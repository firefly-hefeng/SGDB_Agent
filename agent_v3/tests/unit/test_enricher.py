"""Tests for LLM-driven QueryEnricher."""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from src.understanding.enricher import QueryEnricher
from src.core.models import (
    BioEntity,
    ParsedQuery,
    QueryFilters,
    QueryIntent,
)


# ── Mock LLM Client ──

@dataclass
class MockLLMResponse:
    content: str


def make_mock_llm(response_dict: dict) -> AsyncMock:
    """Create a mock LLM client that returns the given dict as JSON."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=MockLLMResponse(
        content=json.dumps(response_dict, ensure_ascii=False),
    ))
    return llm


# ── Test Fixtures ──

@pytest.fixture
def empty_parsed():
    """A ParsedQuery with no entities/filters (e.g., rule parser extracted nothing)."""
    return ParsedQuery(
        intent=QueryIntent.SEARCH,
        filters=QueryFilters(),
        target_level="sample",
        original_text="所有人源单细胞数据",
        language="zh",
        confidence=0.5,
        parse_method="fallback",
    )


@pytest.fixture
def llm_parsed():
    """A ParsedQuery already parsed by LLM (should NOT be re-enriched)."""
    return ParsedQuery(
        intent=QueryIntent.SEARCH,
        filters=QueryFilters(organisms=["Homo sapiens"]),
        target_level="sample",
        original_text="所有人源单细胞数据",
        language="zh",
        confidence=0.9,
        parse_method="llm",
    )


@pytest.fixture
def id_parsed():
    """A high-confidence ID query (should NOT be enriched)."""
    return ParsedQuery(
        intent=QueryIntent.SEARCH,
        filters=QueryFilters(project_ids=["GSE12345"]),
        entities=[BioEntity(text="GSE12345", entity_type="id", normalized_value="GSE12345")],
        target_level="project",
        original_text="GSE12345",
        language="en",
        confidence=0.95,
        parse_method="rule",
    )


# ── Tests ──

class TestQueryEnricher:
    """Test the LLM-driven QueryEnricher."""

    @pytest.mark.asyncio
    async def test_enrich_human_query(self, empty_parsed):
        """'所有人源单细胞数据' should extract organism=Homo sapiens."""
        llm = make_mock_llm({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [
                {"text": "人源", "type": "organism", "value": "Homo sapiens"},
            ],
            "filters": {
                "organisms": ["Homo sapiens"],
            },
            "confidence": 0.92,
            "reasoning": "'人源' means human, '单细胞' is redundant in this DB",
        })

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(empty_parsed)

        assert result.parse_method == "enriched"
        assert result.filters.organisms == ["Homo sapiens"]
        assert result.confidence > empty_parsed.confidence
        llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_llm_parsed(self, llm_parsed):
        """Queries already parsed by LLM should NOT be re-enriched."""
        llm = make_mock_llm({})
        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(llm_parsed)

        assert result.parse_method == "llm"  # unchanged
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_id_query(self, id_parsed):
        """High-confidence ID queries should NOT be enriched."""
        llm = make_mock_llm({})
        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(id_parsed)

        assert result.filters.project_ids == ["GSE12345"]
        llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_llm_returns_original(self, empty_parsed):
        """Without LLM, enricher returns the original ParsedQuery unchanged."""
        enricher = QueryEnricher(llm=None)
        result = await enricher.enrich(empty_parsed)
        assert result is empty_parsed

    @pytest.mark.asyncio
    async def test_enrich_topic_expansion(self):
        """Chinese topic keywords should be expanded to English free_text."""
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(),
            original_text="免疫相关数据",
            language="zh",
            confidence=0.5,
            parse_method="rule",
        )
        llm = make_mock_llm({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [],
            "filters": {
                "free_text": "immune immunology immunotherapy T cell B cell",
            },
            "confidence": 0.85,
            "reasoning": "'免疫' expands to immune-related English search terms",
        })

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(parsed)

        assert result.filters.free_text is not None
        assert "immune" in result.filters.free_text.lower()

    @pytest.mark.asyncio
    async def test_enrich_multi_condition(self):
        """Complex query with multiple conditions."""
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"]),
            entities=[BioEntity(text="脑", entity_type="tissue", normalized_value="brain")],
            original_text="人类脑组织10x单细胞数据",
            language="zh",
            confidence=0.65,
            parse_method="rule",
        )
        llm = make_mock_llm({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [
                {"text": "人类", "type": "organism", "value": "Homo sapiens"},
                {"text": "脑组织", "type": "tissue", "value": "brain"},
                {"text": "10x", "type": "assay", "value": "10x 3' v3"},
            ],
            "filters": {
                "organisms": ["Homo sapiens"],
                "tissues": ["brain"],
                "assays": ["10x 3' v3"],
            },
            "confidence": 0.9,
            "reasoning": "Multiple conditions extracted: human + brain + 10x assay",
        })

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(parsed)

        assert result.filters.organisms == ["Homo sapiens"]
        assert result.filters.tissues == ["brain"]
        assert result.filters.assays == ["10x 3' v3"]

    @pytest.mark.asyncio
    async def test_enrich_preserves_ids(self):
        """Enrichment should preserve IDs from original parse."""
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(pmids=["12345678"]),
            original_text="PMID 12345678 的人类数据",
            language="zh",
            confidence=0.7,
            parse_method="rule",
        )
        llm = make_mock_llm({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [
                {"text": "人类", "type": "organism", "value": "Homo sapiens"},
            ],
            "filters": {
                "organisms": ["Homo sapiens"],
                "pmids": ["12345678"],
            },
            "confidence": 0.9,
        })

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(parsed)

        assert result.filters.organisms == ["Homo sapiens"]
        assert result.filters.pmids == ["12345678"]

    @pytest.mark.asyncio
    async def test_enrich_llm_failure_returns_original(self, empty_parsed):
        """If LLM call fails, return the original ParsedQuery."""
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM API error"))

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(empty_parsed)

        assert result is empty_parsed
        assert result.parse_method == "fallback"

    @pytest.mark.asyncio
    async def test_enrich_statistics_query(self):
        """Statistics queries should be enriched with aggregation."""
        parsed = ParsedQuery(
            intent=QueryIntent.STATISTICS,
            filters=QueryFilters(),
            original_text="各组织的数据分布",
            language="zh",
            confidence=0.6,
            parse_method="rule",
        )
        llm = make_mock_llm({
            "intent": "STATISTICS",
            "target_level": "sample",
            "entities": [],
            "filters": {},
            "aggregation": {"group_by": ["tissue"], "metric": "count"},
            "confidence": 0.9,
        })

        enricher = QueryEnricher(llm=llm)
        result = await enricher.enrich(parsed)

        assert result.intent == QueryIntent.STATISTICS
        assert result.aggregation is not None
        assert result.aggregation.group_by == ["tissue"]
