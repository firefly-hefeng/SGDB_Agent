"""
Unit Tests — Answer Synthesizer

Tests: summary generation, suggestion generation, chart specs,
quality assessment, provenance construction.
"""
import pytest

from src.core.models import (
    AgentResponse,
    AggregationSpec,
    ChartSpec,
    ExecutionResult,
    FusedRecord,
    ParsedQuery,
    ProvenanceInfo,
    QualityReport,
    QueryFilters,
    QueryIntent,
    Suggestion,
    ValidationResult,
)
from src.synthesis.answer import AnswerSynthesizer


@pytest.fixture
def synthesizer():
    return AnswerSynthesizer(llm=None)


def _make_fused(data: dict, sources: list[str] | None = None) -> FusedRecord:
    """Helper to create FusedRecord."""
    src = sources or [data.get("source_database", "geo")]
    return FusedRecord(
        data=data,
        sources=src,
        source_count=len(set(src)),
        records_merged=len(src),
    )


def _make_exec(rows: list[dict], method: str = "rule") -> ExecutionResult:
    """Helper to create ExecutionResult."""
    return ExecutionResult(
        rows=rows,
        columns=list(rows[0].keys()) if rows else [],
        sql="SELECT * FROM test",
        method=method,
        row_count=len(rows),
        validation=ValidationResult(is_valid=True),
    )


class TestSummaryGeneration:
    """Test _generate_summary_sync and _build_template_summary."""

    def test_zero_results(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver data",
        )
        exec_result = _make_exec([])
        summary = synthesizer._generate_summary_sync(parsed, [], exec_result)
        assert "未找到" in summary
        assert "liver" in summary

    def test_search_results(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"]),
            original_text="find brain data",
        )
        fused = [
            _make_fused({"tissue": "brain"}, ["geo"]),
            _make_fused({"tissue": "brain cortex"}, ["cellxgene"]),
        ]
        exec_result = _make_exec([{}, {}])
        summary = synthesizer._generate_summary_sync(parsed, fused, exec_result)
        assert "2" in summary
        assert "数据库" in summary

    def test_statistics_summary(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.STATISTICS,
            aggregation=AggregationSpec(group_by=["source_database"]),
            original_text="统计",
        )
        fused = [
            _make_fused({"source_database": "geo", "count": 100}, ["geo"]),
            _make_fused({"source_database": "cxg", "count": 50}, ["cellxgene"]),
        ]
        exec_result = _make_exec([{}, {}])
        summary = synthesizer._generate_summary_sync(parsed, fused, exec_result)
        assert "统计" in summary

    def test_dedup_note_in_summary(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver",
        )
        fused = [
            _make_fused({"tissue": "liver"}, ["geo"]),
        ]
        exec_result = _make_exec([{}, {}, {}])  # 3 raw rows → 1 fused
        summary = synthesizer._generate_summary_sync(parsed, fused, exec_result)
        assert "去重" in summary


class TestSuggestionGeneration:
    """Test contextual suggestion generation."""

    def test_no_results_expand(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver",
        )
        suggestions = synthesizer._generate_suggestions(parsed, [])
        assert len(suggestions) >= 1
        assert suggestions[0].type == "expand"

    def test_many_results_refine(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"]),
            original_text="find brain",
        )
        fused = [_make_fused({"tissue": "brain"}, ["geo"]) for _ in range(100)]
        suggestions = synthesizer._generate_suggestions(parsed, fused)
        types = [s.type for s in suggestions]
        assert "refine" in types

    def test_multi_source_compare(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            original_text="find data",
        )
        fused = [
            _make_fused({"tissue": "brain"}, ["geo"]),
            _make_fused({"tissue": "brain"}, ["cellxgene"]),
        ]
        suggestions = synthesizer._generate_suggestions(parsed, fused)
        types = [s.type for s in suggestions]
        assert "compare" in types

    def test_max_4_suggestions(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            original_text="find data",
        )
        fused = [
            _make_fused({"tissue": "brain", "has_h5ad": True}, ["geo", "cellxgene"])
            for _ in range(100)
        ]
        suggestions = synthesizer._generate_suggestions(parsed, fused)
        assert len(suggestions) <= 4


