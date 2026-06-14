"""HCA (Human Cell Atlas) Azul API adapter."""

import json
import logging
import time
import urllib.parse

import httpx

from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent
from src.discovery.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)


class HcaAdapter(BaseAdapter):
    """Adapter for HCA Data Portal via Azul API.

    Phase 31.F — Azul's facets are controlled vocabularies. A filter built
    from ``intent.disease=["lung cancer"]`` returns 0 hits even when the
    portal has matching studies labelled "lung adenocarcinoma" or "NSCLC"
    (no fuzzy match, no synonym table on the server). To recover recall
    we run a two-pass search: filtered first (precise), then if it
    returns nothing AND the intent has terms we fall back to an
    unfiltered catalog sweep and post-filter client-side by case-folded
    substring match across title+description. The fallback prefers
    "fewer-but-relevant" over "many-irrelevant" — we cap the unfiltered
    page at 100 hits and only keep ones whose text touches any tissue or
    disease term.
    """

    name = "hca"
    _base_url = "https://service.azul.data.humancellatlas.org"
    _catalog = "dcp59"
    # Azul rejects ``size`` > 75 with a 400 BadRequestError, so every page
    # request is clamped to this hard ceiling (see ``_fetch_page``). The
    # fallback sweep paginates across pages to still scan the whole catalog.
    _AZUL_MAX_PAGE_SIZE = 75
    # The unfiltered sweep scans at most this many projects across at most
    # this many sequential page requests. Kept deliberately small: each
    # 75-hit Azul page is a heavy response (~5 s), and HCA is one of several
    # sources fanned out in parallel — letting it scan the whole ~500-project
    # catalog would make it dominate total discovery latency and risk the
    # 30 s adapter timeout. 150/2 recovers synonym-mismatch recall while
    # staying comparable to the other sources.
    _FALLBACK_SCAN_SIZE = 150
    _FALLBACK_MAX_PAGES = 2

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    def _build_filters(self, intent: QueryIntent) -> dict:
        """Build Azul filter object from intent."""
        filters: dict = {}

        # Disease filter
        if intent.disease:
            filters["sampleDisease"] = {"is": intent.disease}

        # Organ filter (map tissue to organ)
        if intent.tissue:
            # Try specimenOrgan first; Azul has organ facets
            filters["specimenOrgan"] = {"is": intent.tissue}

        # Species filter
        if intent.species:
            filters["genusSpecies"] = {"is": intent.species}

        return filters

    async def _fetch_page(
        self, filters: dict, size: int, include_filters: bool = True
    ) -> tuple[list[dict], int, str, str | None]:
        """Single Azul page fetch.

        Returns ``(hits, total_found, query_url, next_url)``. ``size`` is
        clamped to Azul's hard ceiling of 75 — requesting more returns a
        400 ``BadRequestError`` rather than a truncated page.
        """
        params: dict = {
            "catalog": self._catalog,
            "size": min(size, self._AZUL_MAX_PAGE_SIZE),
            "sort": "projectTitle",
            "order": "asc",
        }
        if include_filters and filters:
            params["filters"] = json.dumps(filters)

        resp = await request_with_retry(
            lambda: self.client.get(
                f"{self._base_url}/index/projects", params=params
            )
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        pagination = data.get("pagination", {}) or {}
        total = pagination.get("total", len(hits))
        next_url = pagination.get("next")
        query_url = f"{self._base_url}/index/projects?{urllib.parse.urlencode(params)}"
        return hits, total, query_url, next_url

    async def _fetch_url(self, url: str) -> tuple[list[dict], str | None]:
        """Follow an Azul ``pagination.next`` cursor URL. Returns
        ``(hits, next_url)``."""
        resp = await request_with_retry(lambda: self.client.get(url))
        resp.raise_for_status()
        data = resp.json()
        return data.get("hits", []), (data.get("pagination", {}) or {}).get("next")

    def _intent_keywords(self, intent: QueryIntent) -> list[str]:
        """Lowercase, deduped pool of substrings we'll match against title+desc
        text when filters return nothing. Pulled from disease + tissue + tech
        + free-form keywords — species is excluded because almost every HCA
        project is human and the term ``human`` over-matches."""
        pool: list[str] = []
        for src in (intent.disease, intent.tissue, intent.tech, intent.keywords):
            pool.extend(src or [])
        out: list[str] = []
        seen: set[str] = set()
        for term in pool:
            t = (term or "").strip().lower()
            if not t or t in seen or len(t) < 3:
                continue
            seen.add(t)
            out.append(t)
        return out

    def _hit_to_result(self, hit: dict) -> DatasetResult | None:
        entry_id = hit.get("entryId", "")
        projects = hit.get("projects", [])
        if not entry_id or not projects:
            return None
        project = projects[0]
        title = project.get("projectTitle", "No title")
        description = project.get("projectDescription") or None

        organisms = hit.get("donorOrganisms", [])
        organism = None
        if organisms:
            species_list = organisms[0].get("genusSpecies", [])
            if species_list:
                organism = species_list[0]

        cell_count = None
        suspensions = hit.get("cellSuspensions", [])
        if suspensions:
            cell_count = suspensions[0].get("estimatedCellCount")

        return DatasetResult(
            id=entry_id,
            title=title,
            description=description,
            organism=organism,
            sample_count=cell_count,
            date=None,
            source_db="HCA",
            source_url=f"https://data.humancellatlas.org/explore/projects/{entry_id}",
            download_url=None,
            data_type="scRNA-seq",
        )

    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        start_time = time.perf_counter()

        try:
            filters = self._build_filters(intent)
            keywords = self._intent_keywords(intent)

            hits, total_found, query_url, _next = await self._fetch_page(
                filters, size=max_results, include_filters=True
            )

            # Fallback pass — Azul's controlled-vocabulary facets often miss
            # synonym-equivalent labels (lung cancer ≠ lung adenocarcinoma).
            # If we got nothing and there's anything to match on, sweep the
            # catalog unfiltered (paging across up to _FALLBACK_MAX_PAGES) and
            # keep hits whose text touches an intent term.
            used_fallback = False
            if not hits and keywords and filters:
                used_fallback = True
                sweep_hits, _sweep_total, query_url, next_url = await self._fetch_page(
                    filters={}, size=self._AZUL_MAX_PAGE_SIZE, include_filters=False
                )
                scanned = len(sweep_hits)
                pages = 1
                hits = []
                while True:
                    for h in sweep_hits:
                        projects = h.get("projects", [])
                        if not projects:
                            continue
                        title = (projects[0].get("projectTitle") or "").lower()
                        desc = (projects[0].get("projectDescription") or "").lower()
                        blob = f"{title} {desc}"
                        if any(kw in blob for kw in keywords):
                            hits.append(h)
                    if (
                        len(hits) >= max_results
                        or not next_url
                        or pages >= self._FALLBACK_MAX_PAGES
                        or scanned >= self._FALLBACK_SCAN_SIZE
                    ):
                        break
                    sweep_hits, next_url = await self._fetch_url(next_url)
                    scanned += len(sweep_hits)
                    pages += 1
                hits = hits[:max_results]
                logger.info(
                    "HCA fallback: filtered=0, scanned %d projects across %d page(s) "
                    "for keywords %s → %d match(es)",
                    scanned, pages, keywords, len(hits),
                )
                total_found = len(hits)

            results: list[DatasetResult] = []
            for hit in hits:
                r = self._hit_to_result(hit)
                if r is not None:
                    results.append(r)

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url=query_url + (";fallback=keyword" if used_fallback else ""),
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
