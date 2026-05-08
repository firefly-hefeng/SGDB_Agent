"""
GEO supplementary-file resolver — enumerate the *actual* downloadable files for a
GEO series from its FTP directory listing, with sizes.

The catalogue stores only the suppl directory URL (`…/GSExxxxx/suppl/`). The HTML
index of that directory lists the real, separately-downloadable series-level files
(processed matrices, `*_RAW.tar`, metadata) together with their sizes. That is what
single-cell users actually want (processed count/normalized matrices); raw FASTQ for
GEO requires an SRA mapping handled elsewhere.

Note: files listed inside `filelist.txt` as archive *contents* (the per-GSM members of
`*_RAW.tar`) are NOT separately downloadable (HTTP 404) — only the entries shown in the
HTML directory index are. So we parse the index, not filelist.txt.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from src.discovery.http_utils import request_with_retry

logger = logging.getLogger(__name__)

GEO_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/geo/series"

# <a href="GSE131309_RAW.tar">GSE131309_RAW.tar</a>     2020-12-09 16:47  762M
_ROW_RE = re.compile(
    r'<a\s+href="(?P<href>[^"/][^"]*)">[^<]+</a>\s+'
    r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+'
    r'(?P<size>[\d.]+[KMGTP]?|-)',
    re.I,
)

# Files that are metadata about the listing itself, not data.
_SKIP_NAMES = {"filelist.txt", "index.html"}

_MULT = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}


def _parse_human_size(tok: str) -> int | None:
    """'762M' -> ~799 MB in bytes (approximate; the index sizes are rounded)."""
    tok = tok.strip()
    if not tok or tok == "-":
        return None
    m = re.fullmatch(r"([\d.]+)([KMGTP]?)", tok, re.I)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    return int(val * _MULT.get(m.group(2).upper(), 1))


def geo_suppl_url(gse: str) -> str:
    """Directory URL for a GSE's series-level supplementary files."""
    prefix = gse[: len(gse) - 3] + "nnn" if len(gse) > 3 else gse
    return f"{GEO_FTP_BASE}/{prefix}/{gse}/suppl/"


@dataclass
class GeoFile:
    name: str
    url: str
    bytes: int | None = None   # approximate (from rounded index size)
    is_archive: bool = False   # *_RAW.tar — a bundle of per-sample files


@dataclass
class GeoResult:
    gse: str
    ok: bool = False
    suppl_url: str = ""
    files: list[GeoFile] = field(default_factory=list)
    note: str = ""

    @property
    def total_bytes(self) -> int:
        return sum(f.bytes or 0 for f in self.files)


# ── TTL cache ──
_CACHE: dict[str, tuple[float, GeoResult]] = {}
_CACHE_TTL_S = 6 * 3600
_CACHE_MAX = 2048


def _cache_get(k: str) -> GeoResult | None:
    hit = _CACHE.get(k)
    if not hit:
        return None
    ts, val = hit
    if time.monotonic() - ts > _CACHE_TTL_S:
        _CACHE.pop(k, None)
        return None
    return val


def _cache_put(k: str, v: GeoResult) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        for old in sorted(_CACHE, key=lambda x: _CACHE[x][0])[: _CACHE_MAX // 10 or 1]:
            _CACHE.pop(old, None)
    _CACHE[k] = (time.monotonic(), v)


def _parse_listing(gse: str, suppl_url: str, html: str) -> GeoResult:
    files: list[GeoFile] = []
    for m in _ROW_RE.finditer(html):
        href = m.group("href")
        if href.startswith(("http://", "https://", "?", "/")) or href in _SKIP_NAMES:
            continue
        name = href.rstrip("/")
        if name in _SKIP_NAMES:
            continue
        files.append(GeoFile(
            name=name,
            url=suppl_url + href,
            bytes=_parse_human_size(m.group("size")),
            is_archive=name.lower().endswith((".tar", "_raw.tar")),
        ))
    return GeoResult(gse=gse, ok=True, suppl_url=suppl_url, files=files,
                     note="" if files else "no supplementary files listed")


class GeoResolver:
    def __init__(self, timeout: float = 20.0):
        self._timeout = timeout

    async def resolve(
        self, gse: str, client: httpx.AsyncClient | None = None
    ) -> GeoResult:
        gse = (gse or "").strip().upper()
        if not gse.startswith("GSE"):
            return GeoResult(gse=gse, note="not a GEO series accession")
        cached = _cache_get(gse)
        if cached is not None:
            return cached

        suppl_url = geo_suppl_url(gse)
        owns = client is None
        if owns:
            client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        try:
            resp = await request_with_retry(
                lambda: client.get(suppl_url), max_attempts=3
            )
            if resp.status_code != 200:
                res = GeoResult(gse=gse, suppl_url=suppl_url,
                                note=f"GEO FTP HTTP {resp.status_code}")
                _cache_put(gse, res)
                return res
            result = _parse_listing(gse, suppl_url, resp.text)
            _cache_put(gse, result)
            return result
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("GEO suppl resolve failed for %s: %s", gse, exc)
            return GeoResult(gse=gse, suppl_url=suppl_url,
                             note=f"GEO FTP unreachable: {type(exc).__name__}")
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("GEO suppl resolve error for %s: %s", gse, exc)
            return GeoResult(gse=gse, suppl_url=suppl_url, note="GEO error")
        finally:
            if owns:
                await client.aclose()


geo_resolver = GeoResolver()
