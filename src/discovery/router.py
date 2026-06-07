"""Discovery router: dispatches queries to all adapters concurrently."""

import asyncio
import time
from typing import Any, AsyncIterator

from src.discovery.adapters import ADAPTERS
from src.discovery.config import get_settings
from src.discovery.deduplicator import annotate_mirrors
from src.discovery.metrics import get_registry
from src.discovery.models import DiscoveryResponse, DiscoveryResult, QueryIntent
from src.discovery.reranker import Reranker, get_reranker


class DiscoveryRouter:
    """Routes discovery queries to all enabled adapters concurrently."""

    def __init__(
        self,
        enabled_sources: list[str] | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.settings = get_settings()
        if enabled_sources is None:
            enabled_sources = list(ADAPTERS.keys())

        self.adapters = []
        for name in enabled_sources:
            adapter_cls = ADAPTERS.get(name)
            if adapter_cls:
                self.adapters.append(adapter_cls())

        self.reranker = reranker if reranker is not None else get_reranker()

    def _select_adapters(self, intent: QueryIntent) -> list:
        """Apply ``intent.restrict_sources`` to the configured adapter list.

        If the intent names specific sources (e.g. user wrote "show me
        CellXGene datasets…"), filter ``self.adapters`` down to those.
        If the restriction is set but nothing matches our adapters,
        fall back to all configured adapters (defensive — better to
        return *something* than silently return zero results).
        """
        if not intent.restrict_sources:
            return self.adapters
        wanted = {s.lower() for s in intent.restrict_sources}
        filtered = [a for a in self.adapters if a.name.lower() in wanted]
        return filtered or self.adapters

    @staticmethod
    def _apply_year_filter(
        result: DiscoveryResult, intent: QueryIntent
    ) -> None:
        """Drop hits whose parsed year conflicts with `intent.time_hint`.

        Closes H-O at the router layer. GEO already filters at the API
        via the ``[PDAT]`` predicate, but EBI / SCEA / CellXGene / HCA
        don't — they would return mixed-year results that drag the
        synthesizer down. This post-filter mirrors `_apply_species_filter`:

        - Only fires when `intent.time_hint` matches a year pattern
          (single ``YYYY``, ``YYYY-YYYY``, or ``YYYY+``); ``recent`` /
          ``latest`` / ``new`` are *advisory* and not strict, so we
          preserve those rows.
        - Skips rows where the date cannot be parsed (preserves recall
          when source metadata is sparse).
        """
        import re as _re

        hint = (intent.time_hint or "").strip().lower()
        if not hint:
            return
        m_single = _re.match(r"^(\d{4})$", hint)
        m_range = _re.match(r"^(\d{4})\s*-\s*(\d{4})$", hint)
        m_plus = _re.match(r"^(\d{4})\s*\+$", hint)
        if not (m_single or m_range or m_plus):
            return  # 'recent' / unrecognised: no strict filter
        if m_single:
            lo = hi = int(m_single.group(1))
        elif m_range:
            lo, hi = int(m_range.group(1)), int(m_range.group(2))
        else:
            lo, hi = int(m_plus.group(1)), 9999  # type: ignore[union-attr]

        kept: list = []
        for r in result.results:
            if not r.date:
                kept.append(r)  # unknown date — preserve
                continue
            year_match = _re.search(r"(19|20)\d{2}", str(r.date))
            if not year_match:
                kept.append(r)
                continue
            year = int(year_match.group(0))
            if lo <= year <= hi:
                kept.append(r)
        result.results = kept

    @staticmethod
    def _apply_species_filter(
        result: DiscoveryResult, intent: QueryIntent
    ) -> None:
        """Drop hits whose ``organism`` is set and conflicts with intent.species.

        Closes H-Q: only the GEO adapter applies a strict `[Organism]`
        filter at the API. For other adapters (EBI, SCEA, HCA, CellXGene),
        a query for ``zebrafish brain`` was returning mixed-species hits.
        This post-filter removes results whose populated organism does NOT
        match the requested species. Results with ``organism=None`` pass
        through untouched (better to return uncertain hits than silently
        drop them; the synthesizer can flag species ambiguity).
        """
        # Skip when intent species is the default human-only (avoids
        # filtering anything when the user didn't constrain species).
        if not intent.species or intent.species == ["Homo sapiens"]:
            return
        wanted = {s.lower() for s in intent.species}
        kept: list = []
        for r in result.results:
            org = (r.organism or "").lower()
            if not org:
                kept.append(r)  # unknown organism — keep
                continue
            if any(w in org or org in w for w in wanted):
                kept.append(r)
        result.results = kept

    async def discover(
        self,
        query: str,
        intent: QueryIntent,
        max_results: int | None = None,
    ) -> DiscoveryResponse:
        """Run discovery across all adapters concurrently."""
        start_time = time.perf_counter()
        max_results = max_results or self.settings.max_results_per_source
        active_adapters = self._select_adapters(intent)

        try:
            tasks = [
                asyncio.wait_for(
                    adapter.search(intent, max_results=max_results),
                    timeout=self.settings.adapter_timeout,
                )
                for adapter in active_adapters
            ]

            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            sources: list[DiscoveryResult] = []
            registry = get_registry()
            for adapter, raw in zip(active_adapters, raw_results):
                # `return_exceptions=True` widens the result to T | BaseException;
                # branch on BaseException so the else branch narrows to the real
                # return type for the type checker.
                if isinstance(raw, BaseException):
                    sources.append(
                        DiscoveryResult(
                            source=adapter.name,
                            total_found=0,
                            results=[],
                            error=f"{type(raw).__name__}: {str(raw)[:200]}",
                            latency_ms=0,
                        )
                    )
                    registry.record_adapter_call(
                        adapter=adapter.name, latency_ms=0, error=True
                    )
                else:
                    sources.append(raw)
                    registry.record_adapter_call(
                        adapter=adapter.name,
                        latency_ms=raw.latency_ms,
                        error=raw.error is not None,
                    )

            # Per-adapter post-filters (H-Q + H-O): drop hits whose
            # populated organism / parsed date conflicts with the
            # intent. Runs before dedup so the mirror counts only
            # reflect on-target hits.
            for s in sources:
                if s.results and not s.error:
                    self._apply_species_filter(s, intent)
                    self._apply_year_filter(s, intent)

            # Cross-source dedup runs first so the reranker can see the
            # mirrored counts (and so mirror annotations follow the row
            # whether or not it gets reordered).
            annotate_mirrors(sources)

            # Per-source re-rank: preserves multi-source diversity while
            # nudging canonical hits to the top within each source.
            for s in sources:
                if s.results and not s.error:
                    s.results = self.reranker.rerank(query, intent, s.results)

            total_found = sum(s.total_found for s in sources)
            total_latency_ms = int((time.perf_counter() - start_time) * 1000)

            return DiscoveryResponse(
                query=query,
                intent=intent,
                sources=sources,
                total_found=total_found,
                total_latency_ms=total_latency_ms,
            )
        finally:
            await self.aclose()

    async def discover_stream(
        self,
        query: str,
        intent: QueryIntent,
        max_results: int | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Stream events as adapters complete.

        Yields ``(event_type, payload)`` tuples in roughly this order:

        - ``("source_complete", {...DiscoveryResult.model_dump()...})`` — once
          per adapter, in completion order. The result is per-source-reranked
          before emission so the ordering the client renders is final.
        - ``("mirrors", {accession_key: [{source_db, id, source_url}, ...]})``
          — single event after all sources are in, listing cross-source
          duplicates so the client can paint mirror badges.
        - ``("done", {total_found, total_latency_ms, sources_count})`` — final.

        Caller is responsible for serialising events (e.g. as SSE).
        Resources (HTTP clients) are released when the iterator is fully
        consumed or garbage-collected.
        """
        start_time = time.perf_counter()
        max_results = max_results or self.settings.max_results_per_source
        registry = get_registry()
        completed_sources: list[DiscoveryResult] = []
        active_adapters = self._select_adapters(intent)

        async def _run(adapter):
            try:
                return adapter, await asyncio.wait_for(
                    adapter.search(intent, max_results=max_results),
                    timeout=self.settings.adapter_timeout,
                )
            except BaseException as exc:  # noqa: BLE001
                return adapter, exc

        try:
            tasks = [asyncio.create_task(_run(a)) for a in active_adapters]
            for fut in asyncio.as_completed(tasks):
                adapter, raw = await fut
                if isinstance(raw, BaseException):
                    result = DiscoveryResult(
                        source=adapter.name,
                        total_found=0,
                        results=[],
                        error=f"{type(raw).__name__}: {str(raw)[:200]}",
                        latency_ms=0,
                    )
                    registry.record_adapter_call(
                        adapter=adapter.name, latency_ms=0, error=True
                    )
                else:
                    result = raw
                    registry.record_adapter_call(
                        adapter=adapter.name,
                        latency_ms=raw.latency_ms,
                        error=raw.error is not None,
                    )

                # Apply per-adapter post-filters (H-Q + H-O) BEFORE
                # rerank so the reranker only sees on-target hits.
                if result.results and not result.error:
                    self._apply_species_filter(result, intent)
                    self._apply_year_filter(result, intent)

                # Per-source rerank before emission so the client never sees
                # results reorder after they appear.
                if result.results and not result.error:
                    result.results = self.reranker.rerank(
                        query, intent, result.results
                    )

                completed_sources.append(result)
                yield "source_complete", result.model_dump()

            # All sources are in — compute cross-source mirrors.
            annotate_mirrors(completed_sources)
            mirrors_event: dict[str, Any] = {}
            for src in completed_sources:
                for r in src.results:
                    if r.mirrors:
                        mirrors_event.setdefault(src.source, {})[r.id] = [
                            m.model_dump() for m in r.mirrors
                        ]
            yield "mirrors", {"by_source": mirrors_event}

            total_found = sum(s.total_found for s in completed_sources)
            total_latency_ms = int((time.perf_counter() - start_time) * 1000)
            yield "done", {
                "total_found": total_found,
                "total_latency_ms": total_latency_ms,
                "sources_count": len(completed_sources),
            }
        finally:
            await self.aclose()

    async def health_check(self) -> dict[str, dict[str, Any]]:
        """Check health of all adapters."""
        results: dict[str, dict[str, Any]] = {}
        try:
            for adapter in self.adapters:
                start = time.perf_counter()
                try:
                    available = adapter.is_available
                    latency_ms = int((time.perf_counter() - start) * 1000)
                    results[adapter.name] = {
                        "available": available,
                        "latency_ms": latency_ms,
                    }
                except Exception as exc:
                    results[adapter.name] = {
                        "available": False,
                        "latency_ms": 0,
                        "error": str(exc)[:200],
                    }
            return results
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Close all adapter HTTP clients."""
        await asyncio.gather(
            *(adapter.aclose() for adapter in self.adapters),
            return_exceptions=True,
        )
