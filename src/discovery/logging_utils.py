"""Logging configuration: structured-ish JSON logs with request_id correlation."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(value: str) -> contextvars.Token:
    return _request_id_var.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_var.reset(token)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id_var.get(),
        }
        for key in (
            "adapter",
            "latency_ms",
            "status",
            "event",
            # LLM tracing fields
            "provider",
            "model",
            "operation",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "est_cost_usd",
            "llm_error",
            # Cache / metrics
            "cache",
            "source",
        ):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger to emit JSON lines to stderr (idempotent)."""
    root = logging.getLogger()
    if getattr(root, "_api_routing_configured", False):
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._api_routing_configured = True  # type: ignore[attr-defined]
