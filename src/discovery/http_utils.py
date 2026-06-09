"""Lightweight HTTP retry helper for adapters."""

from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


async def request_with_retry(
    func: Callable[[], Awaitable[httpx.Response]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
) -> httpx.Response:
    """Execute an httpx request callable with exponential backoff + jitter.

    Retries on retryable status codes and on transport-level exceptions. Raises
    the final exception or returns the last response (after raise_for_status
    if status was retryable but exhausted).
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await func()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                return resp
            if attempt == max_attempts:
                resp.raise_for_status()
                return resp
            last_exc = httpx.HTTPStatusError(
                f"retryable status {resp.status_code}", request=resp.request, response=resp
            )

        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        delay = delay * (0.5 + random.random())  # full jitter on top of half
        await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("request_with_retry exhausted without result")
