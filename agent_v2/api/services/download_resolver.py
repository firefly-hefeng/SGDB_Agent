"""
Download URL resolver — constructs download URLs from database records.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DownloadOption:
    file_type: str
    label: str
    url: str | None
    instructions: str = ""
    source: str = ""


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
            options.extend(self._resolve_hca(project_data or entity_data))

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
        gse = project_data.get("project_id", "")
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
                instructions="Browse and download supplementary files (expression matrices, processed data).",
                source="geo",
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
        project_id = (project_data or entity_data).get("project_id", "")
        sample_id = entity_data.get("sample_id", "")
        series_id = entity_data.get("series_id", "")

        # SRA Run: construct EBI FTP URL
        run_id = sample_id if sample_id.startswith("SRR") else ""
        if not run_id and sample_id.startswith("SRS"):
            run_id = sample_id  # SRS can also be used

        if run_id and run_id.startswith("SRR"):
            prefix6 = run_id[:6]
            if len(run_id) > 9:
                suffix = run_id[-3:].zfill(3)
                ebi_path = f"ftp://ftp.sra.ebi.ac.uk/vol1/fastq/{prefix6}/{suffix}/{run_id}/"
            else:
                ebi_path = f"ftp://ftp.sra.ebi.ac.uk/vol1/fastq/{prefix6}/{run_id}/"
            options.append(DownloadOption(
                file_type="fastq",
                label=f"FASTQ — {run_id}",
                url=ebi_path,
                instructions=f"Download via EBI FTP or SRA Toolkit:\nprefetch {run_id} && fastq-dump --split-files {run_id}",
                source="sra",
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

    def _resolve_ebi(self, project_data: dict) -> list[DownloadOption]:
        project_id = project_data.get("project_id", "")
        options = []

        if project_id.startswith("E-"):
            options.append(DownloadOption(
                file_type="arrayexpress_page",
                label=f"ArrayExpress — {project_id}",
                url=f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{project_id}",
                source="ebi",
            ))
            prefix = project_id.rsplit("-", 1)[0]
            options.append(DownloadOption(
                file_type="matrix",
                label=f"EBI Data Files",
                url=f"https://ftp.ebi.ac.uk/biostudies/fire/{prefix}/{project_id}/",
                instructions="Browse data files on EBI FTP server.",
                source="ebi",
            ))

        return options

    def _resolve_hca(self, project_data: dict) -> list[DownloadOption]:
        access_url = project_data.get("access_url", "")
        project_id = project_data.get("project_id", "")
        if access_url:
            return [DownloadOption(
                file_type="hca_portal",
                label=f"HCA Data Portal — {project_id}",
                url=access_url,
                instructions="Download FASTQ, BAM, or analysis matrices from the HCA Data Portal.",
                source="hca",
            )]
        return []
