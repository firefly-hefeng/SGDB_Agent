"""Cross-database discovery routes.

Wraps the in-process ``src.discovery`` sub-agent (a vendored copy of
``api-routing-agent`` v0.5.2) and exposes its endpoints under the
``/scdbAPI/discover`` namespace so that the unified frontend can consume
them same-origin without an iframe or a second uvicorn process.

Endpoints
---------
- ``GET  /scdbAPI/discover/sources``  — list the configured source adapters
- ``GET  /scdbAPI/discover/health``   — per-adapter health probe
- ``POST /scdbAPI/discover/search``   — synchronous, cached discovery
- ``POST /scdbAPI/discover/stream``   — SSE: ``intent → source_complete*N → mirrors → synth? → done``
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.discovery import (
    DiscoveryRequest,
    DiscoveryResponse,
    DiscoveryResult,
    DiscoveryRouter,
    IntentParser,
    Synthesizer,
    get_settings as get_discovery_settings,
)
from src.discovery.cache import (
    get_discover_cache,
    make_discover_cache_key,
    record_cache_event,
)

router = APIRouter(prefix="/scdbAPI/discover", tags=["discover"])
log = logging.getLogger("api.discover")


# ── Lazy singletons. Created on first request so import is cheap. ──

_intent_parser: IntentParser | None = None
_synthesizer: Synthesizer | None = None
_concurrency: asyncio.Semaphore | None = None


def _get_parser() -> IntentParser:
    global _intent_parser
    if _intent_parser is None:
        _intent_parser = IntentParser()
    return _intent_parser


def _get_synthesizer() -> Synthesizer:
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = Synthesizer()
    return _synthesizer


def _get_concurrency() -> asyncio.Semaphore:
    global _concurrency
    if _concurrency is None:
        _concurrency = asyncio.Semaphore(get_discovery_settings().concurrency_limit)
    return _concurrency


# ── Routes ──


@router.get(
    "/sources",
    summary="List discovery source adapters",
    description=(
        "Returns the 6 cross-database adapters available to the discovery "
        "engine, each with a human-readable name, description, and host. "
        "The `default_selection` field is the subset the UI ticks on first "
        "load (SRA is off by default because it's slow / noisy)."
    ),
    response_description="Adapter catalogue with default selection.",
)
async def list_sources() -> dict:
    """List configured discovery source adapters."""
    from src.discovery.adapters import ADAPTERS

    # Display name + short blurb keep the frontend free of duplicate metadata.
    blurbs: dict[str, dict[str, str]] = {
        "geo": {
            "name": "GEO",
            "full_name": "Gene Expression Omnibus",
            "description": "NCBI's central repository of high-throughput gene expression studies.",
            "host": "ncbi.nlm.nih.gov",
        },
        "sra": {
            "name": "SRA",
            "full_name": "Sequence Read Archive",
            "description": "NCBI's archive of raw sequencing reads.",
            "host": "ncbi.nlm.nih.gov",
        },
        "ebi": {
            "name": "EBI",
            "full_name": "EBI BioStudies / ArrayExpress",
            "description": "EMBL-EBI's curated functional-genomics repository.",
            "host": "ebi.ac.uk",
        },
        "scea": {
            "name": "SCEA",
            "full_name": "Single-Cell Expression Atlas",
            "description": "EBI's ontology-aligned single-cell catalog.",
            "host": "ebi.ac.uk",
        },
        "cellxgene": {
            "name": "CellxGene",
            "full_name": "CZI CellxGene Discover",
            "description": "Chan Zuckerberg Initiative's curated single-cell census.",
            "host": "cellxgene.cziscience.com",
        },
        "hca": {
            "name": "HCA",
            "full_name": "Human Cell Atlas",
            "description": "Open data portal for the Human Cell Atlas.",
            "host": "data.humancellatlas.org",
        },
    }

    return {
        "sources": [
            {
                "id": key,
                **blurbs.get(
                    key,
                    {
                        "name": key.upper(),
                        "full_name": key.upper(),
                        "description": "",
                        "host": "",
                    },
                ),
            }
            for key in ADAPTERS.keys()
        ],
        "default_selection": ["geo", "ebi", "scea", "cellxgene", "hca"],
    }


@router.get(
    "/health",
    summary="Discovery health check",
    description=(
        "Cheap per-adapter availability probe — does not actually call out to "
        "the remote APIs, just verifies adapter classes load and the registry "
        "is intact. Returns `status: ok` if any adapter is reachable, "
        "`degraded` otherwise."
    ),
)
async def discover_health() -> dict:
    """Per-adapter availability probe (cheap) + resolved LLM/rerank state.

    The ``llm`` block reports whether the agent is running with its full
    capability set (LLM intent parse + synthesis + rerank) or degraded to
    rule-only — so a silent LLM-off regression (the Phase-39 root cause) is
    observable, not invisible.
    """
    drouter = DiscoveryRouter()
    adapter_health = await drouter.health_check()
    available = sum(1 for v in adapter_health.values() if v.get("available"))
    settings = get_discovery_settings()
    return {
        "status": "ok" if available else "degraded",
        "adapters_available": available,
        "adapters_total": len(adapter_health),
        "adapters": adapter_health,
        "llm": settings.effective_llm_summary(),
    }


@router.post(
    "/search",
    response_model=DiscoveryResponse,
    summary="Cross-database discovery (synchronous, cached)",
    description=(
        "Fan a natural-language query out to all enabled source databases "
        "concurrently, dedupe across sources via accession-mirror detection, "
        "and return a single `DiscoveryResponse`. The agent runs LLM intent "
        "parsing first, then the per-adapter searches, then optionally an "
        "LLM synthesis pass.\n\n"
        "Responses are cached by (query, sources, max_results, synthesize) "
        "for `DISCOVERY_DISCOVER_CACHE_TTL_SECONDS` (default 600 s). The "
        "`X-Cache: HIT|MISS` response header reports the cache outcome.\n\n"
        "For lower perceived latency on slow queries, use `/stream` (SSE) "
        "and render per-source results as they complete."
    ),
    response_description="Aggregated DiscoveryResponse with per-source breakdown, mirrors, and optional LLM synth.",
)
async def discover_search(request: DiscoveryRequest, http_request: Request) -> DiscoveryResponse:
    """Synchronous, cached cross-database discovery.

    Identical ``(query, sources, max_results, synthesize)`` tuples within
    the configured TTL are served from an in-process cache.
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="`query` must be non-empty")

    cache = get_discover_cache()
    cache_key = make_discover_cache_key(
        request.query,
        request.options.sources,
        request.options.max_results_per_source,
        request.options.synthesize,
    )
    cached = cache.get(cache_key)
    if cached is not None:
        record_cache_event(hit=True)
        try:
            http_request.state.cache_status = "HIT"
        except Exception:
            pass
        return cached
    record_cache_event(hit=False)

    parser = _get_parser()
    # parser.parse() and synthesizer.synthesize() do BLOCKING sync LLM calls;
    # off-load to a thread so the FastAPI event loop is not frozen for the full
    # LLM latency of every request (would serialise all concurrent discovery).
    intent = await asyncio.to_thread(parser.parse, request.query)

    drouter = DiscoveryRouter(enabled_sources=request.options.sources)
    async with _get_concurrency():
        response = await drouter.discover(
            query=request.query,
            intent=intent,
            max_results=request.options.max_results_per_source,
        )

    if request.options.synthesize:
        synthesizer = _get_synthesizer()
        response.synthesized_answer = await asyncio.to_thread(
            synthesizer.synthesize, response
        )

    cache.set(cache_key, response)
    try:
        http_request.state.cache_status = "MISS"
    except Exception:
        pass
    return response


