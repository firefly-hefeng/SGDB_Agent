"""
Unit tests for Schema Knowledge system + LLM Parser.

Tests:
- SchemaKnowledge: YAML loading, accessors, synonym resolution, ID matching, prompt formatting
- LLMQueryParser: fast-track ID queries, synonym fallback, LLM parse (mocked)
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

# ── Fixtures ──

MINI_YAML = {
    "version": "1.0",
    "generated_at": "2026-03-19T00:00:00Z",
    "stats": {
        "total_samples": 756579,
        "total_projects": 23123,
        "total_series": 15968,
        "source_databases": [
            {"name": "geo", "sample_count": 342368},
            {"name": "ncbi", "sample_count": 217513},
        ],
    },
    "fields": {
        "tissue": {
            "semantic_type": "tissue",
            "table": "unified_samples",
            "ontology_source": "UBERON",
            "distinct_count": 18147,
            "null_pct": 2.9,
            "top_values": [
                {"value": "blood", "count": 22964},
                {"value": "liver", "count": 13936},
                {"value": "brain", "count": 5343},
            ],
            "known_synonyms": {
                "brain": ["大脑", "脑", "cerebral"],
                "blood": ["血液", "外周血", "PBMC"],
                "liver": ["肝", "肝脏", "hepatic"],
            },
        },
        "disease": {
            "semantic_type": "disease",
            "table": "unified_samples",
            "ontology_source": "MONDO",
            "distinct_count": 5000,
            "null_pct": 10.0,
            "top_values": [
                {"value": "normal", "count": 100000},
                {"value": "cancer", "count": 50000},
            ],
            "known_synonyms": {
                "normal": ["正常", "健康", "control"],
                "cancer": ["癌", "肿瘤", "tumor"],
            },
        },
        "source_database": {
            "semantic_type": "source_database",
            "table": "unified_samples",
            "distinct_count": 7,
            "null_pct": 0.0,
            "top_values": [
                {"value": "geo", "count": 342368},
                {"value": "ncbi", "count": 217513},
            ],
        },
    },
    "tables": {
        "unified_samples": {
            "record_count": 756579,
            "key_columns": ["pk", "sample_id", "tissue", "disease"],
        },
        "unified_projects": {
            "record_count": 23123,
            "key_columns": ["pk", "project_id", "title"],
        },
    },
    "views": {
        "v_sample_with_hierarchy": {
            "description": "Pre-joined samples+series+projects",
            "columns": ["sample_pk", "sample_id", "tissue", "disease"],
            "note": "cell_type NOT available in this view",
            "column_aliases": {"pk": "sample_pk", "source_database": "sample_source"},
        },
    },
    "id_patterns": [
        {"prefix": "GSE", "type": "geo_project", "table": "unified_projects", "field": "project_id"},
        {"prefix": "PRJNA", "type": "sra_project", "table": "unified_projects", "field": "project_id"},
        {"prefix": "GSM", "type": "geo_sample", "table": "unified_samples", "field": "sample_id"},
    ],
    "query_constraints": [
        "Always add LIMIT (default 20, max 200)",
        "Use LIKE '%term%' for text fields",
    ],
    "overrides": {"synonyms": {}, "notes": {}},
}


@pytest.fixture
def yaml_path(tmp_path):
    p = tmp_path / "schema_knowledge.yaml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(MINI_YAML, f, allow_unicode=True, default_flow_style=False)
    return p


@pytest.fixture
def sk(yaml_path):
    from src.knowledge.schema_knowledge import SchemaKnowledge
    return SchemaKnowledge(yaml_path)


# ========== SchemaKnowledge Tests ==========

class TestSchemaKnowledge:

    def test_load_stats(self, sk):
        assert sk.stats["total_samples"] == 756579
        assert sk.stats["total_projects"] == 23123

    def test_fields(self, sk):
        assert "tissue" in sk.fields
        assert "disease" in sk.fields
        assert sk.fields["tissue"]["distinct_count"] == 18147

    def test_get_field(self, sk):
        f = sk.get_field("tissue")
        assert f is not None
        assert f["null_pct"] == 2.9
        assert sk.get_field("nonexistent") is None

    def test_get_top_values(self, sk):
        top = sk.get_top_values("tissue", n=2)
        assert len(top) == 2
        assert top[0]["value"] == "blood"
        assert top[0]["count"] == 22964

    def test_get_top_values_empty(self, sk):
        assert sk.get_top_values("nonexistent") == []

    def test_get_synonyms(self, sk):
        syns = sk.get_synonyms("tissue")
        assert "brain" in syns
        assert "大脑" in syns["brain"]

    def test_resolve_synonym_chinese(self, sk):
        assert sk.resolve_synonym("tissue", "大脑") == "brain"
        assert sk.resolve_synonym("tissue", "脑") == "brain"
        assert sk.resolve_synonym("tissue", "肝脏") == "liver"

    def test_resolve_synonym_english(self, sk):
        assert sk.resolve_synonym("tissue", "cerebral") == "brain"
        assert sk.resolve_synonym("tissue", "PBMC") == "blood"

    def test_resolve_synonym_canonical(self, sk):
        assert sk.resolve_synonym("tissue", "brain") == "brain"
        assert sk.resolve_synonym("tissue", "Blood") == "blood"

    def test_resolve_synonym_no_match(self, sk):
        assert sk.resolve_synonym("tissue", "xyzzy") is None

    def test_resolve_synonym_disease(self, sk):
        assert sk.resolve_synonym("disease", "正常") == "normal"
        assert sk.resolve_synonym("disease", "癌") == "cancer"
        assert sk.resolve_synonym("disease", "tumor") == "cancer"

    def test_match_id_pattern(self, sk):
        m = sk.match_id_pattern("GSE12345")
        assert m is not None
        assert m["type"] == "geo_project"
        assert m["table"] == "unified_projects"

    def test_match_id_pattern_prjna(self, sk):
        m = sk.match_id_pattern("PRJNA123456")
        assert m is not None
        assert m["prefix"] == "PRJNA"

    def test_match_id_pattern_doi(self, sk):
        m = sk.match_id_pattern("10.1038/s41586-023-06802-1")
        assert m is not None
        assert m["type"] == "doi"

    def test_match_id_pattern_no_match(self, sk):
        assert sk.match_id_pattern("hello world") is None

    def test_format_for_parse_prompt(self, sk):
        prompt = sk.format_for_parse_prompt()
        assert "756,579 samples" in prompt
        assert "tissue" in prompt
        assert "brain" in prompt
        assert len(prompt) > 200

    def test_format_for_validation(self, sk):
        ctx = sk.format_for_validation({"tissues": ["brain"]})
        assert "tissue" in ctx
        assert "blood" in ctx  # top values shown

    def test_format_for_recovery(self, sk):
        ctx = sk.format_for_recovery({"tissues": ["hippocampus"]})
        assert "tissue" in ctx
        assert "hippocampus" in ctx

    def test_format_for_sql_generation(self, sk):
        ctx = sk.format_for_sql_generation()
        assert "unified_samples" in ctx
        assert "LIMIT" in ctx
        assert "v_sample_with_hierarchy" in ctx

    def test_format_for_suggestions(self, sk):
        ctx = sk.format_for_suggestions()
        assert "756,579" in ctx
        assert "tissue" in ctx

    def test_tables(self, sk):
        assert "unified_samples" in sk.tables
        assert sk.tables["unified_samples"]["record_count"] == 756579

    def test_views(self, sk):
        assert "v_sample_with_hierarchy" in sk.views
        assert "cell_type" in sk.views["v_sample_with_hierarchy"]["note"].lower()

    def test_file_not_found(self, tmp_path):
        from src.knowledge.schema_knowledge import SchemaKnowledge
        with pytest.raises(FileNotFoundError):
            SchemaKnowledge(tmp_path / "nonexistent.yaml")


# ========== LLMQueryParser Tests ==========

def _make_mock_llm(response_content: str):
    """Create a mock LLM client that returns the given content."""
    mock = AsyncMock()
    mock.chat = AsyncMock(return_value=MagicMock(content=response_content))
    mock.model_id = "mock-model"
    mock.supports_tool_use = False
    mock.estimate_tokens = MagicMock(return_value=100)
    return mock


class TestLLMQueryParser:

    def _make_parser(self, yaml_path, llm_response=None):
        from src.knowledge.schema_knowledge import SchemaKnowledge
        from src.understanding.llm_parser import LLMQueryParser
        sk = SchemaKnowledge(yaml_path)
        llm = _make_mock_llm(llm_response or "{}")
        return LLMQueryParser(llm=llm, schema_knowledge=sk)

    def test_pure_id_query_fast_track(self, yaml_path):
        parser = self._make_parser(yaml_path)
        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("GSE12345")
        )
        assert result.parse_method == "rule"
        assert result.confidence == 0.95
        assert result.filters.project_ids == ["GSE12345"]
        # LLM should NOT have been called
        parser.llm.chat.assert_not_called()

    def test_pure_id_query_multiple(self, yaml_path):
        parser = self._make_parser(yaml_path)
        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("GSE12345 GSE67890")
        )
        assert result.parse_method == "rule"
        assert len(result.filters.project_ids) == 2

    def test_id_with_text_uses_llm(self, yaml_path):
        llm_response = json.dumps({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [{"text": "GSE12345", "type": "id", "value": "GSE12345"}],
            "filters": {"project_ids": ["GSE12345"], "tissues": ["brain"]},
            "confidence": 0.9,
        })
        parser = self._make_parser(yaml_path, llm_response)
        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("GSE12345 brain tissue data")
        )
        assert result.parse_method == "llm"
        parser.llm.chat.assert_called()

    def test_llm_parse_chinese(self, yaml_path):
        llm_response = json.dumps({
            "intent": "SEARCH",
            "target_level": "sample",
            "entities": [
                {"text": "脑", "type": "tissue", "value": "brain"},
                {"text": "10x", "type": "assay", "value": "10x 3' v3"},
            ],
            "filters": {"tissues": ["brain"], "assays": ["10x 3' v3"]},
            "confidence": 0.95,
        })
        parser = self._make_parser(yaml_path, llm_response)
        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("脑组织10x数据")
        )
        assert result.intent.name == "SEARCH"
        assert result.filters.tissues == ["brain"]
        assert result.language == "zh"

    def test_llm_parse_statistics(self, yaml_path):
        llm_response = json.dumps({
            "intent": "STATISTICS",
            "target_level": "sample",
            "entities": [],
            "filters": {},
            "aggregation": {"group_by": ["source_database"], "metric": "count"},
            "confidence": 0.9,
        })
        parser = self._make_parser(yaml_path, llm_response)
        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("各数据库有多少数据")
        )
        assert result.intent.name == "STATISTICS"
        assert result.aggregation is not None
        assert result.aggregation.group_by == ["source_database"]

    def test_llm_failure_falls_back_to_synonyms(self, yaml_path):
        from src.knowledge.schema_knowledge import SchemaKnowledge
        from src.understanding.llm_parser import LLMQueryParser
        sk = SchemaKnowledge(yaml_path)
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("LLM timeout"))
        llm.model_id = "mock"
        llm.supports_tool_use = False
        llm.estimate_tokens = MagicMock(return_value=100)
        parser = LLMQueryParser(llm=llm, schema_knowledge=sk)

        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("大脑正常组织")
        )
        assert result.parse_method == "synonym_fallback"
        assert "brain" in result.filters.tissues
        assert "normal" in result.filters.diseases

    def test_synonym_fallback_no_match(self, yaml_path):
        from src.knowledge.schema_knowledge import SchemaKnowledge
        from src.understanding.llm_parser import LLMQueryParser
        sk = SchemaKnowledge(yaml_path)
        llm = AsyncMock()
        llm.chat = AsyncMock(side_effect=Exception("fail"))
        llm.model_id = "mock"
        llm.supports_tool_use = False
        llm.estimate_tokens = MagicMock(return_value=100)
        parser = LLMQueryParser(llm=llm, schema_knowledge=sk)

        result = asyncio.get_event_loop().run_until_complete(
            parser.parse("xyzzy unknown query")
        )
        assert result.parse_method == "synonym_fallback"
        assert result.confidence == 0.3
        assert result.filters.free_text == "xyzzy unknown query"

    def test_zero_result_recovery(self, yaml_path):
        recovery_response = json.dumps({
            "diagnosis": "hippocampus too specific",
            "strategy": "relax_value",
            "relaxed_filters": {"tissues": ["brain"]},
            "explanation": "Broadened hippocampus to brain",
            "alternatives": [],
        })
        parser = self._make_parser(yaml_path, recovery_response)
        from src.core.models import ParsedQuery, QueryIntent, QueryFilters
        parsed = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["hippocampus"]),
            original_text="hippocampus data",
        )
        result = asyncio.get_event_loop().run_until_complete(
            parser.recover_zero_result(parsed, "SELECT ... WHERE tissue LIKE '%hippocampus%'")
        )
        assert result is not None
        assert result.filters.tissues == ["brain"]
        assert result.parse_method == "llm_recovery"

    def test_generate_suggestions(self, yaml_path):
        suggestion_response = json.dumps({
            "suggestions": [
                {"type": "refine", "text": "按疾病筛选", "action_query": "brain cancer", "reason": "too many results"},
                {"type": "compare", "text": "比较各数据库", "action_query": "brain 统计", "reason": "multi-source"},
            ]
        })
        parser = self._make_parser(yaml_path, suggestion_response)
        from src.core.models import ParsedQuery, QueryIntent
        parsed = ParsedQuery(intent=QueryIntent.SEARCH, original_text="brain data")
        result = asyncio.get_event_loop().run_until_complete(
            parser.generate_suggestions(parsed, 150, "Found 150 brain datasets")
        )
        assert len(result) == 2
        assert result[0].type == "refine"
        assert result[1].type == "compare"
