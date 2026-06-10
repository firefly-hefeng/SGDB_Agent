"""Structured tracing for LLM calls.

Wraps Anthropic / OpenAI calls in a context manager that records latency, token
usage, and an estimated USD cost, then emits a single JSON log event named
``llm_call``. Cost estimates use a small static pricing table — keep it updated
when providers change rates.
"""

from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from src.discovery.metrics import get_registry

log = logging.getLogger("api_routing.llm")

# Optional per-request ledger. The benchmark cost-runner sets this to a list
# at the start of each query so it can attribute LLM stats to that query
# without parsing log lines or polling the global counters.
_LEDGER: contextvars.ContextVar[list["LLMCallStats"] | None] = contextvars.ContextVar(
    "llm_call_ledger", default=None
)

# Per-million-token USD pricing (input, output). Update when providers change.
# Sources: Anthropic + OpenAI public pricing pages (verified 2026-05).
_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-3-5-haiku-20241022": (0.80, 4.00),
        "claude-3-5-sonnet-20241022": (3.00, 15.00),
        "claude-haiku-4-5-20251001": (1.00, 5.00),
        "claude-sonnet-4-6": (3.00, 15.00),
        "claude-opus-4-7": (15.00, 75.00),
    },
    "openai": {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        # Moonshot Kimi models exposed via OpenAI-compatible endpoint.
        # Pricing per Moonshot 2025 public pricing converted at 7.2 RMB/USD.
        "moonshot-v1-8k": (1.67, 1.67),    # 12 RMB / M tokens both directions
        "moonshot-v1-32k": (3.33, 3.33),   # 24 RMB / M
        "moonshot-v1-128k": (8.33, 8.33),  # 60 RMB / M
    },
}

_DEFAULT_PRICE: tuple[float, float] = (0.0, 0.0)


@dataclass
class LLMCallStats:
    """Mutable stats container yielded by ``trace_llm_call``."""

    provider: str
    model: str
    operation: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    est_cost_usd: float = 0.0
    error: str | None = None


def estimate_cost_usd(
    provider: str, model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Estimate USD cost from the static pricing table. Returns 0.0 if unknown."""
    in_price, out_price = _PRICING.get(provider, {}).get(model, _DEFAULT_PRICE)
    return (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000


@contextmanager
def trace_llm_call(
    provider: str, model: str, operation: str
) -> Iterator[LLMCallStats]:
    """Time an LLM call, capture usage written by the caller, log a JSON event.

    The caller is expected to populate ``stats.prompt_tokens`` and
    ``stats.completion_tokens`` after the SDK call returns. Latency and cost
    are always recorded — even on exception (with ``error`` set).
    """
    stats = LLMCallStats(provider=provider, model=model, operation=operation)
    start = time.perf_counter()
    try:
        yield stats
    except Exception as exc:
        stats.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        raise
    finally:
        stats.latency_ms = int((time.perf_counter() - start) * 1000)
        stats.total_tokens = stats.prompt_tokens + stats.completion_tokens
        stats.est_cost_usd = round(
            estimate_cost_usd(
                provider, model, stats.prompt_tokens, stats.completion_tokens
            ),
            6,
        )
        log.info(
            "llm_call",
            extra={
                "event": "llm_call",
                "provider": provider,
                "model": model,
                "operation": operation,
                "latency_ms": stats.latency_ms,
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
                "total_tokens": stats.total_tokens,
                "est_cost_usd": stats.est_cost_usd,
                "llm_error": stats.error,
            },
        )
        get_registry().record_llm_call(
            provider=provider,
            operation=operation,
            latency_ms=stats.latency_ms,
            prompt_tokens=stats.prompt_tokens,
            completion_tokens=stats.completion_tokens,
            est_cost_usd=stats.est_cost_usd,
            error=stats.error is not None,
        )
        # Attribute to the current query ledger if one is active. The benchmark
        # cost runner uses this to report per-query token usage without parsing
        # log lines.
        ledger = _LEDGER.get()
        if ledger is not None:
            ledger.append(stats)


@contextmanager
def llm_ledger() -> Iterator[list[LLMCallStats]]:
    """Context manager: collect every ``LLMCallStats`` emitted in this scope.

    Usage::

        with llm_ledger() as calls:
            ...invoke agent on one query...
        # `calls` now holds every LLMCallStats produced during the block,
        # in the order their `finally` clauses ran.

    Re-entry is supported: nested ledgers each get their own list — only the
    innermost ledger receives stats. Use this from one request handler at a
    time.
    """
    new_list: list[LLMCallStats] = []
    token = _LEDGER.set(new_list)
    try:
        yield new_list
    finally:
        _LEDGER.reset(token)
