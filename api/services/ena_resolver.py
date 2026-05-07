"""
ENA Portal API resolver — turn an accession into concrete, sized, checksummed files.

The local catalogue stores *pointers* (web pages, FTP directory listings). For the
GEO / NCBI / EBI majority of the catalogue (~13.5 k projects, ~630 k samples) the
authoritative file list lives in the European Nucleotide Archive (ENA), which mirrors
SRA. ENA's `filereport` endpoint resolves an accession into the exact run-level files
with byte sizes and MD5 checksums — including high-speed Aspera paths.

This module is the universal "deep" resolver behind `DownloadResolver.resolve_deep`.

Verified accession coverage (against this DB's id space):
  - sample      SAMEA…/SAMN…/SAMD…   (217 k NCBI + 94 k EBI samples)
  - study       PRJNA…/PRJEB…/PRJDB… (8 156 NCBI projects via project_id)
  - run         SRR…/ERR…/DRR…
  - secondary   SRP…/ERP…/DRP…  (study)   SRS…/ERS…/DRS… (sample)
  - experiment  SRX…/ERX…/DRX…

ENA does NOT accept GEO (GSE/GSM) or ArrayExpress (E-MTAB) accessions directly —
those are handled by source-specific paths in DownloadResolver.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from src.discovery.http_utils import request_with_retry

logger = logging.getLogger(__name__)

ENA_FILEREPORT = "https://www.ebi.ac.uk/ena/portal/api/filereport"
ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"

# Fields requested from ENA. Order matters only for our own parsing clarity.
_FIELDS = (
    "run_accession,sample_accession,experiment_accession,"
    "fastq_ftp,fastq_bytes,fastq_md5,fastq_aspera,"
    "submitted_ftp,submitted_bytes,submitted_md5,"
    "sra_ftp,sra_bytes,sra_md5,"
    "library_strategy,library_layout,read_count"
)

# Accession-type detection. Each entry: (regex, ENA `result` type). We only need
# read_run; the regexes exist so we can *reject* non-ENA ids without a network call.
_ACCESSION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^SAME[AD]?\d{6,}$", re.I), "sample"),
    (re.compile(r"^SAM[ND]\d{6,}$", re.I), "sample"),
    (re.compile(r"^PRJ[A-Z]{2}\d+$", re.I), "study"),
    (re.compile(r"^[EDS]RP\d{6,}$", re.I), "study_secondary"),
    (re.compile(r"^[EDS]RS\d{6,}$", re.I), "sample_secondary"),
    (re.compile(r"^[EDS]RX\d{6,}$", re.I), "experiment"),
    (re.compile(r"^[EDS]RR\d{6,}$", re.I), "run"),
    (re.compile(r"^[EDS]RA\d{6,}$", re.I), "submission"),
)


def is_ena_accession(accession: str) -> bool:
    """True iff ENA `filereport` can resolve this accession directly."""
    a = (accession or "").strip()
    return any(p.match(a) for p, _ in _ACCESSION_PATTERNS)


def human_bytes(n: int | None) -> str | None:
    """1234567 -> '1.2 MB'. None/0 -> None."""
    if not n or n < 0:
        return None
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.0f} {u}" if u == "B" else f"{f:.1f} {u}"
        f /= 1024
    return None


def _https(ftp_path: str) -> str:
    """Rewrite a bare ENA FTP path to a resumable HTTPS URL.

    ENA returns e.g. ``ftp.sra.ebi.ac.uk/vol1/fastq/…``. The same host serves the
    file over HTTPS (verified), which is firewall-friendly and works with
    wget/curl/aria2 without an FTP client.
    """
    p = ftp_path.strip()
    if not p:
        return ""
    if p.startswith(("http://", "https://", "ftp://")):
        return p
    return "https://" + p


def _aspera(fasp_path: str) -> str:
    """`fasp.sra.ebi.ac.uk:/vol1/…` -> a full `ascp` source spec with the ENA user."""
    p = fasp_path.strip()
    if not p:
        return ""
    if "@" in p.split(":", 1)[0]:
        return p
    return "era-fasp@" + p


@dataclass
class EnaFile:
    """One physical, directly-downloadable file."""
    run: str
    url: str                       # https
    bytes: int | None = None
    md5: str | None = None
    aspera_url: str | None = None  # ascp source spec
    kind: str = "fastq"            # fastq | submitted | sra
    sample: str = ""
    experiment: str = ""
    library_strategy: str = ""
    library_layout: str = ""

    @property
    def filename(self) -> str:
        return self.url.rstrip("/").split("/")[-1] or self.run

    @property
    def size_human(self) -> str | None:
        return human_bytes(self.bytes)


@dataclass
class EnaResult:
    accession: str
    ok: bool = False
    files: list[EnaFile] = field(default_factory=list)
    note: str = ""

    @property
    def run_count(self) -> int:
        return len({f.run for f in self.files if f.run})

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes or 0 for f in self.files)


# ── TTL + LRU cache (single event loop; no lock needed) ──

_CACHE: dict[str, tuple[float, EnaResult]] = {}
_CACHE_TTL_S = 6 * 3600
_CACHE_MAX = 4096


def _cache_get(key: str) -> EnaResult | None:
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.monotonic() - ts > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_put(key: str, val: EnaResult) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop the oldest ~10% to amortise eviction cost.
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: _CACHE_MAX // 10 or 1]:
            _CACHE.pop(k, None)
    _CACHE[key] = (time.monotonic(), val)


def _parse_row(row: dict[str, str]) -> list[EnaFile]:
    """One ENA TSV row may describe several files (the multi-value `;` columns).
    Prefer fastq; fall back to submitted, then sra."""
    run = (row.get("run_accession") or "").strip()
    sample = (row.get("sample_accession") or "").strip()
    exp = (row.get("experiment_accession") or "").strip()
    lib_strat = (row.get("library_strategy") or "").strip()
    lib_layout = (row.get("library_layout") or "").strip()

    def split(col: str) -> list[str]:
        v = (row.get(col) or "").strip()
        return [x for x in v.split(";") if x] if v else []

    for kind, ftp_col, bytes_col, md5_col, aspera_col in (
        ("fastq", "fastq_ftp", "fastq_bytes", "fastq_md5", "fastq_aspera"),
        ("submitted", "submitted_ftp", "submitted_bytes", "submitted_md5", None),
        ("sra", "sra_ftp", "sra_bytes", "sra_md5", None),
    ):
        ftps = split(ftp_col)
        if not ftps:
            continue
        sizes = split(bytes_col)
        md5s = split(md5_col)
        asperas = split(aspera_col) if aspera_col else []
        out: list[EnaFile] = []
        for i, ftp in enumerate(ftps):
            try:
                b = int(sizes[i]) if i < len(sizes) and sizes[i] else None
            except ValueError:
                b = None
            out.append(EnaFile(
                run=run,
                url=_https(ftp),
                bytes=b,
                md5=md5s[i] if i < len(md5s) else None,
                aspera_url=_aspera(asperas[i]) if i < len(asperas) else None,
                kind=kind,
                sample=sample,
                experiment=exp,
                library_strategy=lib_strat,
                library_layout=lib_layout,
            ))
        return out  # first non-empty file class wins
    return []


class EnaResolver:
    """Async ENA filereport client with a TTL cache."""

    def __init__(self, timeout: float = 25.0, max_rows: int = 5000):
        self._timeout = timeout
        self._max_rows = max_rows

    async def resolve(
        self, accession: str, client: httpx.AsyncClient | None = None
    ) -> EnaResult:
        a = (accession or "").strip()
        if not a:
            return EnaResult(accession=a, note="empty accession")
        if not is_ena_accession(a):
            return EnaResult(accession=a, note="not an ENA-resolvable accession")

        cached = _cache_get(a)
        if cached is not None:
            return cached

        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        try:
            params = {
                "accession": a,
                "result": "read_run",
                "fields": _FIELDS,
                "format": "tsv",
                "limit": str(self._max_rows),
            }
            resp = await request_with_retry(
                lambda: client.get(ENA_FILEREPORT, params=params),
                max_attempts=3,
            )
            if resp.status_code != 200:
                res = EnaResult(accession=a, note=f"ENA HTTP {resp.status_code}")
                _cache_put(a, res)
                return res
            result = self._parse_tsv(a, resp.text)
            _cache_put(a, result)
            return result
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("ENA resolve failed for %s: %s", a, exc)
            # Do NOT cache transient failures — let the next request retry.
            return EnaResult(accession=a, note=f"ENA unreachable: {type(exc).__name__}")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("ENA resolve unexpected error for %s: %s", a, exc)
            return EnaResult(accession=a, note="ENA error")
        finally:
            if owns_client:
                await client.aclose()

    def _parse_tsv(self, accession: str, text: str) -> EnaResult:
        lines = text.splitlines()
        if not lines:
            return EnaResult(accession=accession, ok=True, files=[], note="no files")
        # An invalid accession returns a plain-text error, not a TSV header.
        header = lines[0].split("\t")
        if "run_accession" not in header:
            return EnaResult(accession=accession, note=lines[0][:200].strip())
        files: list[EnaFile] = []
        for ln in lines[1:]:
            if not ln.strip():
                continue
            cols = ln.split("\t")
            row = {header[i]: (cols[i] if i < len(cols) else "") for i in range(len(header))}
            files.extend(_parse_row(row))
        return EnaResult(accession=accession, ok=True, files=files)

    async def resolve_study_alias(
        self, alias: str, client: httpx.AsyncClient | None = None
    ) -> str | None:
        """Map a submitter study alias (e.g. ArrayExpress `E-MTAB-10018`) to its ENA
        study accession (`PRJEB…`), which `filereport` *can* resolve. Cached.

        ArrayExpress/BioStudies sequencing data is brokered to ENA: the reads live
        under a `PRJEB…` whose `study_alias` is the `E-MTAB…` id. Without this hop,
        EBI projects resolve to zero concrete files."""
        a = (alias or "").strip()
        if not a:
            return None
        ck = f"alias:{a}"
        cached = _cache_get(ck)
        if cached is not None:
            return cached.accession or None

        owns = client is None
        if owns:
            client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        try:
            params = {
                "result": "study",
                "query": f'study_alias="{a}"',
                "fields": "study_accession,secondary_study_accession",
                "format": "tsv",
                "limit": "1",
            }
            resp = await request_with_retry(
                lambda: client.get(ENA_SEARCH, params=params), max_attempts=3
            )
            study = ""
            if resp.status_code == 200:
                lines = resp.text.splitlines()
                if len(lines) >= 2:
                    header = lines[0].split("\t")
                    cols = lines[1].split("\t")
                    row = {header[i]: (cols[i] if i < len(cols) else "")
                           for i in range(len(header))}
                    study = (row.get("study_accession")
                             or row.get("secondary_study_accession") or "").strip()
            # Cache the answer (even an empty one — most aliases are stable).
            _cache_put(ck, EnaResult(accession=study, ok=bool(study)))
            return study or None
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("ENA alias resolve failed for %s: %s", a, exc)
            return None
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("ENA alias resolve error for %s: %s", a, exc)
            return None
        finally:
            if owns:
                await client.aclose()

    async def resolve_many(
        self, accessions: list[str], concurrency: int = 6
    ) -> dict[str, EnaResult]:
        """Resolve several accessions concurrently behind one client + semaphore."""
        uniq = list(dict.fromkeys(a.strip() for a in accessions if a and a.strip()))
        results: dict[str, EnaResult] = {}
        sem = asyncio.Semaphore(max(1, concurrency))
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            async def one(acc: str) -> None:
                async with sem:
                    results[acc] = await self.resolve(acc, client=client)
            await asyncio.gather(*(one(a) for a in uniq))
        return results


# Module-level singleton (cache is shared across requests).
ena_resolver = EnaResolver()
