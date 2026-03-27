"""
Working Memory — Session-level in-process state

Holds the current conversation context:
- Query history (recent parsed queries)
- Result cache (LRU, avoid re-execution)
- Ontology resolution cache
- Active filters (for multi-turn refinement)

Lifecycle: created per session, destroyed when session ends.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..core.models import (
    FusedRecord,
    ParsedQuery,
    QueryFilters,
    SessionContext,
)


@dataclass
class TurnRecord:
    """A single turn in a conversation."""
    query: ParsedQuery
    result_count: int
    top_results: list[dict] = field(default_factory=list)
    sql_method: str = ""
    exec_time_ms: float = 0
    timestamp: float = field(default_factory=time.time)


class WorkingMemory:
    """
    In-process session memory.

    Provides:
    - Multi-turn context (query chain, active filters)
    - Result caching (LRU, max 30 entries)
    - Ontology cache (avoid re-resolving same terms)
    """

    MAX_HISTORY = 20
    MAX_CACHE = 30

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.created_at = time.time()

        self._turns: list[TurnRecord] = []
        self._result_cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._ontology_cache: dict[str, Any] = {}
        self._active_filters: QueryFilters | None = None

    # ─── turns ───

    def add_turn(
        self,
        query: ParsedQuery,
        results: list[dict | FusedRecord],
        sql_method: str = "",
        exec_time_ms: float = 0,
    ):
        """Record a conversation turn."""
        top = []
        for r in results[:3]:
            if isinstance(r, dict):
                top.append(r)
            elif hasattr(r, "data"):
                top.append(r.data)

        turn = TurnRecord(
            query=query,
            result_count=len(results),
            top_results=top,
            sql_method=sql_method,
            exec_time_ms=exec_time_ms,
        )
        self._turns.append(turn)

        # Trim
        if len(self._turns) > self.MAX_HISTORY:
            self._turns = self._turns[-self.MAX_HISTORY:]

        # Update active filters
        self._active_filters = query.filters

        # Cache results
        cache_key = self._cache_key(query)
        self._result_cache[cache_key] = [r if isinstance(r, dict) else getattr(r, "data", {}) for r in results[:100]]
        if len(self._result_cache) > self.MAX_CACHE:
            self._result_cache.popitem(last=False)

    @property
    def turns(self) -> list[TurnRecord]:
        return self._turns

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    @property
    def active_filters(self) -> QueryFilters | None:
        return self._active_filters

    # ─── cache ───

    def get_cached_result(self, query: ParsedQuery) -> list[dict] | None:
        """Look up cached result for a query."""
        key = self._cache_key(query)
        if key in self._result_cache:
            # Move to end (LRU)
            self._result_cache.move_to_end(key)
            return self._result_cache[key]
        return None

    def cache_ontology(self, key: str, value: Any):
        """Cache an ontology resolution result."""
        self._ontology_cache[key] = value

    def get_ontology_cache(self, key: str) -> Any:
        return self._ontology_cache.get(key)

    # ─── context ───

    def get_context(self) -> SessionContext:
        """Build SessionContext for downstream modules."""
        return SessionContext(
            session_id=self.session_id,
            turns=self.turn_count,
            recent_queries=[t.query for t in self._turns[-5:]],
            active_filters=self._active_filters,
        )

    def get_conversation_summary(self) -> str:
        """One-line summary for system prompt injection."""
        if not self._turns:
            return "新对话，无历史上下文。"

        lines = []
        for i, t in enumerate(self._turns[-3:], 1):
            q = t.query
            filters_str = []
            if q.filters.tissues:
                filters_str.append(f"tissue={q.filters.tissues}")
            if q.filters.diseases:
                filters_str.append(f"disease={q.filters.diseases}")
            if q.filters.cell_types:
                filters_str.append(f"cell_type={q.filters.cell_types}")
            filt = ", ".join(filters_str) if filters_str else "无过滤"
            lines.append(f"Turn{i}: {q.intent.name} [{filt}] → {t.result_count}条")

        return "; ".join(lines)

    # ─── internal ───

    @staticmethod
    def _cache_key(query: ParsedQuery) -> str:
        """Deterministic cache key from query."""
        f = query.filters
        parts = [
            query.intent.name,
            query.target_level,
            str(sorted(f.tissues)),
            str(sorted(f.diseases)),
            str(sorted(f.cell_types)),
            str(sorted(f.assays)),
            str(sorted(f.source_databases)),
            f.sex or "",
            str(f.min_cells),
            str(query.limit),
        ]
        return "|".join(parts)
