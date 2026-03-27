"""
Unit Tests — Custom Exception Hierarchy

Tests all exception classes, inheritance, and attributes.
"""
import pytest

from src.core.exceptions import (
    SCeQTLError,
    QueryParsingError,
    IntentClassificationError,
    EntityExtractionError,
    OntologyResolutionError,
    OntologyNotFoundError,
    SQLGenerationError,
    SQLExecutionError,
    AllCandidatesFailedError,
    FusionError,
    DatabaseError,
    DatabaseNotFoundError,
    ConnectionPoolExhaustedError,
    LLMError,
    LLMBudgetExceededError,
    LLMTimeoutError,
    SynthesisError,
    CacheError,
    ExportError,
    UnsupportedFormatError,
)


class TestExceptionHierarchy:
    """All domain exceptions inherit from SCeQTLError."""

    def test_base_exception_attributes(self):
        e = SCeQTLError("test error", stage="test", detail="some detail")
        assert str(e) == "test error"
        assert e.stage == "test"
        assert e.detail == "some detail"

    def test_base_exception_is_exception(self):
        assert issubclass(SCeQTLError, Exception)

    @pytest.mark.parametrize("exc_cls,parent_cls", [
        (QueryParsingError, SCeQTLError),
        (IntentClassificationError, QueryParsingError),
        (EntityExtractionError, QueryParsingError),
        (OntologyResolutionError, SCeQTLError),
        (OntologyNotFoundError, OntologyResolutionError),
        (SQLGenerationError, SCeQTLError),
        (SQLExecutionError, SCeQTLError),
        (AllCandidatesFailedError, SQLExecutionError),
        (FusionError, SCeQTLError),
        (DatabaseError, SCeQTLError),
        (DatabaseNotFoundError, DatabaseError),
        (ConnectionPoolExhaustedError, DatabaseError),
        (LLMError, SCeQTLError),
        (LLMBudgetExceededError, LLMError),
        (LLMTimeoutError, LLMError),
        (SynthesisError, SCeQTLError),
        (CacheError, SCeQTLError),
        (ExportError, SCeQTLError),
        (UnsupportedFormatError, ExportError),
    ])
    def test_inheritance(self, exc_cls, parent_cls):
        assert issubclass(exc_cls, parent_cls)

    def test_stage_auto_set(self):
        """Stage is automatically set by specific exception classes."""
        assert QueryParsingError().stage == "parsing"
        assert OntologyResolutionError().stage == "ontology"
        assert SQLGenerationError().stage == "sql_generation"
        assert SQLExecutionError().stage == "sql_execution"
        assert FusionError().stage == "fusion"
        assert DatabaseError().stage == "database"
        assert LLMError().stage == "llm"
        assert SynthesisError().stage == "synthesis"
        assert CacheError().stage == "cache"
        assert ExportError().stage == "export"

    def test_ontology_not_found_term(self):
        e = OntologyNotFoundError("liver")
        assert e.term == "liver"
        assert "liver" in str(e)

    def test_all_candidates_failed_errors(self):
        errors = ["timeout on rule", "invalid SQL on template"]
        e = AllCandidatesFailedError(errors=errors)
        assert e.errors == errors
        assert "timeout on rule" in e.detail

    def test_database_not_found_path(self):
        e = DatabaseNotFoundError("/path/to/db")
        assert e.path == "/path/to/db"
        assert "/path/to/db" in str(e)

    def test_llm_timeout_value(self):
        e = LLMTimeoutError(timeout_s=30.0)
        assert e.timeout_s == 30.0
        assert "30.0" in str(e)

    def test_unsupported_format(self):
        e = UnsupportedFormatError("xml")
        assert e.fmt == "xml"
        assert "xml" in str(e)

    def test_catch_by_base(self):
        """All domain exceptions can be caught by SCeQTLError."""
        with pytest.raises(SCeQTLError):
            raise QueryParsingError("test")

        with pytest.raises(SCeQTLError):
            raise DatabaseNotFoundError("/test")

        with pytest.raises(SCeQTLError):
            raise LLMBudgetExceededError()
