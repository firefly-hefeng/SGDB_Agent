"""Pydantic data models for API-Routing Agent."""

from pydantic import BaseModel, Field


class QueryIntent(BaseModel):
    """Structured intent extracted from natural language query."""

    disease: list[str] = Field(default_factory=list, description="Disease terms (English)")
    tissue: list[str] = Field(default_factory=list, description="Tissue/anatomy terms (English)")
    tech: list[str] = Field(default_factory=list, description="Sequencing technologies")
    species: list[str] = Field(
        default_factory=lambda: ["Homo sapiens"],
        description="Species (defaults to human)",
    )
    keywords: list[str] = Field(
        default_factory=list, description="Other important keywords from original query"
    )
    time_hint: str | None = Field(default=None, description="Time-related hints like 'recent'")
    restrict_sources: list[str] | None = Field(
        default=None,
        description=(
            "If the user explicitly named one or more source databases "
            "(e.g. 'show me CellXGene datasets…'), the canonical adapter "
            "names to restrict the search to. ``None`` means no restriction."
        ),
    )
    negative_terms: list[str] = Field(
        default_factory=list,
        description=(
            "Disease / tissue / tech / cell-type terms the user excluded with "
            "negation ('NOT X', 'without Y', 'excluding Z'). Adapters retrieve "
            "on the positive fields; the reranker / synthesizer can use this "
            "field to demote or filter results that match an excluded term."
        ),
    )


class MirrorRef(BaseModel):
    """A pointer to the same study in a different source database."""

    source_db: str
    id: str
    source_url: str


class DatasetResult(BaseModel):
    """A single dataset discovery result."""

    id: str = Field(description="Dataset accession/ID")
    title: str = Field(description="Dataset title")
    description: str | None = Field(default=None, description="Description or abstract")
    organism: str | None = Field(default=None, description="Species/organism")
    sample_count: int | None = Field(default=None, description="Number of samples/cells")
    date: str | None = Field(default=None, description="Release date")
    source_db: str = Field(description="Source database name")
    source_url: str = Field(description="Link to view the dataset")
    download_url: str | None = Field(default=None, description="Direct download link if available")
    data_type: str | None = Field(default=None, description="Data type annotation")
    mirrors: list[MirrorRef] = Field(
        default_factory=list,
        description="Same study in other source databases (filled by deduplicator)",
    )


class DiscoveryResult(BaseModel):
    """Results from a single database source."""

    source: str = Field(description="Database name")
    total_found: int = Field(default=0, description="Total matches in this source")
    results: list[DatasetResult] = Field(default_factory=list)
    query_url: str | None = Field(default=None, description="Original query URL for traceability")
    error: str | None = Field(default=None, description="Error message if query failed")
    latency_ms: int = Field(default=0, description="Query latency in milliseconds")


class DiscoveryOptions(BaseModel):
    """Options for discovery query."""

    sources: list[str] = Field(
        default_factory=lambda: ["geo", "ebi", "scea", "cellxgene", "hca"],
        description="List of source databases to query",
    )
    synthesize: bool = Field(default=True, description="Whether to synthesize a summary")
    max_results_per_source: int = Field(default=20, ge=1, le=100)


class DiscoveryRequest(BaseModel):
    """Incoming discovery request."""

    query: str = Field(description="Natural language query")
    options: DiscoveryOptions = Field(default_factory=DiscoveryOptions)


class DiscoveryResponse(BaseModel):
    """Final discovery response."""

    query: str = Field(description="Original user query")
    intent: QueryIntent = Field(description="Parsed intent")
    sources: list[DiscoveryResult] = Field(default_factory=list)
    total_found: int = Field(default=0, description="Total matches across all sources")
    synthesized_answer: str | None = Field(
        default=None, description="LLM-synthesized markdown summary"
    )
    total_latency_ms: int = Field(default=0, description="Total latency in milliseconds")


class HealthStatus(BaseModel):
    """Health check response for a single adapter."""

    available: bool
    latency_ms: int = 0
    error: str | None = None


class HealthResponse(BaseModel):
    """Overall health check response."""

    status: str = "ok"
    adapters: dict[str, HealthStatus] = Field(default_factory=dict)
