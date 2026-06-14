"""EBI Single Cell Expression Atlas (SCEA) adapter.

SCEA (https://www.ebi.ac.uk/gxa/sc) is a curated portal sitting on top of
ArrayExpress / BioStudies that adds standardised differential-expression
analyses and ontology-aligned cell-type annotations. The experiment list is
small (~400 experiments) so we follow the same fetch-all-and-filter strategy
as the CellXGene adapter.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.discovery.adapters.base import BaseAdapter
from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent


class SceaAdapter(BaseAdapter):
    """Adapter for EBI Single Cell Expression Atlas."""

    name = "scea"
    _base_url = "https://www.ebi.ac.uk/gxa/sc"
    _list_endpoint = f"{_base_url}/json/experiments"

    # Class-level cache shared across instances (mirrors CellXGene pattern).
    _cache: list[dict[str, Any]] | None = None
    _cache_timestamp: float = 0.0

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    async def _get_experiments(self) -> list[dict[str, Any]]:
        """Fetch all experiments with TTL caching."""
        now = time.time()
        ttl = self.settings.cellxgene_cache_ttl_seconds  # share TTL setting
        if (
            self._cache is not None
            and (now - self._cache_timestamp) < ttl
        ):
            return self._cache

        resp = await request_with_retry(
            lambda: self.client.get(self._list_endpoint)
        )
        resp.raise_for_status()
        payload = resp.json()
        experiments = payload.get("experiments", []) if isinstance(payload, dict) else []
        type(self)._cache = experiments
        type(self)._cache_timestamp = now
        return experiments

    @staticmethod
    def _searchable_text(exp: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("experimentDescription", "experimentAccession", "species"):
            val = exp.get(key)
            if isinstance(val, str):
                parts.append(val)
        for key in ("experimentalFactors", "technologyType", "experimentProjects"):
            val = exp.get(key)
            if isinstance(val, list):
                parts.extend(str(v) for v in val)
        return " ".join(parts).lower()

    @classmethod
    def _match(cls, intent: QueryIntent, exp: dict[str, Any]) -> bool:
        keywords: list[str] = []
        keywords.extend(intent.disease)
        keywords.extend(intent.tissue)
        keywords.extend(intent.tech)
        # Use the raw query as a relevance signal too — same convention as
        # geo._build_term.
        if intent.keywords:
            keywords.append(intent.keywords[0])

        if not keywords:
            return False

        # Species: SCEA stores binomials; require any species overlap if
        # the user constrained one explicitly (and intent didn't fall back
        # to the human default).
        species_value = str(exp.get("species", "")).lower()
        if intent.species and species_value:
            wanted = {s.lower() for s in intent.species}
            if not any(w in species_value for w in wanted):
                return False

        text = cls._searchable_text(exp)
        return any(kw.lower() in text for kw in keywords if kw)

    @classmethod
    def _relevance(cls, intent: QueryIntent, exp: dict[str, Any]) -> int:
        keywords = intent.disease + intent.tissue + intent.tech
        if intent.keywords:
            keywords.append(intent.keywords[0])
        text = cls._searchable_text(exp)
        return sum(1 for kw in keywords if kw and kw.lower() in text)

    async def search(
        self, intent: QueryIntent, max_results: int = 20
    ) -> DiscoveryResult:
        start_time = time.perf_counter()
        try:
            experiments = await self._get_experiments()
            matches = [e for e in experiments if self._match(intent, e)]
            matches.sort(key=lambda e: self._relevance(intent, e), reverse=True)
            total_found = len(matches)
            matches = matches[:max_results]

            results: list[DatasetResult] = []
            for exp in matches:
                accession = exp.get("experimentAccession", "")
                if not accession:
                    continue
                tech = exp.get("technologyType") or []
                tech_str = ", ".join(tech) if isinstance(tech, list) else str(tech)
                results.append(
                    DatasetResult(
                        id=accession,
                        title=exp.get("experimentDescription") or accession,
                        description=(
                            f"experimentType={exp.get('experimentType', '?')}, "
                            f"factors={exp.get('experimentalFactors', [])}"
                        ),
                        organism=exp.get("species") or None,
                        sample_count=exp.get("numberOfAssays"),
                        date=exp.get("lastUpdate") or exp.get("loadDate") or None,
                        source_db="SCEA",
                        source_url=f"{self._base_url}/experiments/{accession}",
                        download_url=None,
                        data_type=tech_str or "scRNA-seq",
                    )
                )

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url=self._list_endpoint,
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
