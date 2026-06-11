"""In-memory Prometheus-style metrics collector.

Deliberately dependency-free: we render the Prometheus text exposition format
ourselves so we don't pull in ``prometheus_client``. Only counters + simple
bucketed histograms are supported. The collector is process-local — fine for a
single uvicorn worker; for multi-worker deployments swap in a real client.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import defaultdict
from typing import Iterable

log = logging.getLogger("api_routing.metrics")

# Latency histogram buckets in milliseconds.
_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
    float("inf"),
)


def _format_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_format_label_value(v)}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


class _Histogram:
    __slots__ = ("buckets", "counts", "sum", "count")

    def __init__(self, buckets: Iterable[float] = _DEFAULT_BUCKETS_MS) -> None:
        self.buckets = tuple(sorted(buckets))
        self.counts = [0] * len(self.buckets)
        self.sum = 0.0
        self.count = 0

    def observe(self, value: float) -> None:
        self.count += 1
        self.sum += value
        for i, b in enumerate(self.buckets):
            if value <= b:
                self.counts[i] += 1


class MetricsRegistry:
    """Process-local metric registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
            defaultdict(float)
        )
        self._histograms: dict[
            tuple[str, tuple[tuple[str, str], ...]], _Histogram
        ] = {}

    # ---- Mutators ----
    def inc_counter(
        self, name: str, labels: dict[str, str] | None = None, amount: float = 1.0
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] += amount

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                hist = _Histogram()
                self._histograms[key] = hist
            hist.observe(value)

    # ---- Convenience helpers wired by the rest of the app ----
    def record_request(
        self, latency_ms: float, status: int, path: str = ""
    ) -> None:
        labels = {"status": str(status)}
        if path:
            labels["path"] = path
        self.inc_counter("requests_total", labels)
        self.observe_histogram("request_latency_ms", latency_ms, labels)

    def record_adapter_call(
        self, adapter: str, latency_ms: float, error: bool
    ) -> None:
        labels = {"adapter": adapter, "status": "error" if error else "ok"}
        self.inc_counter("adapter_calls_total", labels)
        self.observe_histogram(
            "adapter_latency_ms", latency_ms, {"adapter": adapter}
        )

    def record_llm_call(
        self,
        provider: str,
        operation: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        est_cost_usd: float,
        error: bool,
    ) -> None:
        labels = {
            "provider": provider,
            "operation": operation,
            "status": "error" if error else "ok",
        }
        self.inc_counter("llm_calls_total", labels)
        self.observe_histogram(
            "llm_latency_ms", latency_ms, {"operation": operation}
        )
        if prompt_tokens:
            self.inc_counter(
                "llm_tokens_total",
                {"provider": provider, "operation": operation, "type": "input"},
                amount=prompt_tokens,
            )
        if completion_tokens:
            self.inc_counter(
                "llm_tokens_total",
                {"provider": provider, "operation": operation, "type": "output"},
                amount=completion_tokens,
            )
        if est_cost_usd:
            self.inc_counter(
                "llm_cost_usd_total",
                {"provider": provider, "operation": operation},
                amount=est_cost_usd,
            )

    def record_cache(self, op: str) -> None:
        """op is 'hit' or 'miss'."""
        self.inc_counter("cache_events_total", {"op": op})

    # ---- Render ----
    def render_prometheus(self) -> str:
        with self._lock:
            counters = sorted(self._counters.items())
            hists = sorted(self._histograms.items())

        lines: list[str] = []
        # Counters
        seen_names: set[str] = set()
        for (name, label_tuple), value in counters:
            if name not in seen_names:
                lines.append(f"# TYPE {name} counter")
                seen_names.add(name)
            lines.append(
                f"{name}{_format_labels(dict(label_tuple))} {_render_number(value)}"
            )

        # Histograms
        for (name, label_tuple), hist in hists:
            base_labels = dict(label_tuple)
            lines.append(f"# TYPE {name} histogram")
            for bucket, count in zip(hist.buckets, hist.counts):
                bucket_label = (
                    "+Inf" if bucket == float("inf") else _render_number(bucket)
                )
                bucket_labels = {**base_labels, "le": bucket_label}
                lines.append(
                    f"{name}_bucket{_format_labels(bucket_labels)} {count}"
                )
            lines.append(
                f"{name}_sum{_format_labels(base_labels)} {_render_number(hist.sum)}"
            )
            lines.append(
                f"{name}_count{_format_labels(base_labels)} {hist.count}"
            )

        # Trailing newline per Prometheus convention.
        return "\n".join(lines) + "\n"

    # ---- Test/admin utility ----
    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


def _render_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


_REGISTRY: MetricsRegistry | None = None
_MULTIPROC_WARNED = False


def _warn_multiproc_once() -> None:
    """Warn the operator if metrics will silently miss data in multi-worker mode.

    The default registry is per-process; running uvicorn / gunicorn with
    ``--workers > 1`` means each worker has its own counter set and the
    ``/metrics`` endpoint only ever returns the worker that handled the
    scrape. Production deployments should swap in ``prometheus_client``
    multiprocess mode (see ``docs/engineering/METRICS_DEPLOYMENT.md``).
    """
    global _MULTIPROC_WARNED
    if _MULTIPROC_WARNED:
        return
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        log.warning(
            "metrics_multiproc_unsupported",
            extra={
                "event": "metrics",
                "cache": "warn",
            },
        )
    _MULTIPROC_WARNED = True


def get_registry() -> MetricsRegistry:
    """Return the process-wide metrics registry (lazy singleton)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MetricsRegistry()
        _warn_multiproc_once()
    return _REGISTRY
