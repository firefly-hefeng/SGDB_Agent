"""
Agent interface: machine-readable tool manifest.

    GET /scdbAPI/agent/tools

This module is a THIN PROTOCOL ADAPTER over the existing REST backend. It does
not re-implement any agent logic — it publishes an OpenAI/Anthropic
function-calling-compatible description of the live endpoints so that an LLM
(or an MCP server, see ``api/mcp_server.py``) can discover and call the two
agents that power the Singligent:

  • the **NL→SQL "Explore" agent** over a 943,732-sample curated catalog
    (``nl_query`` → ``POST /scdbAPI/query``), and
  • the **"Discover" cross-DB agent** over 6 federated live databases
    (``discover_search`` → ``POST /scdbAPI/discover/search``).

The manifest is hand-curated from the live request/response shapes (each tool
was verified against the running backend) so that ``description`` fields carry
the WHEN-to-use guidance an agent needs to route between curated-catalog lookup
and live federation. The FastAPI app remains the single source of truth; this
route only describes it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/scdbAPI/agent", tags=["agent"])


# ── Response models (so OpenAPI documents the manifest) ──


class ToolEndpoint(BaseModel):
    """The HTTP call that backs a tool."""

    method: str = Field(description="HTTP method, e.g. GET or POST")
    path: str = Field(description="Path relative to the API base URL")


class ToolSpec(BaseModel):
    """One function-calling tool, compatible with OpenAI/Anthropic tool schemas.

    ``name`` + ``description`` + ``input_schema`` form the portable
    function-calling contract; ``endpoint`` + ``example`` tell an adapter how to
    actually perform the call against this backend.
    """

    name: str = Field(description="Unique tool name (snake_case)")
    description: str = Field(
        description="What the tool does AND when an agent should reach for it"
    )
    input_schema: dict[str, Any] = Field(
        description="JSON Schema (draft-2020-12 object) for the tool arguments"
    )
    endpoint: ToolEndpoint = Field(description="The backing HTTP endpoint")
    example: dict[str, Any] = Field(
        description="A concrete, real example: request args + a trimmed response"
    )


class ToolManifest(BaseModel):
    """The full machine-readable tool catalogue."""

    schema_version: str = Field(default="1.0")
    api_base_url: str = Field(
        description="Base URL the endpoints are relative to (no trailing slash)"
    )
    description: str = Field(
        description="One-paragraph orientation: the two agents and the data behind them"
    )
    agents: dict[str, str] = Field(
        description="Short routing note per agent: when to use each"
    )
    tools: list[ToolSpec]
    errors: dict[str, Any] = Field(
        default_factory=dict,
        description="Machine-readable error contract: wire format + status table",
    )
    rate_limit: dict[str, Any] = Field(
        default_factory=dict,
        description="Rate-limit policy agents should honor (Retry-After on 429)",
    )


# ── The tool catalogue ──
#
# Every example below is a TRIMMED capture from the live backend (curled while
# authoring this module), not a fabricated shape. Counts reflect the
# 943,732-sample build that was live at authoring time and will drift; treat
# them as illustrative, not as test oracles.

_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="nl_query",
        description=(
            "Natural-language → SQL over the CURATED CATALOG (943,732 samples, "
            "8 unified sources, ontology-expanded). Returns sample-level records "
            "with full standardized metadata (tissue/disease/cell-type/assay, "
            "normalized + ontology-term-id fields), a natural-language summary, "
            "and provenance (the SQL executed, ontology expansions, strategy). "
            "USE THIS for: an overview/landing answer to a metadata question, "
            "counting samples by tissue/disease, or looking up a specific "
            "accession that is already in the catalog. It is fast and "
            "deduplicated but only covers data already ingested. "
            "If it returns total_count=0 (an HONEST zero), fall back to "
            "discover_search to query the live source databases."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                    "description": "Natural-language question, e.g. 'lung cancer samples'",
                },
                "session_id": {
                    "type": "string",
                    "default": "default",
                    "description": "Optional conversation id for follow-up context",
                },
                "user_id": {"type": "string", "default": "anonymous"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 20,
                    "description": "Max sample records to return",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="POST", path="/scdbAPI/query"),
        example={
            "request": {"query": "lung cancer samples"},
            "response_excerpt": {
                "summary": "找到约 3,283 个lung + lung cancer相关样本，结果较多——当前展示前 100 条用于浏览。",
                "total_count": 3283,
                "displayed_count": 100,
                "results": [
                    {
                        "data": {
                            "sample_id": "GSM3732848",
                            "sample_source": "geo",
                            "tissue_standard": "lung",
                            "disease_standard": "non-small cell lung cancer",
                            "disease_standard_l1": "lung cancer",
                            "organism_common": "human",
                            "n_cells": 15265,
                        },
                        "sources": ["geo"],
                        "quality_score": 78.3,
                        "facet_match": {"tissue": "match", "disease": "partial"},
                    }
                ],
                "provenance": {
                    "sql_method": "contextual_engine",
                    "ontology_expansions": {"...": "..."},
                    "sql_executed": "SELECT ... FROM unified_samples ...",
                },
            },
        },
    ),
    ToolSpec(
        name="discover_search",
        description=(
            "LIVE cross-database discovery agent: fans the query out, in "
            "parallel, to 6 federated source databases (GEO, SRA, EBI/"
            "ArrayExpress, SCEA, CellxGene, HCA), parses intent, dedupes across "
            "sources by accession-mirror detection, and (optionally) synthesizes "
            "an answer. Returns the parsed intent plus per-source result lists "
            "with titles, abstracts, sample counts, and download URLs. "
            "USE THIS for: multi-entity discovery, the newest studies (it hits "
            "the sources live, so it sees records not yet ingested into the "
            "curated catalog), and as the FALLBACK whenever nl_query returns 0. "
            "It is slower (live network fan-out, multiple seconds) than nl_query. "
            "Set options.synthesize=false to skip the LLM summary for speed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Natural-language discovery query",
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["geo", "sra", "ebi", "scea", "cellxgene", "hca"],
                            },
                            "description": (
                                "Subset of source databases to query. "
                                "Default: ['geo','ebi','scea','cellxgene','hca']."
                            ),
                        },
                        "max_results_per_source": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                            "description": "Cap per source (NOT a global cap)",
                        },
                        "synthesize": {
                            "type": "boolean",
                            "default": True,
                            "description": "Whether to LLM-synthesize a markdown summary",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="POST", path="/scdbAPI/discover/search"),
        example={
            "request": {
                "query": "pancreatic islet diabetes single-cell",
                "options": {"max_results_per_source": 3, "synthesize": False},
            },
            "response_excerpt": {
                "query": "pancreatic islet diabetes single-cell",
                "intent": {
                    "disease": ["diabetes"],
                    "tissue": ["pancreatic islet", "islets of Langerhans"],
                    "tech": ["scRNA-seq"],
                    "species": ["Homo sapiens"],
                },
                "sources": [
                    {
                        "source": "geo",
                        "total_found": 63,
                        "results": [
                            {
                                "id": "GSE282230",
                                "title": "Single-cell RNA Sequencing Uncovers Molecular Mechanisms of Human Pancreatic Islet Dysfunction Under Overnutrition Metabolic Stress",
                                "organism": "Homo sapiens",
                                "sample_count": 14,
                                "source_db": "GEO",
                                "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE282230",
                            }
                        ],
                    }
                ],
            },
        },
    ),
    ToolSpec(
        name="explore_search",
        description=(
            "Faceted, structured search over the curated catalog. Unlike "
            "nl_query this takes EXPLICIT filter arrays (no NL parsing): tissues, "
            "diseases, organisms, assays, cell_types, source_databases, plus "
            "standardized facets (tissue_systems, disease_categories, "
            "sample_types) and flags (has_h5ad, min_cells). Returns paginated "
            "sample records AND recomputed facet histograms for every field — "
            "ideal for building filter UIs or drilling down deterministically. "
            "USE THIS when you already know the exact filter values (e.g. from a "
            "prior nl_query or facet) and want pagination + facet counts; use "
            "nl_query instead when you only have a free-text question."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tissues": {"type": "array", "items": {"type": "string"}},
                "diseases": {"type": "array", "items": {"type": "string"}},
                "organisms": {"type": "array", "items": {"type": "string"}},
                "assays": {"type": "array", "items": {"type": "string"}},
                "cell_types": {"type": "array", "items": {"type": "string"}},
                "source_databases": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "geo", "ega", "ncbi", "ebi",
                            "cellxgene", "psychad", "htan", "hca",
                        ],
                    },
                },
                "tissue_systems": {"type": "array", "items": {"type": "string"}},
                "disease_categories": {"type": "array", "items": {"type": "string"}},
                "sample_types": {"type": "array", "items": {"type": "string"}},
                "sex": {"type": ["string", "null"]},
                "min_cells": {"type": ["integer", "null"]},
                "has_h5ad": {
                    "type": ["boolean", "null"],
                    "description": "Filter to samples with a downloadable .h5ad",
                },
                "text_search": {"type": ["string", "null"]},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 25,
                },
                "sort_by": {"type": "string", "default": "n_cells"},
                "sort_dir": {"type": "string", "enum": ["asc", "desc"], "default": "desc"},
            },
            "required": [],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="POST", path="/scdbAPI/explore"),
        example={
            "request": {"tissues": ["lung"], "diseases": ["lung cancer"], "limit": 1},
            "response_excerpt": {
                "total_count": 1301,
                "offset": 0,
                "limit": 1,
                "results": [
                    {
                        "sample_pk": 25659,
                        "sample_id": "...:Lambrechts_Thienpont_2018_6149v2_5",
                        "tissue_standard": "lung",
                        "disease_standard": "non-small cell lung cancer",
                        "source_database": "cellxgene",
                        "has_h5ad": True,
                        "n_cells": 15265,
                    }
                ],
                "facets": {
                    "tissue": [{"value": "lung", "count": 1301}],
                    "disease": [{"value": "non-small cell lung cancer", "count": 980}],
                },
            },
        },
    ),
    ToolSpec(
        name="celltype_search",
        description=(
            "Search the 336 standardized cell-type labels in the catalogue by "
            "substring, returning per-type sample/project/series/source counts. "
            "Critically, every response carries an HONEST coverage block: only "
            "~24% of samples have a dominant standardized cell_type label, and "
            "fine-grained per-cell composition exists for CellxGene samples only "
            "— so an agent can qualify claims about cell-type abundance rather "
            "than over-stating coverage. USE THIS to map a user's cell-type term "
            "to a standardized label + ontology id before filtering, or to "
            "report how well-annotated a cell type is across the corpus."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Case-insensitive substring on the cell-type name",
                },
                "sort": {
                    "type": "string",
                    "enum": ["n_samples", "n_projects", "n_series", "cell_type"],
                    "default": "n_samples",
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 50,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="GET", path="/scdbAPI/celltypes/search"),
        example={
            "request": {"q": "T cell", "limit": 2},
            "response_excerpt": {
                "cell_types": [
                    {
                        "cell_type": "T cell",
                        "ontology_term_id": "CL:0000084",
                        "n_samples": 43969,
                        "n_projects": 276,
                        "n_sources": 5,
                    }
                ],
                "total": 35,
                "coverage": {
                    "basis": "dominant cell_type_standard label per sample",
                    "samples_annotated": 225811,
                    "samples_total": 943732,
                    "annotated_pct": 23.9,
                    "distinct_types": 336,
                    "composition_note": "Fine-grained per-cell composition is available for CellxGene samples only.",
                },
            },
        },
    ),
    ToolSpec(
        name="resolve_download",
        description=(
            "Resolve the downloadable files for a dataset/accession id. With "
            "deep=true it performs LIVE resolution against ENA/GEO and returns "
            "the exact file list — labels, URLs, byte sizes, MD5 checksums and "
            "Aspera paths where available — plus a total size. With deep=false it "
            "returns the instant best-effort URLs. USE THIS once you have picked "
            "a dataset (e.g. a GSE id from nl_query or discover_search) and want "
            "to actually fetch the data or report its size/contents. deep=true is "
            "slower (live network) — prefer it when exact files/sizes matter."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Dataset/accession id, e.g. GSE181919 or a series/project id",
                },
                "deep": {
                    "type": "boolean",
                    "default": False,
                    "description": "Live-resolve exact files+md5+sizes from ENA/GEO",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="GET", path="/scdbAPI/downloads/{id}"),
        example={
            "request": {"id": "GSE181919", "deep": True},
            "response_excerpt": {
                "entity_id": "GSE181919",
                "source_database": "geo",
                "deep": True,
                "total_bytes": 128266240,
                "total_size_human": "122.3 MB",
                "downloads": [
                    {
                        "file_type": "matrix",
                        "label": "GSE181919_UMI_counts.txt.gz",
                        "url": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE181nnn/GSE181919/suppl/GSE181919_UMI_counts.txt.gz",
                        "bytes": 127926272,
                        "file_size_human": "122.0 MB (approx)",
                        "md5": None,
                    }
                ],
            },
        },
    ),
    ToolSpec(
        name="entity_lookup",
        description=(
            "Fetch the full curated record for a single entity id (a project / "
            "series / sample accession) including its cross-database links (the "
            "same study mirrored across GEO/SRA/EBI etc.) and bibliographic "
            "metadata (title, abstract, PMID, DOI, publication date). USE THIS to "
            "pull the canonical metadata + provenance for one known id, after a "
            "search has surfaced it; for finding ids use nl_query / "
            "discover_search / explore_search."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Entity accession, e.g. GSE181919",
                }
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="GET", path="/scdbAPI/entity/{id}"),
        example={
            "request": {"id": "GSE181919"},
            "response_excerpt": {
                "entity_id": "GSE181919",
                "entity_type": "project",
                "entity_data": {
                    "project_id": "GSE181919",
                    "source_database": "geo",
                    "title": "Single-cell transcriptome profiling of the stepwise progression of head and neck cancer",
                    "organism": "['Homo sapiens']",
                    "pmid": "36828832",
                    "publication_date": "2022-08-31",
                },
            },
        },
    ),
    ToolSpec(
        name="corpus_stats",
        description=(
            "Return corpus-wide statistics: total projects/series/samples/cell-"
            "type-annotations/entity-links, the per-source-database breakdown "
            "(8 curated sources with counts), and the top tissues and diseases "
            "with sample counts. USE THIS to ground an answer in the actual size "
            "and composition of the catalog, or to pick well-populated facets "
            "before drilling down. Takes no arguments."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        endpoint=ToolEndpoint(method="GET", path="/scdbAPI/stats"),
        example={
            "request": {},
            "response_excerpt": {
                "total_projects": 16376,
                "total_series": 14110,
                "total_samples": 943732,
                "total_celltypes": 378029,
                "total_entity_links": 19513,
                "source_databases": [
                    {"name": "geo", "project_count": 5402, "sample_count": 342328},
                    {"name": "ega", "project_count": 1636, "sample_count": 253073},
                ],
                "top_tissues": [{"value": "blood", "count": 49236}],
                "top_diseases": [{"value": "colorectal cancer", "count": 30299}],
            },
        },
    ),
]


_MANIFEST = ToolManifest(
    schema_version="1.0",
    api_base_url="http://localhost:8000",
    description=(
        "Two agents behind one REST surface for human single-cell RNA-seq "
        "metadata. (1) An NL→SQL 'Explore' agent over a curated, deduplicated "
        "catalog of 943,732 samples drawn from 8 unified sources — fast, "
        "ontology-aware lookup/overview. (2) A 'Discover' cross-DB agent that "
        "queries 6 federated source databases LIVE in parallel — slower, but "
        "sees the newest records and data not yet ingested. The honest split: "
        "the curated catalog is built from 8 ingested sources; live federation "
        "reaches 6 source databases directly. When the curated catalog returns "
        "an honest zero, fall back to live discovery."
    ),
    agents={
        "explore_nl_sql": (
            "Curated catalog (943,732 samples, 8 sources). Use nl_query for "
            "free-text questions/overview/id lookup; explore_search for "
            "deterministic faceted drill-down. Fast, deduplicated, ingested-only."
        ),
        "discover_cross_db": (
            "Live federation over 6 databases (GEO/SRA/EBI/SCEA/CellxGene/HCA). "
            "Use discover_search for multi-entity discovery, newest studies, and "
            "as the fallback when nl_query returns total_count=0. Slower (live)."
        ),
    },
    tools=_TOOLS,
    errors={
        "wire_format": (
            "All 4xx/5xx responses are RFC-7807 problem+json with fields "
            "{type, title, status, detail} (detail is a human-readable string). "
            "Validation errors (422) additionally carry an errors[] array of "
            "field-level problems (FastAPI's location/msg/type entries)."
        ),
        "statuses": {
            "400": "Bad request — malformed body or invalid parameter values",
            "404": "Unknown id / table / column (not a 500)",
            "422": "Request validation failed — see errors[] for the field(s)",
            "429": "Rate limited — honor the Retry-After header before retrying",
            "503": "Agent or database not initialized yet — retry after startup",
            "500": "Internal error (type=internal_error)",
        },
        "example": {
            "type": "rate_limit_exceeded", "title": "Too Many Requests",
            "status": 429, "detail": "Rate limit: 60 requests per minute",
        },
    },
    rate_limit={
        "default_requests_per_minute": 60,
        "env_override": "SCEQTL_RATE_LIMIT",
        "scope": "per client IP",
        "on_exceed": "429 with a Retry-After header (seconds) + retry_after_seconds in body",
    },
)


@router.get(
    "/tools",
    response_model=ToolManifest,
    summary="Machine-readable tool manifest for LLM/agent function-calling",
    response_model_exclude_none=False,
)
async def get_tool_manifest(request: Request) -> ToolManifest:
    """Return the function-calling-compatible tool catalogue.

    The shape is intentionally compatible with both the OpenAI and Anthropic
    tool-definition conventions: each tool carries ``name`` + ``description`` +
    ``input_schema`` (a JSON-Schema object), so a caller can drop ``tools`` into
    a chat-completions / messages request after translating ``endpoint`` into an
    actual HTTP call (or let ``api/mcp_server.py`` do that over MCP).

    ``api_base_url`` is resolved from the incoming request (honoring proxy
    headers) so the manifest is correct behind a reverse proxy / on any host,
    not hardcoded to localhost.
    """
    # Self-locating: reflect the EXACT base the manifest was reached at, INCLUDING
    # any sub-path. On the public deploy the app sits behind a reverse proxy at
    # `/singligent/` (FastAPI root_path=/singligent), so base_url is
    # `https://biobigdata.nju.edu.cn/singligent` and the endpoint paths
    # (`/scdbAPI/...`) must append to that — do NOT strip the prefix, or agents
    # would build `https://host/scdbAPI/...`, which the proxy does not expose.
    base = str(request.base_url).rstrip("/")
    return _MANIFEST.model_copy(update={"api_base_url": base})
