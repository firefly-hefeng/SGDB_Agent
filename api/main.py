"""
Singligent FastAPI Application

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

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

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
    logger.info("Starting Singligent...")

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
            parser_mode=settings.agent.parser_mode,
        )
        logger.info("Agent parser_mode=%s", settings.agent.parser_mode)
        logger.info(
            "CoordinatorAgent initialized (ontology=%s, memory=%s)",
            coordinator.ontology is not None,
            coordinator.episodic is not None,
        )

    set_dal(dal)
    set_coordinator(coordinator)

    # Report the discovery sub-agent's resolved LLM/rerank state at startup so a
    # silent LLM-off regression (Phase-39 root cause: DISCOVERY_ env-prefix hid
    # the shared KIMI_API_KEY) is visible in the logs, not invisible.
    try:
        from src.discovery import get_settings as _get_disc_settings
        _ds = _get_disc_settings().effective_llm_summary()
        if _ds["llm_active"]:
            logger.info(
                "Discovery agent: LLM ACTIVE (%s via %s), rerank=%s, ncbi_key=%s",
                _ds["llm_model"], _ds["llm_base_url"], _ds["rerank_backend"], _ds["ncbi_key"],
            )
        else:
            logger.warning(
                "Discovery agent: LLM INACTIVE — running rule-only intent parse + "
                "programmatic synthesis (rerank=%s). Set KIMI_API_KEY to enable.",
                _ds["rerank_backend"],
            )
    except Exception as e:  # noqa: BLE001 — never block startup on a log line
        logger.warning("Discovery LLM-state probe failed: %s", e)

    # Pre-warm dashboard cache so the first user request is instant
    if dal:
        try:
            from api.routes.stats import prewarm_dashboard_cache
            prewarm_dashboard_cache(dal)
        except Exception as e:
            logger.warning("Dashboard cache pre-warm failed: %s", e)
        try:
            from api.routes.collections import prewarm_featured_cache
            # Run on a separate thread so a slow theme query can't block
            # the rest of startup. The first request reuses the cache
            # the moment it lands.
            import threading
            threading.Thread(target=prewarm_featured_cache, daemon=True).start()
            logger.info("Featured collections pre-warm dispatched")
        except Exception as e:
            logger.warning("Featured collections pre-warm dispatch failed: %s", e)
        try:
            from api.routes.explore import prewarm_explore_unfiltered
            import threading
            threading.Thread(target=prewarm_explore_unfiltered, daemon=True).start()
            logger.info("Explore unfiltered pre-warm dispatched")
        except Exception as e:
            logger.warning("Explore pre-warm dispatch failed: %s", e)
        try:
            from api.routes.projects import prewarm_projects_series
            import threading
            threading.Thread(target=prewarm_projects_series, daemon=True).start()
            logger.info("Projects/Series unfiltered pre-warm dispatched")
        except Exception as e:
            logger.warning("Projects/Series pre-warm dispatch failed: %s", e)
        try:
            from api.routes.celltypes import prewarm_celltypes
            import threading
            threading.Thread(target=prewarm_celltypes, daemon=True).start()
        except Exception as e:
            logger.warning("Cell-type catalogue pre-warm dispatch failed: %s", e)
        # NB (Phase 33): do NOT pre-warm the ontology resolver from a background
        # thread — its SQLite cache connection becomes bound to whichever thread
        # first touches it, and SQLite forbids cross-thread reuse. The agent
        # pipeline runs in the event-loop thread, so a prewarm thread would
        # poison the connection ("SQLite objects created in a thread can only be
        # used in that same thread"). The ~3-5s first-query cold cost is
        # acceptable and self-warms after the first NL query.

    yield

    logger.info("Shutting down Singligent...")
    if dal:
        dal.close()
    set_dal(None)
    set_coordinator(None)


# Service version + current phase. Source of truth is pyproject.toml;
# we read it once at import time so /scdbAPI/version stays aligned with
# the packaged distribution and the FastAPI OpenAPI version below.
def _read_pyproject_version() -> str:
    try:
        import tomllib  # py311+
    except Exception:
        try:
            import tomli as tomllib  # type: ignore
        except Exception:
            return "0.0.0"
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    try:
        with pyproject.open("rb") as fh:
            return tomllib.load(fh).get("project", {}).get("version") or "0.0.0"
    except Exception:
        return "0.0.0"


_APP_VERSION: str = _read_pyproject_version()
_PHASE: int = 40  # Bump alongside docs/PHASE<N>*.md when a phase ships.


app = FastAPI(
    title="Singligent API",
    summary="Unified single-cell RNA-seq metadata portal — REST API",
    description=(
        "Ontology-aware natural-language retrieval agent and federated "
        "cross-database discovery agent for human scRNA-seq metadata. "
        "Powers the Singligent portal — public deploy "
        "https://biobigdata.nju.edu.cn/singligent/ , Nanjing University "
        "(https://compbio.nju.edu.cn/).\n\n"
        "## Surfaces\n\n"
        "- **Curated catalog**: `/scdbAPI/explore`, `/scdbAPI/projects/*`, "
        "  `/scdbAPI/series/*` — instant SQL-backed search over 943K samples "
        "  from 8 unified sources.\n"
        "- **Natural-language search**: `/scdbAPI/advanced-search` — NL → SQL "
        "  with ontology expansion, returns facets + provenance.\n"
        "- **Live cross-DB discovery**: `/scdbAPI/discover/*` — fans your "
        "  query out to GEO / SRA / EBI / SCEA / CellxGene / HCA in parallel; "
        "  SSE endpoint for streaming.\n"
        "- **Collections**: `/scdbAPI/collections/*` — curated themed bundles "
        "  with live counts; trending projects by cell count.\n"
        "- **Workspaces**: `/scdbAPI/workspace/*` — per-client lightweight "
        "  bookmark lists (identity is `X-Client-UUID` + IP).\n"
        "- **Downloads / manifest**: `/scdbAPI/downloads/*` — per-dataset URL "
        "  resolution, bulk-script generation (TSV / bash / aria2c), unified "
        "  metadata CSV/JSON export.\n\n"
        "## Authentication\n\n"
        "No authentication required for read endpoints. Per-IP rate limiting "
        "(`SCEQTL_RATE_LIMIT`, default 60 req/min)."
    ),
    version=_APP_VERSION,  # single source of truth: pyproject.toml
    lifespan=lifespan,
    openapi_tags=[
        {"name": "discover", "description": "Cross-database discovery (live, SSE)."},
        {"name": "collections", "description": "Curated themed collections."},
        {"name": "explore", "description": "Curated catalog faceted search."},
        {"name": "project-search", "description": "Project / series level search."},
        {"name": "advanced-search", "description": "NL → SQL agent."},
        {"name": "workspace", "description": "Per-client bookmark lists."},
        {"name": "downloads", "description": "Manifest generation + metadata export."},
    ],
)


# ── Path helpers ──
# The SPA is served at /singligent/ so static assets land under /singligent/assets/
# while the bare /assets/ prefix is what FastAPI's StaticFiles default would
# expose. Both must be treated as static for the middleware skip-lists.

_STATIC_ASSET_PREFIXES = ("/singligent/assets", "/assets")
_HEALTH_PATHS = frozenset({"/scdbAPI/health", "/singligent/scdbAPI/health"})


def _is_static_asset(path: str) -> bool:
    return path.startswith(_STATIC_ASSET_PREFIXES)


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
    if not _is_static_asset(path) and path != "/favicon.ico":
        logger.info(
            "[%s] %s %s → %d (%.0fms)",
            request_id, request.method, path, response.status_code, elapsed_ms,
        )

    return response


# ── Middleware: Simple rate limiter (in-memory, per IP) ──

_rate_store: dict[str, list[float]] = {}
_rate_store_last_cleanup: float = 0.0
RATE_LIMIT = int(os.environ.get("SCEQTL_RATE_LIMIT", "60"))  # requests per minute
RATE_WINDOW = 60.0  # seconds
RATE_CLEANUP_INTERVAL = 300.0  # cleanup stale IPs every 5 minutes
# When the app sits behind nginx/cloudflare, request.client.host is the
# proxy IP and the rate limiter would bucket every external user into
# one counter. Set SCEQTL_TRUST_PROXY=1 to read X-Forwarded-For instead.
TRUST_PROXY = os.environ.get("SCEQTL_TRUST_PROXY", "0").lower() in ("1", "true", "yes")


def _client_ip_for_rate_limit(request: Request) -> str:
    if TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Take the left-most non-empty token: that's the original client.
            for tok in xff.split(","):
                ip = tok.strip()
                if ip:
                    return ip
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple sliding-window rate limiter per client IP."""
    # Skip rate limiting for static assets and health probes.
    # Both the /scdbAPI and /singligent/scdbAPI health paths are skip-listed
    # because the SPA hits the /singligent/ mirror.
    path = request.url.path
    if _is_static_asset(path) or path in _HEALTH_PATHS or path == "/":
        return await call_next(request)

    client_ip = _client_ip_for_rate_limit(request)
    now = time.time()

    # Periodic cleanup of stale IPs to prevent memory leak
    global _rate_store_last_cleanup
    if now - _rate_store_last_cleanup > RATE_CLEANUP_INTERVAL:
        stale_ips = [ip for ip, ts in _rate_store.items() if not ts or now - ts[-1] > RATE_WINDOW]
        for ip in stale_ips:
            del _rate_store[ip]
        _rate_store_last_cleanup = now

    # Clean old entries
    if client_ip in _rate_store:
        _rate_store[client_ip] = [t for t in _rate_store[client_ip] if now - t < RATE_WINDOW]
    else:
        _rate_store[client_ip] = []

    if len(_rate_store[client_ip]) >= RATE_LIMIT:
        # Retry-After tells agents/clients exactly how long to back off — the
        # time until the oldest in-window request ages out (≤ RATE_WINDOW).
        oldest = _rate_store[client_ip][0] if _rate_store[client_ip] else now
        retry_after = max(1, int(RATE_WINDOW - (now - oldest)) + 1)
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "type": "rate_limit_exceeded",
                "title": "Too Many Requests",
                "detail": f"Rate limit: {RATE_LIMIT} requests per minute",
                "status": 429,
                "retry_after_seconds": retry_after,
            },
        )

    _rate_store[client_ip].append(now)
    return await call_next(request)


