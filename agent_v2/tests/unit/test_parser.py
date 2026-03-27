"""
Unit Tests — Query Parser

Tests rule-based query understanding: intent classification, entity extraction,
ID detection, multi-turn context, aggregation detection.
"""
import pytest

from src.core.models import (
    BioEntity,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    SessionContext,
)
from src.understanding.parser import QueryParser


@pytest.fixture
def parser():
    """Parser without LLM (pure rule mode)."""
    return QueryParser(llm=None, schema_context={})


class TestIntentClassification:
    """Test intent detection from keywords."""

    @pytest.mark.asyncio
    async def test_search_intent_chinese(self, parser):
        result = await parser.parse("查找肝脏的数据集")
        assert result.intent == QueryIntent.SEARCH

    @pytest.mark.asyncio
    async def test_search_intent_english(self, parser):
        result = await parser.parse("find brain datasets")
        assert result.intent == QueryIntent.SEARCH

    @pytest.mark.asyncio
    async def test_statistics_intent(self, parser):
        result = await parser.parse("统计各数据库的样本数量")
        assert result.intent == QueryIntent.STATISTICS

    @pytest.mark.asyncio
    async def test_compare_intent(self, parser):
        result = await parser.parse("比较肝脏和肺部数据")
        assert result.intent == QueryIntent.COMPARE

    @pytest.mark.asyncio
    async def test_explore_intent(self, parser):
        result = await parser.parse("explore available datasets")
        assert result.intent == QueryIntent.EXPLORE

    @pytest.mark.asyncio
    async def test_download_intent(self, parser):
        result = await parser.parse("download h5ad files for brain")
        assert result.intent == QueryIntent.DOWNLOAD


class TestEntityExtraction:
    """Test biological entity extraction."""

    @pytest.mark.asyncio
    async def test_tissue_chinese(self, parser):
        result = await parser.parse("查找大脑的数据集")
        tissues = [e for e in result.entities if e.entity_type == "tissue"]
        assert len(tissues) >= 1
        assert any("brain" in (e.normalized_value or "").lower() for e in tissues)

    @pytest.mark.asyncio
    async def test_tissue_english(self, parser):
        result = await parser.parse("find liver datasets")
        tissues = [e for e in result.entities if e.entity_type == "tissue"]
        assert len(tissues) >= 1

    @pytest.mark.asyncio
    async def test_disease_extraction(self, parser):
        result = await parser.parse("find cancer related datasets")
        diseases = [e for e in result.entities if e.entity_type == "disease"]
        assert len(diseases) >= 1

    @pytest.mark.asyncio
    async def test_multi_entity(self, parser):
        result = await parser.parse("find brain cancer datasets")
        types = {e.entity_type for e in result.entities}
        assert "tissue" in types or "disease" in types

    @pytest.mark.asyncio
    async def test_source_database(self, parser):
        result = await parser.parse("search cellxgene for brain data")
        assert "cellxgene" in result.filters.source_databases or any(
            e.entity_type == "source_database" for e in result.entities
        )


class TestIDDetection:
    """Test ID pattern recognition."""

    @pytest.mark.asyncio
    async def test_geo_project_id(self, parser):
        result = await parser.parse("GSE149614")
        assert result.filters.project_ids == ["GSE149614"]
        assert result.intent == QueryIntent.SEARCH

    @pytest.mark.asyncio
    async def test_sra_project_id(self, parser):
        result = await parser.parse("PRJNA12345")
        assert "PRJNA12345" in result.filters.project_ids

    @pytest.mark.asyncio
    async def test_pmid(self, parser):
        result = await parser.parse("PMID:12345678")
        assert len(result.filters.pmids) >= 1

    @pytest.mark.asyncio
    async def test_doi(self, parser):
        result = await parser.parse("10.1038/s41586-021-03570-8")
        assert len(result.filters.dois) >= 1

    @pytest.mark.asyncio
    async def test_multiple_ids(self, parser):
        result = await parser.parse("GSE149614 GSE123456")
        assert len(result.filters.project_ids) >= 2


class TestFilterExtraction:
    """Test structured filter extraction."""

    @pytest.mark.asyncio
    async def test_tissue_filter(self, parser):
        result = await parser.parse("find liver datasets")
        assert len(result.filters.tissues) >= 1

    @pytest.mark.asyncio
    async def test_disease_filter(self, parser):
        result = await parser.parse("查找阿尔茨海默病数据")
        assert len(result.filters.diseases) >= 1

    @pytest.mark.asyncio
    async def test_target_level_default(self, parser):
        result = await parser.parse("find brain data")
        assert result.target_level == "sample"


class TestAggregation:
    """Test aggregation detection for statistics queries."""

    @pytest.mark.asyncio
    async def test_group_by_source(self, parser):
        result = await parser.parse("统计各数据库的样本数量")
        assert result.intent == QueryIntent.STATISTICS
        assert result.aggregation is not None

    @pytest.mark.asyncio
    async def test_distribution_query(self, parser):
        result = await parser.parse("show tissue distribution")
        assert result.intent == QueryIntent.STATISTICS


class TestParseMetadata:
    """Test parse method and confidence."""

    @pytest.mark.asyncio
    async def test_rule_method(self, parser):
        result = await parser.parse("find liver data")
        assert result.parse_method == "rule"

    @pytest.mark.asyncio
    async def test_original_text_preserved(self, parser):
        query = "find brain cancer datasets"
        result = await parser.parse(query)
        assert result.original_text == query

    @pytest.mark.asyncio
    async def test_confidence_positive(self, parser):
        result = await parser.parse("find liver data")
        assert result.confidence > 0


class TestMultiTurn:
    """Test context-aware multi-turn parsing."""

    @pytest.mark.asyncio
    async def test_context_refinement(self, parser):
        """Second query should inherit context from first."""
        ctx = SessionContext(session_id="test")
        r1 = await parser.parse("查找大脑数据", ctx)
        assert r1.filters.tissues

        # Update context
        ctx.active_filters = r1.filters
        ctx.last_result_count = 100
        ctx.turns.append({"input": "查找大脑数据", "intent": "SEARCH", "result_count": 100})

        r2 = await parser.parse("这些中有哪些是癌症的", ctx)
        # Should retain tissue from context and add disease
        assert r2.filters.diseases or r2.filters.tissues
