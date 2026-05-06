"""
Download URL resolver — constructs download URLs from database records.

Supports: CellXGene, GEO, SRA/NCBI, EBI/ArrayExpress, HCA, EGA
Protocols: HTTPS, FTP, ASPERA (ascp), Cloud (S3/GCS)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from api.services.ena_resolver import ena_resolver, human_bytes, is_ena_accession
from api.services.geo_resolver import geo_resolver


@dataclass
class DownloadOption:
    file_type: str
    label: str
    url: str | None
    instructions: str = ""
    source: str = ""
    download_tool: str = "wget"  # wget | curl | ascp | prefetch | pyega3 | awscli
    file_size_human: str | None = None
    checksum_note: str | None = None
    bytes: int | None = None        # exact size when known (ENA); approximate for GEO
    aspera_url: str | None = None   # ascp source spec (ENA high-speed path)
    md5: str | None = None          # checksum for integrity verification
    run: str | None = None          # SRA run accession (ENA-resolved files)


class DownloadResolver:
    """Resolve download URLs from entity records."""

    def resolve(
        self,
        entity_data: dict,
        series_list: list[dict] | None = None,
        project_data: dict | None = None,
    ) -> list[DownloadOption]:
        source = (
            entity_data.get("source_database")
            or (project_data or {}).get("source_database", "")
        )
        options: list[DownloadOption] = []

        if source == "cellxgene":
            options.extend(self._resolve_cellxgene(series_list or []))
        if source == "geo":
            options.extend(self._resolve_geo(project_data or entity_data))
        if source in ("ncbi", "sra"):
            options.extend(self._resolve_sra(entity_data, project_data))
        if source in ("ebi", "scea"):
            options.extend(self._resolve_ebi(project_data or entity_data))
        if source == "hca":
            # HCA samples often have no parent project row → fall back to the portal pointer.
            options.extend(self._resolve_hca(project_data or entity_data)
                           or self._resolve_portal_pointer(entity_data, "hca"))
        if source in ("psychad", "htan"):
            # Consortium sources present only at the sample tier (no project row) —
            # without an explicit pointer these dead-ended with no download path.
            options.extend(self._resolve_portal_pointer(entity_data, source))
        if source == "ega":
            options.extend(self._resolve_ega(project_data or entity_data))

        # Always add access_url if available
        access_url = (project_data or entity_data).get("access_url")
        if access_url and not any(o.url == access_url for o in options):
            options.append(DownloadOption(
                file_type="page",
                label="Original Data Portal",
                url=access_url,
                source=source,
            ))

        return options

    # ── Deep resolution (live ENA / GEO) ──────────────────────────────────────
    #
    # The baseline `resolve()` above is instant but mostly hands back *pointers*
    # (directory listings, web pages). `resolve_deep()` additionally asks the
    # authoritative archive (ENA Portal API for SRA/ENA, GEO FTP listing for GEO)
    # for the exact files, with byte sizes and MD5 checksums. It is a strict
    # superset of `resolve()`: concrete files are prepended; redundant directory
    # pointers they replace are dropped.

    @staticmethod
    def ena_accession_for(entity_data: dict, project_data: dict | None) -> str | None:
        """Pick the most specific ENA-resolvable accession for an entity.

        Run / sample level (`SRR…`, `SAMEA…`) is preferred over study level
        (`PRJNA…`) so a single sample resolves to just its own files."""
        for candidate in (
            entity_data.get("sample_id"),
            entity_data.get("series_id"),
            (project_data or entity_data).get("project_id"),
            (entity_data or {}).get("project_id"),
        ):
            c = (candidate or "").strip()
            if c and is_ena_accession(c):
                return c
        return None

    @staticmethod
    def gse_for(entity_data: dict, project_data: dict | None) -> str | None:
        pid = ((project_data or entity_data).get("project_id") or "").strip()
        return pid if pid.upper().startswith("GSE") else None

    @staticmethod
    def _ena_file_type(filename: str, kind: str) -> str:
        """Give ENA files a meaningful, selectable type from their extension
        (a submitted BAM should read as 'bam', not the opaque 'submitted')."""
        if kind == "fastq":
            return "fastq"
        n = (filename or "").lower()
        if n.endswith((".bam", ".bam.bai")):
            return "bam"
        if n.endswith((".cram", ".cram.crai")):
            return "cram"
        if n.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
            return "fastq"
        if n.endswith((".h5ad",)):
            return "h5ad"
        return kind  # "submitted" | "sra"

    @staticmethod
    def _geo_file_type(name: str) -> str:
        n = name.lower()
        if n.endswith((".h5ad",)):
            return "h5ad"
        if n.endswith((".rds", ".rda")):
            return "rds"
        if any(k in n for k in ("matrix", "counts", "count.", "_count", "barcodes", "features", ".mtx")):
            return "matrix"
        return "supplementary"

    async def resolve_deep(
        self,
        entity_data: dict,
        series_list: list[dict] | None = None,
        project_data: dict | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[DownloadOption]:
        baseline = self.resolve(entity_data, series_list, project_data)
        source = (
            entity_data.get("source_database")
            or (project_data or {}).get("source_database", "")
        )
        seen = {o.url for o in baseline if o.url}
        concrete: list[DownloadOption] = []

        # 1) ENA (SRA/ENA/NCBI/EBI) — exact runs with sizes + md5 + aspera.
        acc = self.ena_accession_for(entity_data, project_data)
        # EBI/ArrayExpress: the project id is an `E-MTAB…` alias ENA can't query
        # directly. Map it to its brokered ENA study (PRJEB…) so the sequencing
        # data (FASTQ/BAM) resolves — otherwise EBI projects yield 0 concrete files.
        if not acc and (source or "").lower() in ("ebi", "scea"):
            pid = ((project_data or entity_data).get("project_id") or "").strip()
            if pid.upper().startswith("E-"):
                acc = await ena_resolver.resolve_study_alias(pid, client=client)
        if acc:
            r = await ena_resolver.resolve(acc, client=client)
            for f in r.files:
                if not f.url or f.url in seen:
                    continue
                seen.add(f.url)
                aspera_instr = ""
                if f.aspera_url:
                    aspera_instr = (
                        "# High-speed Aspera (10-100x faster; needs aspera-cli):\n"
                        f"ascp -QT -l 300m -P33001 "
                        f"-i $HOME/.aspera/connect/etc/asperaweb_id_dsa.openssh "
                        f"{f.aspera_url} ."
                    )
                ft = self._ena_file_type(f.filename, f.kind)
                concrete.append(DownloadOption(
                    file_type=ft,
                    label=f"{ft.upper()} — {f.run} · {f.filename}",
                    url=f.url,
                    instructions=aspera_instr,
                    source=source or "ena",
                    download_tool="wget",
                    file_size_human=f.size_human,
                    checksum_note=f"md5:{f.md5}" if f.md5 else None,
                    bytes=f.bytes,
                    aspera_url=f.aspera_url,
                    md5=f.md5,
                    run=f.run,
                ))

        # 2) GEO suppl — real processed-matrix files with sizes.
        gse = self.gse_for(entity_data, project_data)
        if gse and (source or "").lower() == "geo":
            g = await geo_resolver.resolve(gse, client=client)
            if g.files:
                # Drop the baseline directory pointer (the suppl/ listing) — the
                # concrete per-file options below supersede it.
                baseline = [o for o in baseline if not (o.url and o.url.rstrip("/") == g.suppl_url.rstrip("/"))]
                seen = {o.url for o in baseline if o.url} | {o.url for o in concrete}
            for f in g.files:
                if not f.url or f.url in seen:
                    continue
                seen.add(f.url)
                concrete.append(DownloadOption(
                    file_type=self._geo_file_type(f.name),
                    label=f"{f.name}" + (" (archive of per-sample files)" if f.is_archive else ""),
                    url=f.url,
                    source="geo",
                    download_tool="wget",
                    file_size_human=(human_bytes(f.bytes) + " (approx)") if f.bytes else None,
                    bytes=f.bytes,
                ))

        # 3) CellxGene — the baseline gives analysis-ready h5ad/rds URLs but no
        #    size (resolve_deep used to be a no-op for cellxgene). HEAD each asset
        #    to fill exact bytes so /estimate is honest and the user sees sizes.
        #    Best-effort, size-only (CellxGene does not publish per-asset md5).
        if (source or "").lower() == "cellxgene":
            await self._size_cellxgene_assets(baseline, client=client)

        return concrete + baseline

    @staticmethod
    async def _size_cellxgene_assets(
        options: list["DownloadOption"], client: httpx.AsyncClient | None = None
    ) -> None:
        """Populate ``bytes``/``file_size_human`` on cellxgene h5ad/rds options
        by issuing a bounded set of HEAD requests (mutates in place)."""
        targets = [o for o in options
                   if o.source == "cellxgene" and o.file_type in ("h5ad", "rds") and o.url]
        if not targets:
            return
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
        sem = asyncio.Semaphore(4)

        async def _head(opt: "DownloadOption") -> None:
            async with sem:
                try:
                    r = await client.head(opt.url)
                    cl = r.headers.get("content-length") or r.headers.get("Content-Length")
                    if not cl and r.status_code in (301, 302, 307, 308):
                        loc = r.headers.get("location")
                        if loc:
                            r = await client.head(loc)
                            cl = r.headers.get("content-length")
                    if cl and cl.isdigit():
                        opt.bytes = int(cl)
                        opt.file_size_human = human_bytes(int(cl))
                except Exception:  # noqa: BLE001 — best-effort sizing
                    pass

        try:
            await asyncio.gather(*[_head(o) for o in targets])
        finally:
            if owns_client:
                await client.aclose()

    def _resolve_cellxgene(self, series_list: list[dict]) -> list[DownloadOption]:
        options = []
        for s in series_list:
            sid = s.get("series_id", "unknown")
            title = s.get("title", sid)[:60]
            if s.get("asset_h5ad_url"):
                options.append(DownloadOption(
                    file_type="h5ad",
                    label=f"H5AD — {title}",
                    url=s["asset_h5ad_url"],
                    instructions="AnnData format. Open with: import scanpy; adata = scanpy.read_h5ad('file.h5ad')",
                    source="cellxgene",
                ))
            if s.get("asset_rds_url"):
                options.append(DownloadOption(
                    file_type="rds",
                    label=f"RDS/Seurat — {title}",
                    url=s["asset_rds_url"],
                    instructions="Seurat format. Open with: library(Seurat); obj <- readRDS('file.rds')",
                    source="cellxgene",
                ))
            if s.get("explorer_url"):
                options.append(DownloadOption(
                    file_type="explorer",
                    label=f"CellXGene Explorer — {title}",
                    url=s["explorer_url"],
                    instructions="Interactive single-cell visualization in browser.",
                    source="cellxgene",
                ))
        return options

    def _resolve_geo(self, project_data: dict) -> list[DownloadOption]:
        gse = project_data.get("project_id") or ""
        if not gse.startswith("GSE"):
            return []

        # GEO FTP: ftp.ncbi.nlm.nih.gov/geo/series/GSEnnn/GSExxxxx/suppl/
        prefix = gse[: len(gse) - 3] + "nnn"
        ftp_url = f"https://ftp.ncbi.nlm.nih.gov/geo/series/{prefix}/{gse}/suppl/"

        return [
            DownloadOption(
                file_type="supplementary",
                label=f"GEO Supplementary Files ({gse})",
                url=ftp_url,
                instructions=(
                    f"# Download all supplementary files:\n"
                    f"wget -r -np -nH --cut-dirs=5 -R 'index.html*' '{ftp_url}'\n\n"
                    f"# Or browse files at: {ftp_url}"
                ),
                source="geo",
            ),
            DownloadOption(
                file_type="geo_soft",
                label=f"GEO SOFT Metadata — {gse}",
                url=f"https://ftp.ncbi.nlm.nih.gov/geo/series/{prefix}/{gse}/soft/{gse}_family.soft.gz",
                instructions="Full metadata in SOFT format. Parse with: pip install GEOparse; import GEOparse; gse = GEOparse.get_GEO(filepath='file.soft.gz')",
                source="geo",
                download_tool="wget",
            ),
            DownloadOption(
                file_type="geo_page",
                label=f"GEO Record — {gse}",
                url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={gse}",
                source="geo",
            ),
        ]

    def _resolve_sra(self, entity_data: dict, project_data: dict | None) -> list[DownloadOption]:
        options = []
        # NB: dict.get(k, default) returns the stored value even when it is None
        # (a NULL DB column), so coerce explicitly — `project_id` is None for
        # bare NCBI biosamples and would otherwise crash `.startswith`.
        project_id = (project_data or entity_data).get("project_id") or ""
        sample_id = entity_data.get("sample_id") or ""
        series_id = entity_data.get("series_id") or ""

        # SRA Run: construct EBI FTP URL
        run_id = sample_id if sample_id.startswith("SRR") else ""
        if not run_id and sample_id.startswith("SRS"):
            run_id = sample_id

        if run_id and run_id.startswith("SRR"):
            prefix6 = run_id[:6]
            if len(run_id) > 9:
                suffix = run_id[-3:].zfill(3)
                ebi_path = f"ftp://ftp.sra.ebi.ac.uk/vol1/fastq/{prefix6}/{suffix}/{run_id}/"
            else:
                ebi_path = f"ftp://ftp.sra.ebi.ac.uk/vol1/fastq/{prefix6}/{run_id}/"

            # Modern SRA Toolkit instructions
            options.append(DownloadOption(
                file_type="fastq",
                label=f"FASTQ — {run_id}",
                url=ebi_path,
                instructions=(
                    f"# Method 1: SRA Toolkit (recommended, multi-threaded)\n"
                    f"prefetch --max-size 100G {run_id}\n"
                    f"vdb-validate {run_id}\n"
                    f"fasterq-dump --split-files --threads 8 --progress {run_id}\n"
                    f"pigz -p 8 {run_id}_*.fastq\n\n"
                    f"# Method 2: Direct FTP download\n"
                    f"wget -r -np '{ebi_path}'"
                ),
                source="sra",
                download_tool="prefetch",
            ))

            # ASPERA high-speed option
            aspera_path = self._build_aspera_path(run_id)
            if aspera_path:
                options.append(DownloadOption(
                    file_type="fastq_aspera",
                    label=f"FASTQ (ASPERA 10-100x faster) — {run_id}",
                    url=None,
                    instructions=(
                        f"# ASPERA high-speed download (10-100x faster than FTP)\n"
                        f"# Install: conda install -c hcc aspera-cli\n"
                        f"# Or: conda install -c bioconda aspera-connect\n\n"
                        f"ascp -QT -l 300m -P33001 \\\n"
                        f"  -i $HOME/.aspera/connect/etc/asperaweb_id_dsa.openssh \\\n"
                        f"  {aspera_path} ."
                    ),
                    source="sra",
                    download_tool="ascp",
                ))

        if series_id and series_id.startswith("SRP"):
            options.append(DownloadOption(
                file_type="sra_page",
                label=f"SRA Study — {series_id}",
                url=f"https://www.ncbi.nlm.nih.gov/sra/?term={series_id}",
                source="sra",
            ))

        if project_id.startswith("PRJNA"):
            options.append(DownloadOption(
                file_type="bioproject_page",
                label=f"BioProject — {project_id}",
                url=f"https://www.ncbi.nlm.nih.gov/bioproject/{project_id}",
                source="sra",
            ))

        return options

    def _build_aspera_path(self, run_id: str) -> str | None:
        """Build ASPERA path for an SRR run ID."""
        if not run_id.startswith("SRR"):
            return None
        prefix6 = run_id[:6]
        if len(run_id) > 9:
            suffix = run_id[-3:].zfill(3)
            return f"era-fasp@fasp.sra.ebi.ac.uk:vol1/fastq/{prefix6}/{suffix}/{run_id}/"
        return f"era-fasp@fasp.sra.ebi.ac.uk:vol1/fastq/{prefix6}/{run_id}/"

    def _resolve_ebi(self, project_data: dict) -> list[DownloadOption]:
        project_id = project_data.get("project_id") or ""
        options = []

        if project_id.startswith("E-"):
            options.append(DownloadOption(
                file_type="arrayexpress_page",
                label=f"ArrayExpress — {project_id}",
                url=f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{project_id}",
                source="ebi",
            ))
            # Audit F11: the old `ftp.ebi.ac.uk/biostudies/fire/<prefix>/<id>/`
            # URL is a hard 404. The BioStudies file endpoint serves the real,
            # downloadable experiment metadata (SDRF maps each sample → assay →
            # data file; IDF is the experiment design). The raw sequencing data
            # itself is added by resolve_deep via the E-MTAB→ENA-study mapping.
            files_base = f"https://www.ebi.ac.uk/biostudies/files/{project_id}"
            options.append(DownloadOption(
                file_type="metadata",
                label=f"SDRF — sample↔data table ({project_id})",
                url=f"{files_base}/{project_id}.sdrf.txt",
                instructions=("Sample and Data Relationship Format: one row per assay, "
                              "linking each sample to its raw/processed data files."),
                source="ebi",
            ))
            options.append(DownloadOption(
                file_type="metadata",
                label=f"IDF — experiment design ({project_id})",
                url=f"{files_base}/{project_id}.idf.txt",
                instructions="Investigation Description Format: protocols + experiment design.",
                source="ebi",
            ))

        return options

    # Consortium portals that distribute data outside the standard archives.
    _PORTAL_POINTERS = {
        "psychad": (
            "https://www.synapse.org/",
            "PsychAD (PsychENCODE) — via Synapse",
            "PsychAD single-nucleus data is distributed through Synapse (PsychENCODE "
            "consortium). Register for a Synapse account, accept the data-use terms, then "
            "search for the PsychAD study and locate this record id.",
        ),
        "htan": (
            "https://data.humantumoratlas.org/",
            "HTAN Data Portal",
            "Human Tumor Atlas Network data. Browse/download Level 1-4 files "
            "(FASTQ/BAM/expression matrices) from the HTAN Data Portal; search by the "
            "HTAN biospecimen/participant id below.",
        ),
        "hca": (
            "https://data.humancellatlas.org/explore",
            "HCA Data Portal",
            "Human Cell Atlas data. Download FASTQ/BAM/analysis matrices from the HCA "
            "Data Portal; search by project or the record id below.",
        ),
    }

    def _resolve_portal_pointer(self, entity_data: dict, source: str) -> list[DownloadOption]:
        cfg = self._PORTAL_POINTERS.get(source)
        if not cfg:
            return []
        default_url, label, instr = cfg
        url = (entity_data or {}).get("access_url") or default_url
        rec = (entity_data or {}).get("sample_id") or (entity_data or {}).get("project_id") or ""
        return [DownloadOption(
            file_type=f"{source}_portal",
            label=label,
            url=url,
            instructions=instr + (f"\n\nThis record: {rec}" if rec else ""),
            source=source,
        )]

    def _resolve_hca(self, project_data: dict) -> list[DownloadOption]:
        access_url = project_data.get("access_url") or ""
        project_id = project_data.get("project_id") or ""
        if access_url:
            return [DownloadOption(
                file_type="hca_portal",
                label=f"HCA Data Portal — {project_id}",
                url=access_url,
                instructions=(
                    "Download FASTQ, BAM, or analysis matrices from the HCA Data Portal.\n"
                    "Supports: loom, h5ad, csv matrix formats."
                ),
                source="hca",
            )]
        return []

    def _resolve_ega(self, project_data: dict) -> list[DownloadOption]:
        """Resolve EGA (European Genome-phenome Archive) controlled access data."""
        project_id = project_data.get("project_id") or ""
        if not project_id.startswith(("EGAD", "EGAS")):
            return []

        return [
            DownloadOption(
                file_type="ega_metadata",
                label=f"EGA Dataset — {project_id}",
                url=f"https://ega-archive.org/datasets/{project_id}",
                instructions=(
                    f"# EGA: Controlled access data (requires DAC approval)\n\n"
                    f"# Step 1: Apply for data access\n"
                    f"# Visit: https://ega-archive.org/datasets/{project_id}\n"
                    f"# Submit access request to the Data Access Committee (DAC)\n\n"
                    f"# Step 2: After approval, download with PyEGA3\n"
                    f"pip install pyega3\n"
                    f"pyega3 -cf credentials.json fetch {project_id}\n\n"
                    f"# credentials.json format:\n"
                    f'# {{"username": "ega-box-xxx", "password": "your-password"}}'
                ),
                source="ega",
                download_tool="pyega3",
            ),
        ]
