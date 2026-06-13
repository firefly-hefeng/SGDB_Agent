"""EBI BioStudies adapter."""

import re
import time
import urllib.parse

import httpx

from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent
from src.discovery.adapters.base import BaseAdapter


# Heuristic organism extraction.
#
# Background (EXP-20260511-03 / H-J): the BioStudies search endpoint returns
# only minimal metadata per hit — no `organism` or `data_type` at the hit
# level. Fetching per-study attributes via `/studies/<accession>` would add
# 5-10 follow-up HTTP calls per query. Instead we extract organism /
# data_type from the title + content text using high-precision patterns.
# The annotator (and downstream reranker) then has at least *some* metadata
# to work with, instead of treating every hit as ``organism=None``
# (which forces a conservative grade-1 by the rubric's missing-metadata rule).
_ORGANISM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:homo[\s_]sapiens|human|humans)\b", re.I), "Homo sapiens"),
    (re.compile(r"\b(?:mus[\s_]musculus|mouse|mice|murine)\b", re.I), "Mus musculus"),
    (re.compile(r"\b(?:rattus[\s_]norvegicus|rat|rats)\b", re.I), "Rattus norvegicus"),
    (re.compile(r"\b(?:macaca[\s_]\w+|macaque|rhesus)\b", re.I), "Macaca mulatta"),
    (re.compile(r"\b(?:danio[\s_]rerio|zebrafish)\b", re.I), "Danio rerio"),
    (re.compile(r"\b(?:drosophila|d\.[\s_]melanogaster|fruit[\s_]fl(?:y|ies))\b", re.I),
        "Drosophila melanogaster"),
    (re.compile(r"\b(?:saccharomyces|yeast|s\.[\s_]cerevisiae)\b", re.I),
        "Saccharomyces cerevisiae"),
    (re.compile(r"\b(?:caenorhabditis|c\.[\s_]elegans|worm)\b", re.I),
        "Caenorhabditis elegans"),
    (re.compile(r"\barabidopsis\b", re.I), "Arabidopsis thaliana"),
)

# Single-cell technology / data-type heuristics. Matched in priority order;
# first match wins. Patterns are deliberately tight to avoid false positives
# on bulk-RNA studies that happen to mention "single cells in tissue".
_DATA_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsnRNA[\s\-]?seq\b|\bsingle[\s\-]?nucleus[\s\-]?(?:RNA[\s\-]?)?seq", re.I),
        "snRNA-seq"),
    (re.compile(r"\bscRNA[\s\-]?seq\b|\bsingle[\s\-]?cell[\s\-]?RNA[\s\-]?seq", re.I),
        "scRNA-seq"),
    (re.compile(r"\bscATAC[\s\-]?seq\b|\bsingle[\s\-]?cell[\s\-]?ATAC[\s\-]?seq", re.I),
        "scATAC-seq"),
    (re.compile(r"\bsnATAC[\s\-]?seq\b", re.I), "snATAC-seq"),
    (re.compile(r"\bCITE[\s\-]?seq\b", re.I), "CITE-seq"),
    (re.compile(r"\bspatial[\s\-]?transcriptomics?\b|\bVisium\b|\bSlide[\s\-]?seq\b"
                r"|\bMERFISH\b|\bseqFISH\b", re.I),
        "spatial transcriptomics"),
    (re.compile(r"\b10x[\s\-]?Genomics\b|\b10x\b", re.I), "10x Genomics"),
    (re.compile(r"\bSmart[\s\-]?seq[2-3]?\b", re.I), "Smart-seq"),
    (re.compile(r"\bDrop[\s\-]?seq\b", re.I), "Drop-seq"),
    (re.compile(r"\b(?:bulk[\s\-]?)?RNA[\s\-]?seq\b", re.I), "RNA-seq"),
)


def _extract_organism(text: str) -> str | None:
    """Return the first matching canonical organism name, or ``None``."""
    if not text:
        return None
    for pat, name in _ORGANISM_PATTERNS:
        if pat.search(text):
            return name
    return None


