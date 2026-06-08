"""Process-local TTL-LRU cache for discovery responses.

Keyed on (query, sorted-sources, max_results, synthesize). Stores the rendered
``DiscoveryResponse`` so we can return identical bytes without re-running
adapters or LLM calls. Eviction order is least-recently-used; entries past the
TTL are treated as misses.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, TypeVar

from src.discovery.metrics import get_registry

V = TypeVar("V")


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V
    inserted_at: float


class TTLCache(Generic[V]):
    """Tiny TTL + LRU cache. Not coroutine-aware (operations are sync and fast)."""

    def __init__(self, *, max_size: int = 256, ttl_seconds: float = 600.0) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, _Entry[V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> V | None:
        if self.ttl_seconds <= 0 or self.max_size <= 0:
            return None
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if now - entry.inserted_at > self.ttl_seconds:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)  # mark recently used
            return entry.value

    def set(self, key: str, value: V) -> None:
        if self.ttl_seconds <= 0 or self.max_size <= 0:
            return
        now = time.time()
        with self._lock:
            self._data[key] = _Entry(value=value, inserted_at=now)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def make_discover_cache_key(
    query: str, sources: list[str], max_results: int, synthesize: bool
) -> str:
    src = ",".join(sorted(sources))
    return f"{query}|{src}|{max_results}|{int(synthesize)}"


_DISCOVER_CACHE: TTLCache | None = None


def get_discover_cache() -> TTLCache:
    """Lazy global discover cache, configured from settings on first use."""
    global _DISCOVER_CACHE
    if _DISCOVER_CACHE is None:
        from .config import get_settings

        s = get_settings()
        _DISCOVER_CACHE = TTLCache(
            max_size=s.discover_cache_max_size,
            ttl_seconds=s.discover_cache_ttl_seconds,
        )
    return _DISCOVER_CACHE


def reset_discover_cache() -> None:
    """Test helper — drop the singleton so settings re-apply."""
    global _DISCOVER_CACHE
    _DISCOVER_CACHE = None


def record_cache_event(hit: bool) -> None:
    get_registry().record_cache("hit" if hit else "miss")
