"""
SCeQTL-Agent V2 FastAPI Application

Production features:
- Rate limiting middleware
- Structured logging with request IDs
- Error standardization (RFC 7807 problem+json)
- Environment-driven CORS configuration
- Request timeout protection
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.dal.database import DatabaseAbstractionLayer
from src.agent.coordinator import CoordinatorAgent
from src.core.exceptions import SCeQTLError

# ── Structured logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: initialize DAL + CoordinatorAgent on startup."""
    from api.deps import set_dal, set_coordinator

    settings = get_settings()
    logger.info("Starting SCeQTL-Agent V2...")

    dal = None
    coordinator = None

    if settings.database.db_path:
        dal = DatabaseAbstractionLayer(settings.database.db_path)
        schema = dal.schema_inspector.analyze()
        logger.info(
            "Database connected: %d tables, %d views",
            schema["total_tables"],
            schema["total_views"],
        )

        # Ontology cache
        onto_path = None
        project_root = Path(__file__).parent.parent
        default_onto = project_root / "data" / "ontologies" / "ontology_cache.db"
        if default_onto.exists():
            onto_path = str(default_onto)
            logger.info("Ontology cache: %s", onto_path)

        # Memory directory
        mem_path = str(project_root / "data" / "memory")

        # Schema Knowledge path
        sk_path = project_root / settings.knowledge.schema_path
        sk_path_str = str(sk_path) if sk_path.exists() else None
        if sk_path_str:
            logger.info("Schema Knowledge: %s", sk_path_str)
        else:
            logger.info("Schema Knowledge: not found at %s", sk_path)

        # Build LLM client chain: Kimi (primary) → Claude (fallback) → rule engine
        from src.infra.llm_client import OpenAILLMClient, ClaudeLLMClient
        from src.infra.llm_router import LLMRouter, CircuitBreaker

        llm = None
        if settings.llm.kimi_api_key:
            kimi_client = OpenAILLMClient(
                api_key=settings.llm.kimi_api_key,
                model=settings.llm.primary_model,
                base_url=settings.llm.kimi_base_url,
            )
            fallback_client = None
            if settings.llm.anthropic_api_key:
                fallback_client = ClaudeLLMClient(
                    api_key=settings.llm.anthropic_api_key,
                    model=settings.llm.fallback_model,
                )
            elif settings.llm.openai_api_key:
                fallback_client = OpenAILLMClient(
                    api_key=settings.llm.openai_api_key,
                    model="gpt-4o-mini",
                )
            llm = LLMRouter(
                primary=kimi_client,
                fallback=fallback_client,
                circuit_breaker=CircuitBreaker(
                    failure_threshold=settings.agent.circuit_breaker_threshold,
                    recovery_timeout=settings.agent.circuit_breaker_recovery_seconds,
                ),
                request_timeout=settings.llm.request_timeout,
            )
            logger.info("LLM: Kimi (%s) → %s fallback",
                        settings.llm.primary_model,
                        fallback_client.model_id if fallback_client else "none")
        elif settings.llm.anthropic_api_key:
            llm = ClaudeLLMClient(
                api_key=settings.llm.anthropic_api_key,
                model=settings.llm.fallback_model,
            )
            logger.info("LLM: Claude (%s)", settings.llm.fallback_model)
        elif settings.llm.openai_api_key:
            llm = OpenAILLMClient(
                api_key=settings.llm.openai_api_key,
                model="gpt-4o-mini",
            )
            logger.info("LLM: OpenAI (gpt-4o-mini)")
        else:
            logger.info("LLM: none configured, rule engine only")

        coordinator = CoordinatorAgent.create(
            dal=dal,
            llm=llm,
            ontology_cache_path=onto_path,
            memory_db_path=mem_path,
            schema_knowledge_path=sk_path_str,
        )
        logger.info(
            "CoordinatorAgent initialized (ontology=%s, memory=%s)",
            coordinator.ontology is not None,
            coordinator.episodic is not None,
        )

    set_dal(dal)
    set_coordinator(coordinator)

    # Pre-warm dashboard cache so the first user request is instant
    if dal:
        try:
            from api.routes.stats import prewarm_dashboard_cache
            prewarm_dashboard_cache(dal)
        except Exception as e:
            logger.warning("Dashboard cache pre-warm failed: %s", e)

    yield

    logger.info("Shutting down SCeQTL-Agent V2...")
    if dal:
        dal.close()
    set_dal(None)
    set_coordinator(None)