def _extract_data_type(text: str) -> str | None:
    """Return the first matching canonical data type, or ``None``.

    Single-cell technologies are checked before generic RNA-seq so the
    most specific label wins.
    """
    if not text:
        return None
    for pat, label in _DATA_TYPE_PATTERNS:
        if pat.search(text):
            return label
    return None


# Phase 31.F — single-cell intent detector.
#
# Used by the post-filter that drops obviously-bulk results from BioStudies
# when the user asked for single-cell. R21 / Round-2 R9: a query like
# "human lung scRNA-seq" pulled hundreds of bulk RNA-seq submissions
# diluting the result list. We don't try to be exhaustive — if either the
# tech field or any keyword contains a single-cell signal, switch to
# single-cell mode.
_SINGLE_CELL_SIGNALS = (
    "single cell", "single-cell", "sc-rna", "scrna",
    "snrna", "sn-rna", "single nucleus", "single-nucleus",
    "10x", "10x genomics", "smart-seq", "smart seq",
    "drop-seq", "drop seq", "cite-seq", "cite seq",
    "scatac", "snatac", "spatial transcriptomic",
    "visium", "slide-seq", "merfish", "seqfish",
)


def _wants_single_cell(intent_terms: list[str]) -> bool:
    """True if any term mentions a single-cell modality."""
    for term in intent_terms or []:
        t = (term or "").lower()
        if any(sig in t for sig in _SINGLE_CELL_SIGNALS):
            return True
    return False


# Bulk-only signals — if a title screams "bulk RNA-seq" and the data_type
# extractor only managed "RNA-seq", we treat the hit as bulk and drop it
# under single-cell intent.
_BULK_HINTS = (
    re.compile(r"\bbulk\b", re.I),
    re.compile(r"\bwhole[\s\-]tissue\b", re.I),
    re.compile(r"\bmicroarray\b", re.I),
    re.compile(r"\bChIP[\s\-]?seq\b", re.I),
    re.compile(r"\bATAC[\s\-]?seq\b(?!.*\bsingle\b)", re.I),
)


def _is_bulk_only(result: DatasetResult) -> bool:
    """Heuristic: looks bulk, looks not single-cell.

    We only call this when we already know the caller wanted single-cell —
    so a False here means "keep" (could still be single-cell), and a True
    means "drop, this is clearly not what they asked for".
    """
    dt = (result.data_type or "").lower()
    if "single" in dt or dt in (
        "scrna-seq", "snrna-seq", "scatac-seq", "snatac-seq",
        "cite-seq", "spatial transcriptomics", "10x genomics",
        "smart-seq", "drop-seq",
    ):
        return False
    blob = f"{result.title or ''} {result.description or ''}"
    if any(sig in blob.lower() for sig in _SINGLE_CELL_SIGNALS):
        return False
    # data_type fell back to bulk RNA-seq / nothing AND the title hints bulk.
    return any(p.search(blob) for p in _BULK_HINTS) or dt == "rna-seq"