class TestChartGeneration:
    """Test chart spec generation."""

    def test_no_charts_for_empty(self, synthesizer):
        parsed = ParsedQuery(intent=QueryIntent.SEARCH, original_text="test")
        charts = synthesizer._generate_charts(parsed, [])
        assert charts == []

    def test_pie_chart_for_multi_source(self, synthesizer):
        parsed = ParsedQuery(intent=QueryIntent.SEARCH, original_text="find")
        fused = [
            _make_fused({"tissue": "brain"}, ["geo"]),
            _make_fused({"tissue": "liver"}, ["cellxgene"]),
        ]
        charts = synthesizer._generate_charts(parsed, fused)
        assert len(charts) == 1
        assert charts[0].type == "pie"
        assert "geo" in charts[0].data
        assert "cellxgene" in charts[0].data

    def test_bar_chart_for_statistics(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.STATISTICS,
            aggregation=AggregationSpec(group_by=["source_database"]),
            original_text="统计",
        )
        fused = [
            _make_fused({"source_database": "geo", "count": 100}, ["geo"]),
            _make_fused({"source_database": "cxg", "count": 50}, ["cellxgene"]),
        ]
        charts = synthesizer._generate_charts(parsed, fused)
        assert len(charts) == 1
        assert charts[0].type == "bar"


class TestQualityAssessment:
    """Test data quality assessment."""

    def test_empty_results(self, synthesizer):
        quality = synthesizer._assess_quality([])
        assert quality == QualityReport()

    def test_field_completeness(self, synthesizer):
        fused = [
            _make_fused({"tissue": "brain", "disease": "normal", "sex": "M", "assay": "10x"}),
            _make_fused({"tissue": "brain"}),
        ]
        quality = synthesizer._assess_quality(fused)
        assert quality.field_completeness["tissue"] == 100.0
        assert quality.field_completeness["sex"] == 50.0

    def test_cross_validation_score(self, synthesizer):
        fused = [
            FusedRecord(data={}, sources=["geo", "cellxgene"], source_count=2),
            FusedRecord(data={}, sources=["geo"], source_count=1),
        ]
        quality = synthesizer._assess_quality(fused)
        assert quality.cross_validation_score == 50.0


class TestSynthesizeFromExecution:
    """Test the full synchronous synthesis flow."""

    def test_full_response_structure(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver data",
            limit=20,
        )
        fused = [
            _make_fused({"tissue": "liver", "disease": "normal"}, ["geo"]),
            _make_fused({"tissue": "liver"}, ["cellxgene"]),
        ]
        exec_result = _make_exec(
            [{"tissue": "liver"}, {"tissue": "liver"}],
            method="rule",
        )

        response = synthesizer.synthesize_from_execution(
            parsed, fused, exec_result, 150.0,
        )
        assert isinstance(response, AgentResponse)
        assert response.total_count == 2
        assert response.displayed_count == 2
        assert response.summary
        assert response.provenance.sql_method == "rule"
        assert response.provenance.execution_time_ms == 150.0
        assert isinstance(response.quality_report, QualityReport)

    def test_limit_applied(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            original_text="test",
            limit=5,
        )
        fused = [_make_fused({"tissue": "brain"}, ["geo"]) for _ in range(20)]
        exec_result = _make_exec([{}] * 20)

        response = synthesizer.synthesize_from_execution(
            parsed, fused, exec_result, 100.0,
        )
        assert response.total_count == 20
        assert response.displayed_count == 5
        assert len(response.results) == 5

    def test_ontology_expansions_in_provenance(self, synthesizer):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            original_text="test",
        )
        fused = [_make_fused({"tissue": "liver"}, ["geo"])]
        exec_result = _make_exec([{}])
        expansions = [{"original": "liver", "ontology_id": "UBERON:0002107"}]

        response = synthesizer.synthesize_from_execution(
            parsed, fused, exec_result, 100.0,
            ontology_expansions=expansions,
        )
        assert len(response.provenance.ontology_expansions) == 1
