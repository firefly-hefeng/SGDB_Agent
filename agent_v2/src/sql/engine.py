"""
SQL Generation & Parallel Execution

- JoinPathResolver: 自动推导JOIN路径
- SQLGenerator: 3候选生成 (模板 + 规则 + LLM)
- ParallelSQLExecutor: 并行执行 + 渐进降级
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..core.models import (
    AggregationSpec,
    ExecutionResult,
    JoinClause,
    JoinPlan,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    ResolvedEntity,
    SQLCandidate,
    ValidationResult,
)
from ..core.interfaces import ILLMClient
from ..dal.database import DatabaseAbstractionLayer

logger = logging.getLogger(__name__)


# ========== 视图列名映射 ==========
# v_sample_with_hierarchy 中部分列名与原表不同
VIEW_COLUMN_MAP: dict[str, str] = {
    "pk": "sample_pk",
    "source_database": "sample_source",
    "title": "project_title",
}


def _vc(field: str, use_view: bool) -> str:
    """将字段名映射为视图兼容的列名"""
    if use_view:
        return VIEW_COLUMN_MAP.get(field, field)
    return field


# ========== 字段→表映射 ==========

FIELD_TABLE: dict[str, str] = {
    # Projects
    "project_id": "unified_projects", "pmid": "unified_projects",
    "doi": "unified_projects", "citation_count": "unified_projects",
    "journal": "unified_projects", "project_title": "unified_projects",
    "submitter_organization": "unified_projects",
    # Series
    "series_id": "unified_series", "assay": "unified_series",
    "has_h5ad": "unified_series", "has_rds": "unified_series",
    "cell_count": "unified_series", "gene_count": "unified_series",
    "asset_h5ad_url": "unified_series", "explorer_url": "unified_series",
    # Samples
    "sample_id": "unified_samples", "tissue": "unified_samples",
    "disease": "unified_samples", "cell_type": "unified_samples",
    "sex": "unified_samples", "age": "unified_samples",
    "organism": "unified_samples", "ethnicity": "unified_samples",
    "development_stage": "unified_samples", "n_cells": "unified_samples",
    "individual_id": "unified_samples", "source_database": "unified_samples",
    "tissue_ontology_term_id": "unified_samples",
    "disease_ontology_term_id": "unified_samples",
    # Celltypes
    "cell_type_name": "unified_celltypes",
    "cell_type_ontology_term_id": "unified_celltypes",
}

# v_sample_with_hierarchy 包含的字段
# 注意: cell_type 不在视图中，需要时会自动回退到 unified_samples + JOIN
VIEW_FIELDS = {
    "sample_pk", "sample_id", "sample_id_type", "sample_source",
    "organism", "tissue", "tissue_ontology_term_id", "tissue_general",
    "disease", "disease_ontology_term_id",
    "sex", "age", "age_unit", "development_stage", "ethnicity",
    "individual_id", "n_cells", "biological_identity_hash",
    "series_pk", "series_id", "series_title", "assay",
    "series_cell_count",
    "project_pk", "project_id", "project_title",
    "pmid", "doi", "citation_count",
}


class JoinPathResolver:
    """根据查询涉及的字段自动推导JOIN路径"""

    JOIN_RULES = {
        ("unified_samples", "unified_projects"): JoinClause(
            "LEFT JOIN", "unified_projects", "p",
            "s.project_pk = p.pk",
        ),
        ("unified_samples", "unified_series"): JoinClause(
            "LEFT JOIN", "unified_series", "sr",
            "s.series_pk = sr.pk",
        ),
        ("unified_celltypes", "unified_samples"): JoinClause(
            "INNER JOIN", "unified_samples", "s",
            "ct.sample_pk = s.pk",
        ),
    }

    def resolve(self, needed_fields: list[str], target_table: str = "unified_samples") -> JoinPlan:
        """推导最优JOIN路径"""
        # 检查是否能用视图
        if target_table == "unified_samples":
            field_set = set(needed_fields)
            if field_set.issubset(VIEW_FIELDS) or not field_set:
                return JoinPlan(base_table="v_sample_with_hierarchy", use_view=True)

        needed_tables = set()
        for f in needed_fields:
            t = FIELD_TABLE.get(f)
            if t:
                needed_tables.add(t)
        needed_tables.add(target_table)

        if len(needed_tables) <= 1:
            return JoinPlan(base_table=target_table)

        # 构建JOIN链
        joins = []
        connected = {target_table}
        remaining = needed_tables - connected

        for table in sorted(remaining):
            key = (target_table, table)
            rev_key = (table, target_table)
            rule = self.JOIN_RULES.get(key) or self.JOIN_RULES.get(rev_key)
            if rule:
                joins.append(rule)
                connected.add(table)

        return JoinPlan(base_table=target_table, joins=joins)


class SQLGenerator:
    """
    SQL生成器: 3候选策略
    1. 模板 (常见模式)
    2. 规则 (灵活组合)
    3. LLM (复杂/歧义)
    """

    def __init__(self, dal: DatabaseAbstractionLayer, llm: ILLMClient | None = None):
        self.dal = dal
        self.llm = llm
        self.join_resolver = JoinPathResolver()

    async def generate(
        self,
        query: ParsedQuery,
        resolved_entities: list[ResolvedEntity] | None = None,
    ) -> list[SQLCandidate]:
        """生成SQL候选列表"""
        candidates: list[SQLCandidate] = []

        # 确定涉及的字段
        needed_fields = self._collect_needed_fields(query)
        plan = self.join_resolver.resolve(needed_fields, self._target_to_table(query.target_level))

        # 路径1: 模板
        tpl = self._from_template(query, resolved_entities, plan)
        if tpl:
            candidates.append(tpl)

        # 路径2: 规则
        rule = self._from_rules(query, resolved_entities, plan)
        candidates.append(rule)

        # 路径3: LLM (仅复杂查询)
        if self.llm and query.complexity in (QueryComplexity.MODERATE, QueryComplexity.COMPLEX):
            try:
                llm_sql = await self._from_llm(query, resolved_entities, plan)
                if llm_sql:
                    candidates.append(llm_sql)
            except Exception as e:
                logger.warning("LLM SQL generation failed: %s", e)

        return candidates

    def _collect_needed_fields(self, query: ParsedQuery) -> list[str]:
        """收集查询涉及的字段"""
        fields = set()
        f = query.filters
        if f.tissues:
            fields.add("tissue")
        if f.diseases:
            fields.add("disease")
        if f.assays:
            fields.add("assay")
        if f.cell_types:
            fields.add("cell_type")
        if f.source_databases:
            fields.add("source_database")
        if f.sex:
            fields.add("sex")
        if f.organisms:
            fields.add("organism")
        if f.development_stages:
            fields.add("development_stage")
        if f.has_h5ad is not None:
            fields.add("has_h5ad")
        if f.pmids:
            fields.add("pmid")
        if f.dois:
            fields.add("doi")
        if f.min_cells is not None:
            fields.add("n_cells")
        if f.min_citation_count is not None:
            fields.add("citation_count")
        if query.ordering:
            fields.add(query.ordering.field)
        if query.aggregation:
            fields.update(query.aggregation.group_by)
        return list(fields)

    @staticmethod
    def _target_to_table(level: str) -> str:
        return {
            "project": "unified_projects",
            "series": "unified_series",
            "sample": "unified_samples",
            "celltype": "unified_celltypes",
        }.get(level, "unified_samples")

    # ---------- 模板生成 ----------

    def _from_template(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate | None:
        """模板化SQL生成"""
        f = query.filters

        # ID查询模板
        if f.project_ids:
            pid = f.project_ids[0]
            return SQLCandidate(
                sql="SELECT * FROM unified_projects WHERE project_id = ? LIMIT 1",
                params=[pid], method="template",
            )
        if f.sample_ids:
            sid = f.sample_ids[0]
            return SQLCandidate(
                sql="SELECT * FROM unified_samples WHERE sample_id = ? LIMIT 1",
                params=[sid], method="template",
            )
        if f.pmids:
            return SQLCandidate(
                sql="SELECT * FROM unified_projects WHERE pmid = ? LIMIT 10",
                params=[f.pmids[0]], method="template",
            )

        # 统计模板
        if query.aggregation and query.intent == QueryIntent.STATISTICS:
            return self._statistics_template(query, plan)

        return None

    def _statistics_template(self, query: ParsedQuery, plan: JoinPlan) -> SQLCandidate:
        """统计类SQL模板"""
        agg = query.aggregation
        group_field = _vc(
            agg.group_by[0] if agg.group_by else "source_database",
            plan.use_view,
        )
        table = plan.base_table

        where_parts, params = self._build_where(query.filters, table, plan.use_view)
        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        sql = (
            f"SELECT {group_field}, COUNT(*) as count, "
            f"SUM(CASE WHEN n_cells IS NOT NULL THEN n_cells ELSE 0 END) as total_cells "
            f"FROM {table} WHERE {where_sql} "
            f"GROUP BY {group_field} ORDER BY count DESC LIMIT {query.limit}"
        )
        return SQLCandidate(sql=sql, params=params, method="template")

    # ---------- 规则生成 ----------

    def _from_rules(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate:
        """规则化SQL构建"""
        table = plan.base_table
        use_view = plan.use_view

        # Collect ontology-expanded fields to exclude from _build_where
        onto_fields: set[str] = set()
        onto_parts: list[str] = []
        onto_params: list = []

        if entities:
            for ent in entities:
                if ent.db_values and ent.original.entity_type in ("tissue", "disease", "cell_type"):
                    field = _vc(ent.original.entity_type, use_view)
                    values = [v.raw_value for v in ent.db_values[:50]]
                    if values:
                        onto_fields.add(ent.original.entity_type)
                        placeholders = ", ".join("?" * len(values))
                        onto_parts.append(f"{field} IN ({placeholders})")
                        onto_params.extend(values)

        # Build WHERE from filters, excluding ontology-handled fields
        where_parts, params = self._build_where(
            query.filters, table, use_view,
            exclude_fields=onto_fields if onto_fields else None,
        )

        # Prepend ontology-expanded conditions
        if onto_parts:
            where_parts = onto_parts + where_parts
            params = onto_params + params

        if not where_parts:
            if query.filters.free_text:
                t_col = _vc("tissue", use_view)
                d_col = _vc("disease", use_view)
                title_col = _vc("title", use_view)
                if use_view:
                    where_parts.append(
                        f"({t_col} LIKE ? OR {d_col} LIKE ? OR {title_col} LIKE ?)"
                    )
                    text = f"%{query.filters.free_text}%"
                    params.extend([text, text, text])
                else:
                    where_parts.append(f"({t_col} LIKE ? OR {d_col} LIKE ?)")
                    text = f"%{query.filters.free_text}%"
                    params.extend([text, text])

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        # SELECT
        select = "*"
        if query.aggregation:
            group = _vc(query.aggregation.group_by[0], use_view)
            select = f"{group}, COUNT(*) as count"

        # ORDER BY
        order = ""
        if query.ordering:
            order = f" ORDER BY {_vc(query.ordering.field, use_view)} {query.ordering.direction.upper()}"
        elif query.aggregation:
            order = " ORDER BY count DESC"
        else:
            order = f" ORDER BY {_vc('pk', use_view)} DESC"

        # GROUP BY
        group_by = ""
        if query.aggregation:
            group_by = f" GROUP BY {_vc(query.aggregation.group_by[0], use_view)}"

        sql = f"SELECT {select} FROM {table} WHERE {where_sql}{group_by}{order} LIMIT {query.limit}"
        return SQLCandidate(sql=sql, params=params, method="rule")

    def _build_where(
        self, filters: QueryFilters, table: str,
        use_view: bool = False, exclude_fields: set | None = None,
    ) -> tuple[list[str], list[Any]]:
        """构建WHERE条件 (use_view=True时自动映射视图列名)"""
        parts: list[str] = []
        params: list[Any] = []
        exclude = exclude_fields or set()

        def _like(field: str, values: list[str]):
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            or_clauses = [f"{col} LIKE ?" for _ in values]
            parts.append(f"({' OR '.join(or_clauses)})")
            params.extend(f"%{v}%" for v in values)

        def _in(field: str, values: list[str]):
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            placeholders = ", ".join("?" * len(values))
            parts.append(f"{col} IN ({placeholders})")
            params.extend(values)

        def _eq(field: str, value: Any):
            if value is None or field in exclude:
                return
            col = _vc(field, use_view)
            parts.append(f"{col} = ?")
            params.append(value)

        _like("tissue", filters.tissues)
        _like("disease", filters.diseases)
        _like("cell_type", filters.cell_types)
        _in("source_database", filters.source_databases)
        _like("assay", filters.assays)
        _like("organism", filters.organisms)
        _eq("sex", filters.sex)
        _in("pmid", filters.pmids)

        if filters.min_cells is not None and "n_cells" not in exclude:
            parts.append("n_cells >= ?")
            params.append(filters.min_cells)
        if filters.min_citation_count is not None and "citation_count" not in exclude:
            col = _vc("citation_count", use_view)
            parts.append(f"{col} >= ?")
            params.append(filters.min_citation_count)

        return parts, params

    # ---------- LLM生成 ----------

    async def _from_llm(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate | None:
        """LLM生成SQL"""
        if not self.llm:
            return None

        ddl = self.dal.schema_inspector.get_ddl_summary()
        prompt = f"""Generate a SQLite query for this request.

