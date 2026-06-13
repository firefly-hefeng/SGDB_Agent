"""GEO adapter using NCBI E-utilities."""

import asyncio
import datetime as _dt
import re as _re
import time
import urllib.parse
from typing import Any

import httpx

from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent
from src.discovery.adapters.base import BaseAdapter

# Shared semaphore for all NCBI E-utilities calls
_ncbi_semaphore: asyncio.Semaphore | None = None


def _date_predicate_from_hint(time_hint: str | None) -> str | None:
    """Translate ``intent.time_hint`` into an NCBI ``PDAT`` predicate.

    Supported hint forms:

    - ``"recent"`` / ``"latest"`` / ``"new"`` → last 24 months
    - 4-digit year (``"2024"``) → that year only
    - YYYY-YYYY range (``"2024-2025"``) → inclusive range
    - YYYY+ (``"2024+"``) → year onward

    Returns ``None`` if the hint is empty or unrecognised — the adapter then
    omits the date filter entirely so we don't accidentally narrow results.
    """
    if not time_hint:
        return None
    text = time_hint.strip().lower()
    if not text:
        return None

    today = _dt.date.today()
    if text in {"recent", "latest", "new"}:
        # Last 24 months — captures both 2024 + 2025 in 2026 phrasing.
        start = today.replace(year=today.year - 2)
        return f'("{start:%Y/%m/%d}"[PDAT] : "3000/12/31"[PDAT])'

    # YYYY+
    m = _re.match(r"^(\d{4})\s*\+$", text)
    if m:
        return f'("{m.group(1)}/01/01"[PDAT] : "3000/12/31"[PDAT])'

    # YYYY-YYYY
    m = _re.match(r"^(\d{4})\s*-\s*(\d{4})$", text)
    if m:
        return f'("{m.group(1)}/01/01"[PDAT] : "{m.group(2)}/12/31"[PDAT])'

    # YYYY
    m = _re.match(r"^(\d{4})$", text)
    if m:
        return f'("{m.group(1)}/01/01"[PDAT] : "{m.group(1)}/12/31"[PDAT])'

    return None


def _get_ncbi_semaphore() -> asyncio.Semaphore:
    global _ncbi_semaphore
    if _ncbi_semaphore is None:
        settings = get_settings()
        limit = (
            settings.ncbi_rate_limit_with_key
            if settings.ncbi_api_key
            else settings.ncbi_rate_limit
        )
        _ncbi_semaphore = asyncio.Semaphore(limit)
    return _ncbi_semaphore


