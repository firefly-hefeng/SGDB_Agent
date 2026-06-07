"""Discovery sub-agent (cross-database NL search).

In-process port of the upstream ``api-routing-agent`` v0.5.2 at
``/mnt/d/api_routing_agent``. Exposes ``IntentParser``, ``DiscoveryRouter``,
and ``Synthesizer`` plus the Pydantic models used by the route layer.
"""

from __future__ import annotations

from .config import DiscoverySettings, get_settings
from .intent_parser import IntentParser
from .models import (
    DatasetResult,
    DiscoveryOptions,
    DiscoveryRequest,
    DiscoveryResponse,
    DiscoveryResult,
    HealthResponse,
    HealthStatus,
    MirrorRef,
    QueryIntent,
)
from .router import DiscoveryRouter
from .synthesizer import Synthesizer

__all__ = [
    "DatasetResult",
    "DiscoveryOptions",
    "DiscoveryRequest",
    "DiscoveryResponse",
    "DiscoveryResult",
    "DiscoveryRouter",
    "DiscoverySettings",
    "HealthResponse",
    "HealthStatus",
    "IntentParser",
    "MirrorRef",
    "QueryIntent",
    "Synthesizer",
    "get_settings",
]
