"""
API Pydantic schemas (request/response models)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request models ──

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language query")
    session_id: str = Field(default="default", max_length=100)
    user_id: str = Field(default="anonymous", max_length=100)
    limit: int = Field(default=20, ge=1, le=200)


class ExportRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field(default="default")
    format: str = Field(default="csv", pattern=r"^(csv|json|bibtex)$")
    fields: list[str] | None = None
    limit: int = Field(default=200, ge=1, le=5000)


class FeedbackRequest(BaseModel):
    query: str = Field(default="")
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


# ── Response models ──

class SuggestionOut(BaseModel):
    type: str
    text: str
    action_query: str
    reason: str = ""


class ChartOut(BaseModel):
    type: str
    title: str
    data: dict | list


class ProvenanceOut(BaseModel):
    original_query: str = ""
    parsed_intent: str = ""
    ontology_expansions: list[dict] = []
    sql_executed: str = ""
    sql_method: str = ""
    strategy_level: str = ""
    fusion_stats: dict = {}
    data_sources: list[str] = []
    execution_time_ms: float = 0.0


class QualityOut(BaseModel):
    field_completeness: dict[str, float] = {}
    cross_validation_score: float = 0.0
    source_coverage: dict[str, int] = {}


class ResultRecord(BaseModel):
    data: dict = {}
    sources: list[str] = []
    source_count: int = 0
    quality_score: float = 0.0


class QueryResponse(BaseModel):
    summary: str = ""
    results: list[ResultRecord] = []
    total_count: int = 0
    displayed_count: int = 0
    provenance: ProvenanceOut = ProvenanceOut()
    quality_report: QualityOut = QualityOut()
    suggestions: list[SuggestionOut] = []
    charts: list[ChartOut] = []
    error: str | None = None


class OntologyResolveResponse(BaseModel):
    term: str
    field_type: str
    ontology_id: str | None = None
    label: str | None = None
    synonyms: list[str] = []
    db_values: list[dict] = []
    children_count: int = 0
    total_samples: int = 0


class AutocompleteResponse(BaseModel):
    field: str
    prefix: str
    values: list[dict] = []  # [{value, count}]


class StatsResponse(BaseModel):
    total_projects: int = 0
    total_series: int = 0
    total_samples: int = 0
    total_celltypes: int = 0
    total_entity_links: int = 0
    source_databases: list[dict] = []  # [{name, project_count, sample_count}]
    top_tissues: list[dict] = []
    top_diseases: list[dict] = []


class SessionHistoryItem(BaseModel):
    query: str
    intent: str = ""
    result_count: int = 0
    timestamp: float = 0.0


class SessionHistoryResponse(BaseModel):
    session_id: str
    turns: list[SessionHistoryItem] = []


class EntityLinksResponse(BaseModel):
    entity_id: str
    entity_type: str = ""
    entity_data: dict = {}
    cross_links: list[dict] = []


# ── Advanced Search models ──

class ParsedCondition(BaseModel):
    """A single structured condition extracted from NL parsing or user interaction."""
    field: str                    # "tissue", "disease", "assay", "organism", etc.
    operator: str = "in"          # "in", "eq", "gte", "lte", "like"
    values: list[str] = []
    display_label: str = ""       # Human-readable label
    source: str = "nl_parse"      # "nl_parse" | "user_edit" | "facet_select"
    confidence: float = 1.0


class AdvancedSearchRequest(BaseModel):
    nl_query: str | None = None
    conditions: list[ParsedCondition] = []
    session_id: str = "default"
    limit: int = Field(default=25, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort_by: str = "n_cells"
    sort_dir: str = "desc"


class AdvancedSearchResponse(BaseModel):
    conditions: list[ParsedCondition] = []
    results: list[dict] = []
    total_count: int = 0
    offset: int = 0
    limit: int = 25
    facets: dict[str, list[dict]] = {}
    summary: str = ""
    provenance: ProvenanceOut = ProvenanceOut()
    suggestions: list[SuggestionOut] = []
    error: str | None = None


class MetadataDownloadRequest(BaseModel):
    sample_pks: list[int] = []
    conditions: list[ParsedCondition] = []
    format: str = Field(default="csv", pattern=r"^(csv|json)$")
    limit: int = Field(default=1000, ge=1, le=50000)
