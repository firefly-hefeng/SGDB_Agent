"""
Unit Tests — SQL Generator & Executor

Tests SQL candidate generation, view column mapping, join resolution,
template/rule methods, and parallel execution logic.
"""
import pytest

from src.core.models import (
    AggregationSpec,
    BioEntity,
    DBValueMatch,
    ExecutionResult,
    OntologyTerm,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    ResolvedEntity,
    SQLCandidate,
    ValidationResult,
)
from src.sql.engine import (
    JoinPathResolver,
    SQLGenerator,
    ParallelSQLExecutor,
    VIEW_COLUMN_MAP,
    VIEW_FIELDS,
    _vc,
)


class TestViewColumnMapping:
    """Test _vc() view column name mapping."""

    def test_pk_maps_to_sample_pk(self):
        assert _vc("pk", True) == "sample_pk"

    def test_source_database_maps(self):
        assert _vc("source_database", True) == "sample_source"

    def test_title_maps_to_project_title(self):
        assert _vc("title", True) == "project_title"

    def test_unmapped_field_unchanged(self):
        assert _vc("tissue", True) == "tissue"

    def test_no_mapping_when_not_view(self):
        assert _vc("pk", False) == "pk"
        assert _vc("source_database", False) == "source_database"


class TestJoinPathResolver:
    """Test automatic JOIN path resolution."""

    def test_view_used_for_sample_queries(self):
        resolver = JoinPathResolver()
        plan = resolver.resolve(["tissue", "disease"], "unified_samples")
        assert plan.use_view is True
        assert plan.base_table == "v_sample_with_hierarchy"

    def test_no_join_for_single_table(self):
        resolver = JoinPathResolver()
        plan = resolver.resolve(["tissue"], "unified_samples")
        assert plan.use_view is True

    def test_empty_fields_use_view(self):
        resolver = JoinPathResolver()
        plan = resolver.resolve([], "unified_samples")
        assert plan.use_view is True

    def test_project_table_direct(self):
        resolver = JoinPathResolver()
        plan = resolver.resolve(["project_id"], "unified_projects")
        assert plan.base_table == "unified_projects"
        assert plan.use_view is False


class TestSQLGeneratorTemplates:
    """Test template SQL generation paths."""

    @pytest.fixture
    def mock_dal(self, mocker):
        dal = mocker.MagicMock()
        dal.get_schema_summary.return_value = {"tables": {}, "views": []}
        dal.schema_inspector.get_ddl_summary.return_value = "-- schema"
        return dal

    @pytest.fixture
    def gen(self, mock_dal):
        return SQLGenerator(dal=mock_dal, llm=None)

    @pytest.mark.asyncio
    async def test_id_query_uses_template(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(project_ids=["GSE149614"]),
            original_text="GSE149614",
        )
        candidates = await gen.generate(query)
        assert any(c.method == "template" for c in candidates)
        template_sql = next(c for c in candidates if c.method == "template")
        assert "GSE149614" in template_sql.params

    @pytest.mark.asyncio
    async def test_pmid_query_uses_template(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(pmids=["12345678"]),
            original_text="PMID:12345678",
        )
        candidates = await gen.generate(query)
        assert any(c.method == "template" for c in candidates)

    @pytest.mark.asyncio
    async def test_statistics_template(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.STATISTICS,
            aggregation=AggregationSpec(group_by=["source_database"]),
            original_text="统计各数据库",
        )
        candidates = await gen.generate(query)
        assert any(c.method == "template" for c in candidates)
        template = next(c for c in candidates if c.method == "template")
        assert "GROUP BY" in template.sql
        assert "COUNT" in template.sql

    @pytest.mark.asyncio
    async def test_rule_candidate_always_generated(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver data",
        )
        candidates = await gen.generate(query)
        assert any(c.method == "rule" for c in candidates)


class TestSQLGeneratorRules:
    """Test rule-based SQL generation."""

    @pytest.fixture
    def mock_dal(self, mocker):
        dal = mocker.MagicMock()
        dal.get_schema_summary.return_value = {"tables": {}, "views": []}
        return dal

    @pytest.fixture
    def gen(self, mock_dal):
        return SQLGenerator(dal=mock_dal, llm=None)

    @pytest.mark.asyncio
    async def test_tissue_filter_in_where(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver",
        )
        candidates = await gen.generate(query)
        rule = next(c for c in candidates if c.method == "rule")
        assert "LIKE" in rule.sql
        assert "%liver%" in rule.params

    @pytest.mark.asyncio
    async def test_multi_condition_where(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"], diseases=["cancer"]),
            original_text="find brain cancer",
        )
        candidates = await gen.generate(query)
        rule = next(c for c in candidates if c.method == "rule")
        assert "LIKE" in rule.sql
        assert len(rule.params) >= 2

    @pytest.mark.asyncio
    async def test_ontology_expansion_in_rule(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["liver"]),
            original_text="find liver",
        )
        resolved = [
            ResolvedEntity(
                original=BioEntity(text="liver", entity_type="tissue", normalized_value="liver"),
                ontology_term=OntologyTerm(
                    ontology_id="UBERON:0002107", ontology_source="UBERON", label="liver"
                ),
                db_values=[
                    DBValueMatch(raw_value="liver"),
                    DBValueMatch(raw_value="hepatic tissue"),
                    DBValueMatch(raw_value="liver parenchyma"),
                ],
            )
        ]
        candidates = await gen.generate(query, resolved)
        rule = next(c for c in candidates if c.method == "rule")
        # Should use IN clause with expanded values
        assert "IN" in rule.sql
        assert "liver" in rule.params
        assert "hepatic tissue" in rule.params

    @pytest.mark.asyncio
    async def test_limit_always_present(self, gen):
        query = ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(tissues=["brain"]),
            original_text="find brain",
            limit=50,
        )
        candidates = await gen.generate(query)
        for c in candidates:
            assert "LIMIT" in c.sql


class TestParallelSQLExecutor:
    """Test parallel execution logic."""

    @pytest.fixture
    def mock_dal(self, mocker):
        dal = mocker.MagicMock()
        return dal

    @pytest.fixture
    def executor(self, mock_dal):
        return ParallelSQLExecutor(dal=mock_dal)

    @pytest.mark.asyncio
    async def test_empty_candidates(self, executor):
        result = await executor.execute([])
        assert not result.validation.is_valid
        assert result.validation.issue == "all_candidates_failed"

    @pytest.mark.asyncio
    async def test_first_valid_wins(self, executor, mock_dal):
        from src.core.models import QueryResult

        mock_dal.execute.return_value = QueryResult(
            rows=[{"pk": 1, "tissue": "liver"}],
            columns=["pk", "tissue"],
            total_count=1,
            returned_count=1,
        )
        candidates = [
            SQLCandidate(sql="SELECT 1", params=[], method="rule"),
            SQLCandidate(sql="SELECT 2", params=[], method="template"),
        ]
        result = await executor.execute(candidates)
        assert result.validation.is_valid
        assert result.row_count == 1