def _sse(event: str, data: dict[str, Any]) -> str:
    """Encode a single SSE event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/stream",
    summary="Cross-database discovery (SSE stream)",
    description=(
        "Same intent + adapter dispatch as `/search`, but emits results as "
        "Server-Sent Events so the UI can render each source's results "
        "the moment that adapter responds.\n\n"
        "Event sequence:\n\n"
        "- `intent` — parsed `QueryIntent` (one, first)\n"
        "- `source_complete` — one per adapter, in completion order\n"
        "- `mirrors` — cross-source duplicates, after all adapters return\n"
        "- `synth` — optional LLM markdown synthesis when "
        "`options.synthesize=true`\n"
        "- `done` — final totals\n"
        "- `error` — emitted on failure; the connection then closes\n\n"
        "**Caching:** SSE responses are *not* cached. Use `/search` for "
        "cacheable workflows."
    ),
)
async def discover_stream(request: DiscoveryRequest):
    """SSE endpoint: stream adapter results as they complete."""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="`query` must be non-empty")

    parser = _get_parser()
    intent = await asyncio.to_thread(parser.parse, request.query)  # blocking LLM → thread

    drouter = DiscoveryRouter(enabled_sources=request.options.sources)
    synthesizer = _get_synthesizer() if request.options.synthesize else None

    async def event_stream():
        yield "retry: 5000\n\n"
        yield _sse("intent", intent.model_dump())

        accumulated_sources: list[dict] = []
        done_payload: dict | None = None
        try:
            async with _get_concurrency():
                async for event_type, payload in drouter.discover_stream(
                    query=request.query,
                    intent=intent,
                    max_results=request.options.max_results_per_source,
                ):
                    if event_type == "source_complete":
                        accumulated_sources.append(payload)
                        yield _sse(event_type, payload)
                    elif event_type == "mirrors":
                        yield _sse(event_type, payload)
                    elif event_type == "done":
                        done_payload = payload  # hold so synth lands first
                    else:
                        yield _sse(event_type, payload)
        except Exception as exc:
            log.exception("discover_stream_error")
            yield _sse(
                "error",
                {"type": type(exc).__name__, "message": str(exc)[:200]},
            )
            return

        if synthesizer is not None:
            try:
                response = DiscoveryResponse(
                    query=request.query,
                    intent=intent,
                    sources=[DiscoveryResult(**s) for s in accumulated_sources],
                    total_found=sum(s["total_found"] for s in accumulated_sources),
                    total_latency_ms=0,
                )
                synth = await asyncio.to_thread(synthesizer.synthesize, response)
                yield _sse("synth", {"markdown": synth})
            except Exception as exc:
                log.warning("stream_synth_failed: %s", exc)

        if done_payload is not None:
            yield _sse("done", done_payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx proxy buffering
        },
    )