class GeoAdapter(BaseAdapter):
    """Adapter for GEO (Gene Expression Omnibus) via NCBI E-utilities."""

    name = "geo"
    _base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    def _build_term(self, intent: QueryIntent) -> str:
        """Build an Entrez query term from intent.

        Strategy (v2.1, after EXP-20260511-06 found the LLM intent parser
        can put a *single short adverb* into ``keywords[0]`` (e.g.
        ``"recent"``), which the previous version blindly used as the entire
        relevance term and produced wildly off-topic GEO results):

        - If ``keywords[0]`` is a substantive query (≥ 3 tokens or > 20
          characters), use it verbatim as the relevance term — NCBI's
          free-text scoring outperforms anything we can build from booleans
          for canonical-paper retrieval.
        - Otherwise, fall back to AND-of-categories
          (disease, tissue, tech — each internally OR-joined for synonyms).
        - Always AND the species filter and ``GSE[Filter]`` to narrow to
          dataset series of the requested organism.
        - When ``intent.time_hint`` is set, append a PDAT predicate.
        """
        parts: list[str] = []

        raw = (intent.keywords[0].strip() if intent.keywords else "")

        # Heuristic: a "substantive" raw query has multiple tokens. A single
        # token like "recent" / "tumor" / "data" is too generic to be the
        # whole relevance term — fall back to category-based construction.
        substantive = bool(raw and (len(raw.split()) >= 3 or len(raw) > 20))

        if substantive:
            parts.append(f"({raw})")
        else:
            cat_parts: list[str] = []
            for group in (intent.disease, intent.tissue, intent.tech):
                if group:
                    joined = " OR ".join(f'"{kw}"' for kw in group)
                    cat_parts.append(f"({joined})")
            if cat_parts:
                parts.extend(cat_parts)
            elif raw:
                # All categories empty AND we have a short keyword — better
                # than nothing.
                parts.append(f"({raw})")

        if intent.species:
            species_str = " OR ".join(
                f'"{sp}"[Organism]' for sp in intent.species
            )
            parts.append(f"({species_str})")

        # Force GSE (dataset series) filter — drops platform / sample records.
        parts.append("GSE[Filter]")

        # Date predicate from `time_hint`. NCBI's PDAT field is YYYY/MM/DD.
        # We translate the supported hints to a closed-on-the-left interval.
        date_pred = _date_predicate_from_hint(intent.time_hint)
        if date_pred:
            parts.append(date_pred)

        # Negation predicate. NCBI eutils supports `term1 NOT term2`; we
        # AND each excluded term as a `NOT "term"` clause so the search
        # both fires on the positive intent AND excludes off-topic records.
        for neg in (intent.negative_terms or [])[:3]:  # cap at 3 to keep term length sane
            neg_clean = neg.strip().strip('"')
            if neg_clean and len(neg_clean) >= 3:
                parts.append(f'NOT "{neg_clean}"')

        return " AND ".join(parts)

    async def _ncbi_get(self, endpoint: str, params: dict[str, Any]) -> dict:
        """Make rate-limited NCBI E-utilities request."""
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        if self.settings.ncbi_email:
            params["email"] = self.settings.ncbi_email

        url = f"{self._base_url}/{endpoint}"
        sem = _get_ncbi_semaphore()

        async with sem:
            resp = await request_with_retry(
                lambda: self.client.get(url, params=params)
            )
            resp.raise_for_status()
            return resp.json()

    async def _esearch(self, term: str, retmax: int) -> tuple[list[str], int]:
        """Run esearch and return ``(uids, total_count)``.

        Sort is intentionally omitted so NCBI's default relevance ordering is
        used. ``sort=date`` (used pre-Phase-5.5) drowned canonical older
        datasets in recent submissions, hurting hit@10 — see Phase 5.5 log.
        Returning the count from the same call removes a redundant network
        round-trip that was previously made just for the total.
        """
        data = await self._ncbi_get(
            "esearch.fcgi",
            {
                "db": "gds",
                "term": term,
                "retmax": retmax,
                "retmode": "json",
            },
        )
        result = data.get("esearchresult", {})
        uids = result.get("idlist", [])
        try:
            total = int(result.get("count", len(uids)))
        except (TypeError, ValueError):
            total = len(uids)
        return uids, total

    async def _esummary(self, uids: list[str]) -> dict[str, Any]:
        """Run esummary and return result dict keyed by UID."""
        if not uids:
            return {}
        data = await self._ncbi_get(
            "esummary.fcgi",
            {
                "db": "gds",
                "id": ",".join(uids),
                "retmode": "json",
            },
        )
        return data.get("result", {})

    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        start_time = time.perf_counter()
        term = self._build_term(intent)

        try:
            uids, total_found = await self._esearch(term, retmax=max_results)
            if not uids:
                return DiscoveryResult(
                    source=self.name,
                    total_found=total_found,
                    results=[],
                    query_url=f"{self._base_url}/esearch.fcgi?db=gds&term={urllib.parse.quote(term)}",
                    latency_ms=int((time.perf_counter() - start_time) * 1000),
                )

            summaries = await self._esummary(uids)
            results = []
            for uid in uids:
                info = summaries.get(uid)
                if not info or not isinstance(info, dict):
                    continue

                accession = info.get("accession", "")
                if not accession:
                    continue

                samples = info.get("samples", [])
                sample_count = info.get("n_samples") or len(samples)

                ftplink = info.get("ftplink", "")
                download_url = ftplink if ftplink else None

                results.append(
                    DatasetResult(
                        id=accession,
                        title=info.get("title", "No title"),
                        description=info.get("summary") or None,
                        organism=info.get("taxon") or None,
                        sample_count=sample_count if sample_count else None,
                        date=info.get("pdat") or None,
                        source_db=self.name.upper(),
                        source_url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}",
                        download_url=download_url,
                        data_type=info.get("gdstype") or None,
                    )
                )

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url=f"{self._base_url}/esearch.fcgi?db=gds&term={urllib.parse.quote(term)}",
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