# ── Global exception handler (RFC 7807 problem+json) ──

@app.exception_handler(SCeQTLError)
async def singligent_error_handler(request: Request, exc: SCeQTLError):
    """Convert domain exceptions to RFC 7807 problem+json."""
    return JSONResponse(
        status_code=500,
        content={
            "type": f"singligent_error/{exc.stage or 'unknown'}",
            "title": type(exc).__name__,
            "detail": str(exc),
            "status": 500,
            "stage": exc.stage,
        },
    )


_HTTP_TITLES = {
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 409: "Conflict", 422: "Unprocessable Entity",
    429: "Too Many Requests", 500: "Internal Server Error", 503: "Service Unavailable",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """RFC-7807 for raise HTTPException(...) + 404/405 — so the agent-manifest
    error contract (all 4xx/5xx are problem+json {type,title,status,detail}) is
    actually true, not just for domain/500 errors."""
    detail = exc.detail if isinstance(exc.detail, str) else jsonable_encoder(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None) or None,
        content={
            "type": f"http_error/{exc.status_code}",
            "title": _HTTP_TITLES.get(exc.status_code, "HTTP Error"),
            "status": exc.status_code,
            "detail": detail,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """RFC-7807 for 422 validation errors, preserving the field-level detail[]."""
    return JSONResponse(
        status_code=422,
        content={
            "type": "validation_error",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request validation failed",
            "errors": jsonable_encoder(exc.errors()),
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
#
# Phase 32: when an explicit allowlist is configured, also send
# `Access-Control-Allow-Credentials: true` so authenticated requests
# (X-Client-UUID workspace mutations) only succeed from approved origins.
# Wildcard `*` remains the default for local dev / internal demos but is
# explicitly INCOMPATIBLE with credentialed mutations — the FastAPI CORS
# middleware drops `allow_credentials` automatically when origins are `*`.

cors_origins = [o.strip() for o in os.environ.get("SCEQTL_CORS_ORIGINS", "*").split(",")]
_cors_allow_credentials = cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-UUID", "X-Request-ID", "Authorization"],
    allow_credentials=_cors_allow_credentials,
    expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
    max_age=3600,
)


# Phase 32: defensive HTTP headers — guard against XFS clickjacking,
# MIME sniffing, and uncontrolled Referer leakage. The SPA itself is
# served same-origin so a CSP that only allows `self` for everything
# except images and CDN-loaded fonts is safe and effective.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # CSP intentionally permissive on connect-src to keep `fetch('/scdbAPI/…')`
    # working in dev where the SPA may be served from a different port.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response

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
from api.routes.debug import router as debug_router
from api.routes.projects import router as projects_router
from api.routes.workspace import router as workspace_router
from api.routes.discover import router as discover_router
from api.routes.collections import router as collections_router
from api.routes.celltypes import router as celltypes_router
from api.routes.agent_iface import router as agent_iface_router
from api.websocket import router as ws_router

# ── API Routes ──
# Mount API routes under /scdbAPI (direct access)
# ── Meta router (info / version / health / schema) ──
# Mounted as a router (not bare @app.get) so the /singligent mirror block
# below picks it up — the SPA's BASE_URL is /singligent/scdbAPI, so any
# endpoint reached only at the bare /scdbAPI/* prefix would 404 from the
# SPA. See tests/unit/test_singligent_mount.py.
meta_router = APIRouter(prefix="/scdbAPI", tags=["meta"])


@meta_router.get("/info")
async def api_info():
    # Audit F27: keep the service name consistent with /version ("SGDB Agent").
    return {
        "service": "SGDB Agent",
        "status": "running",
        "version": _APP_VERSION,
    }


@meta_router.get("/version")
async def api_version():
    """Surface the provenance every biologist needs to cite a specific
    run of the portal: app version, DB build date, ontology version,
    agent parser mode, schema fingerprint, last ETL run.

    Anything returned by /version should be safe to embed in a paper's
    methods section verbatim.
    """
    from api.deps import get_dal, get_coordinator

    payload: dict = {
        "service": "SGDB Agent",
        "app_version": _APP_VERSION,
        "phase": _PHASE,
    }

    dal = get_dal()
    if dal:
        try:
            r = dal.execute(
                "SELECT MAX(last_updated) AS latest FROM stats_overall"
            )
            if r.rows and r.rows[0]["latest"]:
                payload["db_build_date"] = r.rows[0]["latest"]
        except Exception:
            pass
        try:
            r = dal.execute("SELECT value FROM stats_overall WHERE metric='total_samples'")
            if r.rows:
                payload["db_sample_count"] = r.rows[0]["value"]
        except Exception:
            pass
        try:
            r = dal.execute("SELECT value FROM stats_overall WHERE metric='total_projects'")
            if r.rows:
                payload["db_project_count"] = r.rows[0]["value"]
        except Exception:
            pass
        try:
            # Audit F26: etl_run_log has no run_finished_at/run_label columns —
            # the old query always raised, silently dropping this provenance.
            # Use the real schema (source_database, phase, status, completed_at).
            r = dal.execute(
                "SELECT source_database, phase, status, completed_at "
                "FROM etl_run_log WHERE completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1"
            )
            if r.rows:
                payload["last_etl_run"] = {
                    "label": f"{r.rows[0]['source_database']} / {r.rows[0]['phase']}",
                    "status": r.rows[0]["status"],
                    "finished_at": r.rows[0]["completed_at"],
                }
        except Exception:
            pass

    coordinator = get_coordinator()
    if coordinator:
        payload["agent_parser_mode"] = getattr(coordinator, "parser_mode", None)
        if coordinator.ontology:
            try:
                cache = coordinator.ontology.cache
                stats = cache.get_stats()
                payload["ontology"] = {
                    "total_terms": stats.get("total_terms"),
                    "by_source": stats.get("by_source"),
                    "total_mappings": stats.get("total_mappings"),
                }
            except Exception:
                pass

    return payload


@meta_router.get("/health")
async def health():
    """Health check with component status."""
    from api.deps import get_dal, get_coordinator

    status = {"status": "healthy", "components": {}}
    dal = get_dal()
    coordinator = get_coordinator()

    if dal:
        try:
            result = dal.execute(
                "SELECT value as cnt FROM stats_overall WHERE metric = 'total_samples'"
            )
            if result.rows:
                sample_count = result.rows[0]["cnt"]
            else:
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

    try:
        from src.discovery.adapters import ADAPTERS as _DISC_ADAPTERS

        status["components"]["discovery"] = {
            "status": "ready",
            "sources_configured": list(_DISC_ADAPTERS.keys()),
        }
    except Exception as e:
        status["components"]["discovery"] = {"status": "error", "error": str(e)}

    return status


@meta_router.get("/schema")
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


@meta_router.get("/schema/{table}/stats/{field}")
async def get_field_stats(table: str, field: str, top_n: int = 20):
    """Get field statistics."""
    from fastapi import HTTPException

    from api.deps import get_dal
    dal = get_dal()
    if not dal:
        return JSONResponse(
            status_code=503,
            content={"type": "service_unavailable", "title": "Database not configured", "status": 503},
        )
    try:
        stats = dal.get_field_stats(table, field, top_n)
    except Exception as e:
        msg = str(e).lower()
        if "no such table" in msg or "no such column" in msg:
            raise HTTPException(
                status_code=404,
                detail=f"{table}.{field}: {e}",
            )
        raise
    return {
        "table": stats.table_name,
        "field": stats.field_name,
        "total": stats.total_count,
        "non_null": stats.non_null_count,
        "null_pct": stats.null_pct,
        "distinct": stats.distinct_count,
        "top_values": [{"value": v, "count": c} for v, c in stats.top_values],
    }


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
app.include_router(debug_router)
app.include_router(projects_router)
app.include_router(workspace_router)
app.include_router(discover_router)
app.include_router(collections_router)
app.include_router(celltypes_router)
app.include_router(agent_iface_router)
app.include_router(meta_router)
app.include_router(ws_router)

# Also mount under /singligent for frontend compatibility. Every router that
# the SPA touches must be in this list — the SPA's BASE_URL is
# `/singligent/scdbAPI`, so anything missing here falls through to the
# static-file catch-all below and returns 404 (GET) or 405 (POST).
app.include_router(query_router, prefix="/singligent")
app.include_router(ontology_router, prefix="/singligent")
app.include_router(entity_router, prefix="/singligent")
app.include_router(stats_router, prefix="/singligent")
app.include_router(session_router, prefix="/singligent")
app.include_router(export_router, prefix="/singligent")
app.include_router(explore_router, prefix="/singligent")
app.include_router(dataset_router, prefix="/singligent")
app.include_router(downloads_router, prefix="/singligent")
app.include_router(advanced_search_router, prefix="/singligent")
app.include_router(projects_router, prefix="/singligent")
app.include_router(workspace_router, prefix="/singligent")
app.include_router(discover_router, prefix="/singligent")
app.include_router(collections_router, prefix="/singligent")
app.include_router(celltypes_router, prefix="/singligent")
app.include_router(agent_iface_router, prefix="/singligent")
app.include_router(meta_router, prefix="/singligent")


# ── Serve frontend static files (production) ──
web_dist = Path(__file__).parent.parent / "web" / "dist"
if web_dist.exists():
    from fastapi.responses import FileResponse

    # Mount under /singligent to match frontend build
    app.mount("/singligent/assets", StaticFiles(directory=str(web_dist / "assets")), name="static-assets")

    # Serve other static files (exclude API paths)
    @app.get("/singligent/{file_path:path}", include_in_schema=False)
    async def serve_static(file_path: str, request: Request):
        # Skip API paths - let them be handled by API routers
        if file_path.startswith("scdbAPI"):
            # Return 404 to let FastAPI continue to other routes
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        file = web_dist / file_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(web_dist / "index.html")

    # Root redirects to /singligent/
    @app.get("/")
    async def serve_root():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/singligent/", status_code=302)
