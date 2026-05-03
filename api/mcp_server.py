"""
MCP (Model Context Protocol) stdio server for the Singligent.

This is a STANDALONE entrypoint — it is never imported by ``api/main.py`` and
adds nothing to the core dependency set. It exposes the same tools as the
dep-free manifest (``GET /scdbAPI/agent/tools``), each implemented as a thin
``httpx`` call to the running FastAPI backend. The agent logic stays in the
REST app; this module is purely a protocol adapter so an MCP-speaking client
(Claude Desktop, a generic MCP client, the Anthropic SDK's MCP helpers) can
drive the two agents over stdio.

Run it:

    python -m api.mcp_server

The ``mcp`` SDK is imported LAZILY (only inside ``main``). If it isn't
installed, this prints a clear install hint and exits non-zero — it does NOT
traceback, and it does NOT affect the rest of the app, which never imports it.

    pip install -e '.[agent]'

Configuration:
    SCEQTL_API_BASE   base URL of the running FastAPI backend
                      (default: http://localhost:8000)
"""

from __future__ import annotations

import os
import sys

# Base URL of the live FastAPI backend. The MCP server is a thin client of it.
API_BASE = os.environ.get("SCEQTL_API_BASE", "http://localhost:8000").rstrip("/")

# Default per-tool HTTP timeout (seconds). nl_query and deep download
# resolution can be slow (live LLM / live ENA-GEO), so this is generous.
HTTP_TIMEOUT = float(os.environ.get("SCEQTL_MCP_TIMEOUT", "120"))


# ── Tool catalogue ──
# Kept in lock-step with api/routes/agent_iface.py. Each entry maps an MCP tool
# name to (description, input_schema, how-to-dispatch). Dispatch is expressed as
# (http_method, path_template, arg_style) where arg_style tells _dispatch how to
# turn the validated arguments into a request.
#
#   arg_style:
#     "json_body"  → POST the args dict as the JSON body
#     "query"      → GET with the args as query params
#     "path:<key>" → GET <path with {id}=args[key]>, remaining args as query

_TOOLS: list[dict] = [
    {
        "name": "nl_query",
        "description": (
            "Natural-language → SQL over the CURATED CATALOG (943,732 samples, "
            "8 unified sources). Returns sample-level records + a summary + "
            "provenance (the SQL, ontology expansions). Use for an overview "
            "answer, counting by tissue/disease, or looking up a known "
            "accession. If total_count is 0 (honest zero), fall back to "
            "discover_search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language question"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
            },
            "required": ["query"],
        },
        "method": "POST",
        "path": "/scdbAPI/query",
        "arg_style": "json_body",
    },
    {
        "name": "discover_search",
        "description": (
            "LIVE cross-database discovery: fans the query out in parallel to 6 "
            "federated source databases (GEO, SRA, EBI, SCEA, CellxGene, HCA), "
            "dedupes across sources, optionally synthesizes. Use for multi-entity "
            "discovery, the newest studies, and as the FALLBACK when nl_query "
            "returns 0. Slower (live). options: {sources?, "
            "max_results_per_source?, synthesize?}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language discovery query"},
                "options": {
                    "type": "object",
                    "properties": {
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["geo", "sra", "ebi", "scea", "cellxgene", "hca"],
                            },
                        },
                        "max_results_per_source": {
                            "type": "integer", "minimum": 1, "maximum": 100, "default": 20,
                        },
                        "synthesize": {"type": "boolean", "default": True},
                    },
                },
            },
            "required": ["query"],
        },
        "method": "POST",
        "path": "/scdbAPI/discover/search",
        "arg_style": "json_body",
    },
    {
        "name": "explore_search",
        "description": (
            "Faceted catalog search with EXPLICIT filter arrays (no NL parsing): "
            "tissues, diseases, organisms, assays, cell_types, source_databases, "
            "tissue_systems, disease_categories, sample_types, plus has_h5ad / "
            "min_cells. Returns paginated records + recomputed facet histograms. "
            "Use for deterministic drill-down once you know exact filter values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tissues": {"type": "array", "items": {"type": "string"}},
                "diseases": {"type": "array", "items": {"type": "string"}},
                "organisms": {"type": "array", "items": {"type": "string"}},
                "assays": {"type": "array", "items": {"type": "string"}},
                "cell_types": {"type": "array", "items": {"type": "string"}},
                "source_databases": {"type": "array", "items": {"type": "string"}},
                "tissue_systems": {"type": "array", "items": {"type": "string"}},
                "disease_categories": {"type": "array", "items": {"type": "string"}},
                "sample_types": {"type": "array", "items": {"type": "string"}},
                "has_h5ad": {"type": "boolean"},
                "min_cells": {"type": "integer"},
                "text_search": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                "sort_by": {"type": "string", "default": "n_cells"},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            },
        },
        "method": "POST",
        "path": "/scdbAPI/explore",
        "arg_style": "json_body",
    },
    {
        "name": "celltype_search",
        "description": (
            "Search the 336 standardized cell-type labels by substring; returns "
            "per-type sample/project/series/source counts and an HONEST coverage "
            "block (~24% of samples have a dominant standardized cell type; "
            "per-cell composition is CellxGene-only). Use to map a term to a "
            "standardized label + ontology id before filtering."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Substring on cell-type name"},
                "sort": {
                    "type": "string",
                    "enum": ["n_samples", "n_projects", "n_series", "cell_type"],
                    "default": "n_samples",
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            },
        },
        "method": "GET",
        "path": "/scdbAPI/celltypes/search",
        "arg_style": "query",
    },
    {
        "name": "resolve_download",
        "description": (
            "Resolve downloadable files for an accession. deep=true live-resolves "
            "exact files with byte sizes + MD5 + Aspera paths from ENA/GEO and a "
            "total size; deep=false returns instant best-effort URLs. Use once "
            "you've picked a dataset (e.g. a GSE id) to fetch or size its data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Accession, e.g. GSE181919"},
                "deep": {"type": "boolean", "default": False},
            },
            "required": ["id"],
        },
        "method": "GET",
        "path": "/scdbAPI/downloads/{id}",
        "arg_style": "path:id",
    },
    {
        "name": "entity_lookup",
        "description": (
            "Fetch the full curated record for a single accession (project / "
            "series / sample), including cross-database links and bibliographic "
            "metadata (title, abstract, PMID, DOI). Use to pull canonical "
            "metadata for one known id surfaced by a search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Accession, e.g. GSE181919"},
            },
            "required": ["id"],
        },
        "method": "GET",
        "path": "/scdbAPI/entity/{id}",
        "arg_style": "path:id",
    },
    {
        "name": "corpus_stats",
        "description": (
            "Corpus-wide statistics: totals (projects/series/samples/cell-type "
            "annotations/entity-links), per-source-database breakdown (8 sources), "
            "and top tissues + diseases with counts. Takes no arguments. Use to "
            "ground an answer in the catalog's actual size and composition."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "method": "GET",
        "path": "/scdbAPI/stats",
        "arg_style": "query",
    },
]


