"""Phase 30.A — parser-result cache.

The reasoning-parser CoT round-trip to Kimi/Claude takes 30–60 s on cold
calls. Many user queries repeat verbatim (theme tiles, examples,
"COVID-19 lung" typed thrice). A simple in-memory LRU cache on the
*normalised* query text returns the cached `ParsedQuery` in micro-
seconds.

Design:

  - Wraps any `IQueryParser` — no changes to coordinator code.
  - Cache key: lowercase + trimmed query text. Session context is
    intentionally NOT part of the key — parsing is content-driven, and
    biologists hitting the same query in two sessions deserve the same
    answer.
  - TTL: 1 hour (in the time horizon a DB rebuild + restart would
    happen anyway).
  - LRU bound: 256 entries (text queries are tiny).
  - copy.deepcopy on return — callers mutate `ParsedQuery.limit` and
    we don't want one caller's mutation to leak into the next.

A small `stats()` method returns hit/miss/eviction counts for telemetry
and tests.
"""

from __future__ import annotations

import copy
import logging
import time
from collections import OrderedDict

from ..core.interfaces import IQueryParser
from ..core.models import ParsedQuery, SessionContext

logger = logging.getLogger(__name__)


class CachingParser:
    """LRU cache wrapper around any IQueryParser implementation."""

    def __init__(
        self,
        inner: IQueryParser,
        *,
        max_entries: int = 256,
        ttl_seconds: int = 3600,
    ):
        self._inner = inner
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, ParsedQuery]] = OrderedDict()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "stale_drops": 0}

    @staticmethod
    def _key(query: str) -> str:
        return (query or "").strip().lower()

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def clear(self) -> None:
        self._store.clear()

    async def parse(
        self,
        query: str,
        context: SessionContext | None = None,
    ) -> ParsedQuery:
        key = self._key(query)
        if not key:
            # Empty / whitespace-only — don't cache; let inner reject.
            return await self._inner.parse(query, context)

        entry = self._store.get(key)
        if entry is not None:
            ts, cached = entry
            if (time.time() - ts) <= self._ttl:
                # Move to end of OrderedDict (most-recently-used)
                self._store.move_to_end(key)
                self._stats["hits"] += 1
                logger.debug("CachingParser hit for %r", key[:60])
                # Deep-copy: callers may set parsed.limit etc. and we
                # don't want the cached object mutated under their feet.
                return copy.deepcopy(cached)
            # Stale — drop and treat as miss.
            del self._store[key]
            self._stats["stale_drops"] += 1

        self._stats["misses"] += 1
        result = await self._inner.parse(query, context)
        # Cache the result — also deep-copy so a downstream mutation
        # of the returned object doesn't poison the cache.
        try:
            self._store[key] = (time.time(), copy.deepcopy(result))
        except Exception as e:
            # Some ParsedQuery shapes (with non-copyable trace) may
            # fail deepcopy; degrade silently.
            logger.warning("CachingParser failed to cache %r: %s", key[:60], e)

        # Evict oldest
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)
            self._stats["evictions"] += 1

        return result

    # The CachingParser exposes the inner parser's other public
    # surface (e.g. ReasoningParser.parse_with_trace) via getattr so a
    # caller can still get the trace if they need it.
    def __getattr__(self, name: str):
        return getattr(self._inner, name)
