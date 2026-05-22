"""
SCeQTL-Agent V2 异常层级

结构化异常处理，替代宽泛的 except Exception 捕获。
每个异常携带 stage 信息，用于 pipeline 阶段追踪。
"""

from __future__ import annotations


class SCeQTLError(Exception):
    """Base exception for all SCeQTL-Agent errors."""

    def __init__(self, message: str, *, stage: str = "", detail: str = ""):
        self.stage = stage
        self.detail = detail
        super().__init__(message)


# ── Query Understanding ──


class QueryParsingError(SCeQTLError):
    """Query could not be parsed into a structured form."""

    def __init__(self, message: str = "Query parsing failed", **kw):
        super().__init__(message, stage="parsing", **kw)


class IntentClassificationError(QueryParsingError):
    """Intent could not be determined from the query."""

    def __init__(self, message: str = "Intent classification failed", **kw):
        super().__init__(message, **kw)


class EntityExtractionError(QueryParsingError):
    """No biological entities could be extracted."""

    def __init__(self, message: str = "Entity extraction failed", **kw):
        super().__init__(message, **kw)


# ── Ontology ──


class OntologyResolutionError(SCeQTLError):
    """Ontology term resolution failed."""

    def __init__(self, message: str = "Ontology resolution failed", **kw):
        super().__init__(message, stage="ontology", **kw)


class OntologyNotFoundError(OntologyResolutionError):
    """No ontology match found for the given term."""

    def __init__(self, term: str, **kw):
        self.term = term
        super().__init__(f"No ontology match for '{term}'", **kw)


# ── SQL Generation & Execution ──


class SQLGenerationError(SCeQTLError):
    """SQL could not be generated from the parsed query."""

    def __init__(self, message: str = "SQL generation failed", **kw):
        super().__init__(message, stage="sql_generation", **kw)


class SQLExecutionError(SCeQTLError):
    """SQL execution failed or produced no valid results."""

    def __init__(self, message: str = "SQL execution failed", **kw):
        super().__init__(message, stage="sql_execution", **kw)


class AllCandidatesFailedError(SQLExecutionError):
    """All SQL candidates failed during parallel execution."""

    def __init__(self, errors: list[str] | None = None, **kw):
        self.errors = errors or []
        detail = "; ".join(self.errors) if self.errors else ""
        super().__init__("All SQL candidates failed", detail=detail, **kw)


# ── Cross-DB Fusion ──


class FusionError(SCeQTLError):
    """Cross-database fusion failed."""

    def __init__(self, message: str = "Cross-DB fusion failed", **kw):
        super().__init__(message, stage="fusion", **kw)


# ── Database ──


class DatabaseError(SCeQTLError):
    """Database connection or query error."""

    def __init__(self, message: str = "Database error", **kw):
        super().__init__(message, stage="database", **kw)


class DatabaseNotFoundError(DatabaseError):
    """Database file not found."""

    def __init__(self, path: str, **kw):
        self.path = path
        super().__init__(f"Database not found: {path}", **kw)


class ConnectionPoolExhaustedError(DatabaseError):
    """No available connections in the pool."""

    def __init__(self, **kw):
        super().__init__("Connection pool exhausted", **kw)


# ── LLM ──


class LLMError(SCeQTLError):
    """LLM call failed."""

    def __init__(self, message: str = "LLM call failed", **kw):
        super().__init__(message, stage="llm", **kw)


class LLMBudgetExceededError(LLMError):
    """Daily LLM budget exhausted."""

    def __init__(self, **kw):
        super().__init__("Daily LLM budget exceeded", **kw)


class LLMTimeoutError(LLMError):
    """LLM request timed out."""

    def __init__(self, timeout_s: float = 0, **kw):
        self.timeout_s = timeout_s
        super().__init__(f"LLM request timed out after {timeout_s:.1f}s", **kw)


# ── Synthesis ──


class SynthesisError(SCeQTLError):
    """Answer synthesis failed."""

    def __init__(self, message: str = "Answer synthesis failed", **kw):
        super().__init__(message, stage="synthesis", **kw)


# ── Cache ──


class CacheError(SCeQTLError):
    """Cache read/write error."""

    def __init__(self, message: str = "Cache error", **kw):
        super().__init__(message, stage="cache", **kw)


# ── Export ──


class ExportError(SCeQTLError):
    """Data export error."""

    def __init__(self, message: str = "Export error", **kw):
        super().__init__(message, stage="export", **kw)


class UnsupportedFormatError(ExportError):
    """Requested export format is not supported."""

    def __init__(self, fmt: str, **kw):
        self.fmt = fmt
        super().__init__(f"Unsupported export format: {fmt}", **kw)