def _dispatch(spec: dict, arguments: dict, client) -> str:
    """Translate a validated tool call into an HTTP request and return the
    response body as text. ``client`` is an ``httpx.Client``."""
    import json

    method = spec["method"]
    path = spec["path"]
    style = spec["arg_style"]
    args = dict(arguments or {})

    if style == "json_body":
        url = f"{API_BASE}{path}"
        resp = client.request(method, url, json=args)
    elif style == "query":
        url = f"{API_BASE}{path}"
        resp = client.request(method, url, params=args)
    elif style.startswith("path:"):
        key = style.split(":", 1)[1]
        ident = args.pop(key, "")
        url = f"{API_BASE}{path.format(**{key: ident})}"
        resp = client.request(method, url, params=args)
    else:  # pragma: no cover — guarded by the static _TOOLS table
        raise ValueError(f"unknown arg_style: {style}")

    resp.raise_for_status()
    # Return compact JSON text so the MCP client receives the structured payload.
    try:
        return json.dumps(resp.json(), ensure_ascii=False)
    except ValueError:
        return resp.text


def main() -> int:
    """Entry point. Returns a process exit code."""
    # ── Lazy import of the MCP SDK + httpx. If either is missing, degrade
    #    gracefully with an install hint instead of tracebacking. ──
    try:
        import anyio
        import httpx
        import mcp.types as mcp_types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as e:
        sys.stderr.write(
            "The MCP server requires the optional 'agent' extras "
            f"(missing: {e.name}).\n"
            "Install them with:\n\n"
            "    pip install -e '.[agent]'\n\n"
            "This installs the official `mcp` Python SDK (and httpx). "
            "The dep-free tool manifest at GET /scdbAPI/agent/tools needs none "
            "of this and works today.\n"
        )
        return 1

    server: Server = Server("sceqtl-portal")
    _by_name = {t["name"]: t for t in _TOOLS}

    @server.list_tools()
    async def list_tools() -> list:
        return [
            mcp_types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in _TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        spec = _by_name.get(name)
        if spec is None:
            return [mcp_types.TextContent(type="text", text=f"Unknown tool: {name}")]
        try:
            # httpx is sync here; run it off the event loop so the stdio server
            # stays responsive.
            def _do() -> str:
                with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                    return _dispatch(spec, arguments, client)

            text = await anyio.to_thread.run_sync(_do)
        except httpx.HTTPStatusError as e:
            text = (
                f"Backend returned {e.response.status_code} for tool '{name}'. "
                f"Body: {e.response.text[:500]}"
            )
        except httpx.HTTPError as e:
            text = (
                f"Could not reach the Singligent backend at {API_BASE} for tool "
                f"'{name}': {e}. Is the FastAPI server running? "
                "Set SCEQTL_API_BASE to point at it."
            )
        return [mcp_types.TextContent(type="text", text=text)]

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    sys.stderr.write(
        f"Singligent MCP server starting (stdio). Backend: {API_BASE}. "
        f"{len(_TOOLS)} tools.\n"
    )
    anyio.run(_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