class EbiAdapter(BaseAdapter):
    """Adapter for EBI BioStudies (includes ArrayExpress data)."""

    name = "ebi"
    _base_url = "https://www.ebi.ac.uk/biostudies/api/v1"

    # Phase 39 W1.5 — data-only filter (fixes the literature-dilution that the
    # 吕同轩 biologist round flagged: the un-scoped BioStudies search returns
    # mostly ``S-EPMC*`` EuroPMC *literature* records, not deposited datasets,
    # so precision was ~40% and ``total_found`` was inflated 2–5×). Restricting
    # to the **ArrayExpress** collection (EMBL-EBI's functional-genomics data
    # archive: E-MTAB / E-GEOD / E-CURD …) returns actual datasets with an
    # honest count. Measured: COVID-lung 2332→1021 hits, all E-MTAB (0 S-EPMC),
    # while clean queries lose only ~5-10% of the count. Set to ``None`` to
    # restore the literature-inclusive behaviour (for the precision ablation).
    _data_collection: str | None = "arrayexpress"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    def _build_query(self, intent: QueryIntent) -> str:
        """Build BioStudies search query from intent.

        EBI's BioStudies search treats space-joined terms as AND-ish
        relevance, so a fully synonym-expanded tissue list (e.g. nine
        brain anatomy terms from ``synonym_map``) both crashes the
        server with HTTP 500 (EXP-20260513-03 round 10, rs-019) and
        narrows recall. We cap each field at its canonical term plus
        one alias; the synonyms still help via post-filter matching at
        the router layer.
        """
        def _head(xs: list[str], n: int = 2) -> list[str]:
            return list(xs[:n]) if xs else []

        parts: list[str] = []
        parts.extend(_head(intent.disease, 2))
        parts.extend(_head(intent.tissue, 2))
        parts.extend(_head(intent.tech, 2))
        parts.extend(_head(intent.keywords, 3))
        return " ".join(parts)

    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        start_time = time.perf_counter()
        query = self._build_query(intent)

        if not query.strip():
            return DiscoveryResult(
                source=self.name,
                total_found=0,
                results=[],
                latency_ms=int((time.perf_counter() - start_time) * 1000),
            )

        try:
            url = f"{self._base_url}/search"
            params: dict[str, str | int] = {
                "query": query,
                "pageSize": max_results,
            }
            # Data-only scoping (see _data_collection): keeps deposited datasets,
            # drops EuroPMC literature, and corrects total_found.
            if self._data_collection:
                params["collection"] = self._data_collection
            resp = await request_with_retry(
                lambda: self.client.get(url, params=params)
            )
            resp.raise_for_status()
            data = resp.json()

            hits = data.get("hits", [])
            total_found = data.get("totalHits", len(hits))

            results = []
            for hit in hits:
                accession = hit.get("accession", "")
                if not accession:
                    continue

                # Determine the correct view URL
                if accession.startswith("E-GEOD-") or accession.startswith("E-MTAB-"):
                    source_url = f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{accession}"
                else:
                    source_url = f"https://www.ebi.ac.uk/biostudies/studies/{accession}"

                title = hit.get("title", "No title")
                content = hit.get("content") or ""
                # Combine title + content for heuristic extraction; title is
                # cheap-and-high-signal, content backstops it.
                text_for_extract = f"{title} {content}"
                organism = _extract_organism(text_for_extract)
                data_type = _extract_data_type(text_for_extract)

                results.append(
                    DatasetResult(
                        id=accession,
                        title=title,
                        description=content or None,
                        organism=organism,
                        # Audit F14: the BioStudies hit's `files` is a FILE count,
                        # not a sample count — surfacing it under "Samples" was
                        # misleading. The search API doesn't expose a sample count,
                        # so report it as unknown rather than wrong.
                        sample_count=None,
                        date=hit.get("release_date") or None,
                        source_db=self.name.upper(),
                        source_url=source_url,
                        download_url=None,
                        data_type=data_type,
                    )
                )

            # Phase 31.F — single-cell post-filter.
            #
            # BioStudies covers literature broadly, so a scRNA-seq query
            # returns many bulk RNA-seq / microarray hits ranked by raw
            # term frequency. If the user clearly asked for single-cell,
            # drop the obviously-bulk results. The full-list `total_found`
            # is preserved separately so the user can see we filtered.
            if _wants_single_cell(intent.tech) or _wants_single_cell(intent.keywords):
                kept = [r for r in results if not _is_bulk_only(r)]
                if kept:
                    results = kept

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url=f"{self._base_url}/search?query={urllib.parse.quote(query)}",
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=0,
                results=[],
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
                latency_ms=latency_ms,
            )

    @property
    def is_available(self) -> bool:
        return True