Schema:
{ddl}

View v_sample_with_hierarchy joins samples+series+projects. Use it for simple queries.

User intent: {query.intent.name}
Target: {query.target_level}
Filters: tissues={query.filters.tissues}, diseases={query.filters.diseases}, organisms={query.filters.organisms}, assays={query.filters.assays}, cell_types={query.filters.cell_types}, sex={query.filters.sex}, sources={query.filters.source_databases}, free_text={query.filters.free_text}
Aggregation: {query.aggregation}
Limit: {query.limit}

Rules:
- Use parameterized queries (?) for values
- Use LIKE '%term%' for text matching
- Always add LIMIT
- For text matching use COLLATE NOCASE or LOWER()
- Return ONLY the SQL, no explanation

SQL:"""

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=512,
        )

        sql = response.content.strip()
        # 清理
        if sql.startswith("```"):
            sql = sql.split("```")[1].strip()
            if sql.startswith("sql"):
                sql = sql[3:].strip()
        sql = sql.rstrip(";")

        if not sql.upper().startswith("SELECT"):
            return None

        return SQLCandidate(sql=sql, params=[], method="llm")


class ParallelSQLExecutor:
    """
    并行SQL执行 + 渐进降级

    策略:
    1. 并行执行所有候选
    2. 第一个返回合理结果的候选胜出
    3. 全部失败 → 渐进放宽条件
    """

    CANDIDATE_TIMEOUT = 2.0  # 单候选超时(秒)

    def __init__(self, dal: DatabaseAbstractionLayer):
        self.dal = dal

    async def execute(self, candidates: list[SQLCandidate]) -> ExecutionResult:
        """并行执行候选SQL"""
        if not candidates:
            return ExecutionResult.empty(["No SQL candidates"])

        # 创建并行任务
        tasks = [
            asyncio.create_task(self._execute_one(c))
            for c in candidates
        ]

        # as_completed: 第一个合理结果即返回
        errors: list[str] = []
        for coro in asyncio.as_completed(tasks, timeout=self.CANDIDATE_TIMEOUT * 2):
            try:
                result = await coro
                if result and result.validation.is_valid:
                    # 取消其余任务
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return result
                elif result:
                    errors.append(f"{result.method}: {result.validation.issue}")
            except asyncio.TimeoutError:
                errors.append("timeout")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                errors.append(str(e))

        # 全部失败 → 渐进降级
        return await self._fallback(candidates, errors)

    async def _execute_one(self, candidate: SQLCandidate) -> ExecutionResult | None:
        """执行单个候选"""
        try:
            t0 = time.perf_counter()
            result = self.dal.execute(candidate.sql, candidate.params)
            elapsed = (time.perf_counter() - t0) * 1000

            # 验证
            validation = self._validate(result, candidate)

            return ExecutionResult(
                rows=result.rows,
                columns=result.columns,
                sql=candidate.sql,
                params=candidate.params,
                method=candidate.method,
                exec_time_ms=round(elapsed, 2),
                row_count=len(result.rows),
                validation=validation,
            )
        except Exception as e:
            logger.warning("SQL execution failed [%s]: %s", candidate.method, e)
            return ExecutionResult(
                sql=candidate.sql,
                method=candidate.method,
                validation=ValidationResult(is_valid=False, issue=str(e)),
            )

    def _validate(self, result, candidate: SQLCandidate) -> ValidationResult:
        """结果验证"""
        if not result.rows:
            return ValidationResult(
                is_valid=False, issue="zero_results",
                suggestion="try_broader_query",
            )
        if len(result.rows) > 10000:
            return ValidationResult(
                is_valid=True,
                note=f"Large result set: {len(result.rows)} rows",
            )
        return ValidationResult(is_valid=True)

    async def _fallback(self, candidates: list[SQLCandidate], errors: list[str]) -> ExecutionResult:
        """渐进降级"""
        if not candidates:
            return ExecutionResult.empty(errors)

        base = candidates[0]
        sql = base.sql

        # Level 1: 将 = 改为 LIKE
        relaxed = sql.replace(" = ?", " LIKE ?")
        params = [f"%{p}%" if isinstance(p, str) else p for p in (base.params or [])]
        try:
            result = self.dal.execute(relaxed, params)
            if result.rows:
                return ExecutionResult(
                    rows=result.rows,
                    columns=result.columns,
                    sql=relaxed,
                    params=params,
                    method="fallback_fuzzy",
                    exec_time_ms=result.execution_time_ms,
                    row_count=len(result.rows),
                    validation=ValidationResult(
                        is_valid=True,
                        note="降级到模糊匹配获得结果",
                    ),
                )
        except Exception:
            pass

        # Level 2: 去除大部分条件，只保留最核心的一个
        # 尝试只用视图查前20条
        try:
            simple_sql = "SELECT * FROM v_sample_with_hierarchy LIMIT 20"
            result = self.dal.execute(simple_sql)
            return ExecutionResult(
                rows=result.rows,
                columns=result.columns,
                sql=simple_sql,
                method="fallback_explore",
                exec_time_ms=result.execution_time_ms,
                row_count=len(result.rows),
                validation=ValidationResult(
                    is_valid=True,
                    note="所有查询条件都无结果，返回探索结果",
                ),
            )
        except Exception:
            pass

        return ExecutionResult.empty(errors)