app = FastAPI(
    title="SCeQTL-Agent V2",
    description="Ontology-aware cross-database metadata retrieval agent for human scRNA-seq data",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Middleware: Request ID + Logging + Timing ──

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Add request ID, log request/response, track timing."""
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = time.perf_counter()

    response: Response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-MS"] = f"{elapsed_ms:.0f}"

    # Log non-static requests
    path = request.url.path
    if not path.startswith("/assets") and path != "/favicon.ico":
        logger.info(
            "[%s] %s %s → %d (%.0fms)",
            request_id, request.method, path, response.status_code, elapsed_ms,
        )

    return response


# ── Middleware: Simple rate limiter (in-memory, per IP) ──

_rate_store: dict[str, list[float]] = {}
RATE_LIMIT = int(os.environ.get("SCEQTL_RATE_LIMIT", "60"))  # requests per minute
RATE_WINDOW = 60.0  # seconds


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple sliding-window rate limiter per client IP."""
    # Skip rate limiting for static assets and health
    path = request.url.path
    if path.startswith("/assets") or path == "/scdbAPI/health" or path == "/":
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries
    if client_ip in _rate_store:
        _rate_store[client_ip] = [t for t in _rate_store[client_ip] if now - t < RATE_WINDOW]
    else:
        _rate_store[client_ip] = []

    if len(_rate_store[client_ip]) >= RATE_LIMIT:
        return JSONResponse(
            status_code=429,
            content={
                "type": "rate_limit_exceeded",
                "title": "Too Many Requests",
                "detail": f"Rate limit: {RATE_LIMIT} requests per minute",
                "status": 429,
            },
        )

    _rate_store[client_ip].append(now)
    return await call_next(request)


# ── Global exception handler (RFC 7807 problem+json) ──

@app.exception_handler(SCeQTLError)
async def sceqtl_error_handler(request: Request, exc: SCeQTLError):
    """Convert domain exceptions to RFC 7807 problem+json."""
    return JSONResponse(
        status_code=500,
        content={
            "type": f"sceqtl_error/{exc.stage or 'unknown'}",
            "title": type(exc).__name__,
            "detail": str(exc),
            "status": 500,
            "stage": exc.stage,
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    """Catch-all error handler."""
    logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "type": "internal_error",
            "title": "Internal Server Error",
            "detail": str(exc) if os.environ.get("SCEQTL_DEBUG") else "An unexpected error occurred",
            "status": 500,
        },
    )


# ── CORS (environment-driven) ──

cors_origins = os.environ.get("SCEQTL_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routers ──
from api.routes.query import router as query_router
from api.routes.ontology import router as ontology_router
from api.routes.entity import router as entity_router
from api.routes.stats import router as stats_router
from api.routes.session import router as session_router
from api.routes.export import router as export_router
from api.routes.explore import router as explore_router
from api.routes.dataset import router as dataset_router
from api.routes.downloads import router as downloads_router
from api.routes.advanced_search import router as advanced_search_router
from api.websocket import router as ws_router

app.include_router(query_router)
app.include_router(ontology_router)
app.include_router(entity_router)
app.include_router(stats_router)
app.include_router(session_router)
app.include_router(export_router)
app.include_router(explore_router)
app.include_router(dataset_router)
app.include_router(downloads_router)
app.include_router(advanced_search_router)
app.include_router(ws_router)


# ── Basic routes ──

@app.get("/scdbAPI/info")
async def api_info():
    return {"service": "SCeQTL-Agent V2", "status": "running", "version": "2.0.0"}


@app.get("/scdbAPI/health")
async def health():
    """Health check with component status."""
    from api.deps import get_dal, get_coordinator

    status = {"status": "healthy", "components": {}}
    dal = get_dal()
    coordinator = get_coordinator()

    if dal:
        try:
            # Use precomputed count for speed (<5ms vs ~1.6s for live COUNT)
            result = dal.execute(
                "SELECT value as cnt FROM stats_overall WHERE metric = 'total_samples'"
            )
            if result.rows:
                sample_count = result.rows[0]["cnt"]
            else:
                # Fallback: verify connectivity without full COUNT
                result = dal.execute("SELECT COUNT(*) as cnt FROM unified_samples LIMIT 1")
                sample_count = result.rows[0]["cnt"]
            status["components"]["database"] = {
                "status": "connected",
                "sample_count": sample_count,
            }
        except Exception as e:
            status["components"]["database"] = {"status": "error", "error": str(e)}
            status["status"] = "degraded"
    else:
        status["components"]["database"] = {"status": "not_configured"}
        status["status"] = "degraded"

    if coordinator:
        status["components"]["agent"] = {"status": "ready"}
        status["components"]["ontology"] = {
            "status": "loaded" if coordinator.ontology else "not_available"
        }
        status["components"]["memory"] = {
            "status": "loaded" if coordinator.episodic else "not_available"
        }
    else:
        status["components"]["agent"] = {"status": "not_initialized"}

    return status


@app.get("/scdbAPI/schema")
async def get_schema():
    """Get database schema summary."""
    from api.deps import get_dal
    dal = get_dal()
    if not dal:
        return JSONResponse(
            status_code=503,
            content={"type": "service_unavailable", "title": "Database not configured", "status": 503},
        )
    return dal.get_schema_summary()


@app.get("/scdbAPI/schema/{table}/stats/{field}")
async def get_field_stats(table: str, field: str, top_n: int = 20):
    """Get field statistics."""
    from api.deps import get_dal
    dal = get_dal()
    if not dal:
        return JSONResponse(
            status_code=503,
            content={"type": "service_unavailable", "title": "Database not configured", "status": 503},
        )
    stats = dal.get_field_stats(table, field, top_n)
    return {
        "table": stats.table_name,
        "field": stats.field_name,
        "total": stats.total_count,
        "non_null": stats.non_null_count,
        "null_pct": stats.null_pct,
        "distinct": stats.distinct_count,
        "top_values": [{"value": v, "count": c} for v, c in stats.top_values],
    }


# ── Serve frontend static files (production) ──
web_dist = Path(__file__).parent.parent / "web" / "dist"
if web_dist.exists():
    from fastapi.responses import FileResponse

    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(web_dist / "assets")), name="static-assets")

    # SPA fallback: any non-API route serves index.html for client-side routing
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Let API routes be handled by their own routers
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        # Serve static files if they exist (e.g., vite.svg, favicon.ico)
        file_path = web_dist / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        # Otherwise serve index.html for SPA routing
        return FileResponse(web_dist / "index.html")
