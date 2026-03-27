"""
Unit Tests — Coordinator Agent (DI)

Tests: factory creation, pipeline execution, error handling,
memory updates, Protocol-based DI.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.models import (
    AgentResponse,
    ExecutionResult,
    FusedRecord,
    ParsedQuery,
    QueryFilters,
    QueryIntent,
    SQLCandidate,
    ValidationResult,
)
from src.agent.coordinator import CoordinatorAgent
from src.synthesis.answer import AnswerSynthesizer


def _mock_parser(intent=QueryIntent.SEARCH, tissues=None):
    """Create a mock parser that returns a canned ParsedQuery."""
    parser = AsyncMock()
    parsed = ParsedQuery(
        intent=intent,
        filters=QueryFilters(tissues=tissues or []),
        original_text="test query",
        confidence=0.9,
        parse_method="rule",
    )
    parser.parse.return_value = parsed
    return parser


def _mock_sql_gen():
    """Create a mock SQL generator."""
    gen = AsyncMock()
    gen.generate.return_value = [
        SQLCandidate(sql="SELECT 1", params=[], method="rule"),
    ]
    return gen


def _mock_sql_exec(rows=None):
    """Create a mock SQL executor."""
    if rows is None:
        rows = [{"pk": 1, "tissue": "liver", "source_database": "geo"}]
    exec_mock = AsyncMock()
    exec_mock.execute.return_value = ExecutionResult(
        rows=rows,
        columns=list(rows[0].keys()) if rows else [],
        sql="SELECT 1",
        method="rule",
        row_count=len(rows),
        validation=ValidationResult(is_valid=True),
    )
    return exec_mock


def _mock_fusion(fused=None):
    """Create a mock fusion engine."""
    if fused is None:
        fused = [
            FusedRecord(
                data={"pk": 1, "tissue": "liver", "source_database": "geo"},
                sources=["geo"],
                source_count=1,
            ),
        ]
    fusion = MagicMock()
    fusion.fuse.return_value = fused
    return fusion


class TestCoordinatorDI:
    """Test Protocol-based dependency injection."""

    def test_di_construction(self):
        """Coordinator can be constructed with injected dependencies."""
        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
        )
        assert agent.parser is not None
        assert agent.synthesizer is not None

    def test_no_ontology_by_default(self):
        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
        )
        assert agent.ontology is None
        assert agent.episodic is None
        assert agent.semantic is None


class TestCoordinatorPipeline:
    """Test the query pipeline execution."""

    @pytest.mark.asyncio
    async def test_basic_query(self):
        """Full pipeline executes and returns AgentResponse."""
        agent = CoordinatorAgent(
            parser=_mock_parser(tissues=["liver"]),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
        )

        response = await agent.query("find liver data")
        assert isinstance(response, AgentResponse)
        assert response.total_count >= 1
        assert response.provenance.sql_method == "rule"
        assert response.error is None

    @pytest.mark.asyncio
    async def test_pipeline_calls_all_stages(self):
        """Verify each stage is called in order."""
        parser = _mock_parser()
        sql_gen = _mock_sql_gen()
        sql_exec = _mock_sql_exec()
        fusion = _mock_fusion()

        agent = CoordinatorAgent(
            parser=parser,
            sql_gen=sql_gen,
            sql_exec=sql_exec,
            fusion=fusion,
            synthesizer=AnswerSynthesizer(),
        )

        await agent.query("test")

        parser.parse.assert_called_once()
        sql_gen.generate.assert_called_once()
        sql_exec.execute.assert_called_once()
        fusion.fuse.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_returns_response_not_exception(self):
        """Pipeline errors return AgentResponse with error field, not raise."""
        parser = AsyncMock()
        parser.parse.side_effect = RuntimeError("parse failed")

        agent = CoordinatorAgent(
            parser=parser,
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
        )

        response = await agent.query("broken query")
        assert response.error is not None
        assert "parse failed" in response.error

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Pipeline handles zero results gracefully."""
        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(rows=[]),
            fusion=_mock_fusion(fused=[]),
            synthesizer=AnswerSynthesizer(),
        )

        response = await agent.query("find nonexistent data")
        assert response.total_count == 0
        assert "未找到" in response.summary


class TestCoordinatorMemory:
    """Test memory integration."""

    @pytest.mark.asyncio
    async def test_session_context_updated(self):
        """Session context is updated after query."""
        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
        )

        await agent.query("test", session_id="s1")
        assert "s1" in agent._sessions
        assert len(agent._sessions["s1"].turns) == 1

    @pytest.mark.asyncio
    async def test_episodic_memory_called(self):
        """Episodic memory is updated when available."""
        episodic = MagicMock()

        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
            episodic=episodic,
        )

        await agent.query("test", user_id="user1")
        episodic.record_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_memory_called(self):
        """Semantic memory records successful queries."""
        semantic = MagicMock()

        agent = CoordinatorAgent(
            parser=_mock_parser(),
            sql_gen=_mock_sql_gen(),
            sql_exec=_mock_sql_exec(),
            fusion=_mock_fusion(),
            synthesizer=AnswerSynthesizer(),
            semantic=semantic,
        )

        await agent.query("test")
        semantic.record_successful_query.assert_called_once()


class TestCoordinatorPatternGeneralization:
    """Test _generalize_pattern static method."""

    def test_search_tissue(self):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
        )
        pattern = CoordinatorAgent._generalize_pattern(parsed)
        assert "SEARCH" in pattern
        assert "tissue_filter" in pattern

    def test_statistics_group(self):
        from src.core.models import AggregationSpec
        parsed = ParsedQuery(
            intent=QueryIntent.STATISTICS,
            aggregation=AggregationSpec(group_by=["source_database"]),
        )
        pattern = CoordinatorAgent._generalize_pattern(parsed)
        assert "STATISTICS" in pattern
        assert "group_by_source_database" in pattern

    def test_multi_filter(self):
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"], diseases=["cancer"]),
        )
        pattern = CoordinatorAgent._generalize_pattern(parsed)
        assert "tissue_filter" in pattern
        assert "disease_filter" in pattern
