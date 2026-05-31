"""
KnowledgePromptBuilder — 将数据统计信息注入 LLM Prompt

功能:
1. 为 SQL 生成 prompt 注入字段分布、基数估计、选择性提示
2. 为 Query Parser prompt 注入 top values + 同义词
3. 为 Zero-result Recovery prompt 注入实际数据分布
4. 生成多轮对话上下文摘要
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.schema_config import SchemaConfig

from .data_stats import DataStatsAnalyzer
from .cardinality import CardinalityEstimator
from .models import KnowledgeContext

logger = logging.getLogger(__name__)

# 硬编码默认值 — 仅在无 SchemaConfig 时使用 (向后兼容)
_DEFAULT_CORE_FIELDS = ["tissue", "disease", "organism", "source_database", "assay", "sex"]

_DEFAULT_FIELD_LABELS = {
    "tissue": "组织/Tissue",
    "disease": "疾病/Disease",
    "organism": "物种/Organism",
    "source_database": "数据源/Source",
    "assay": "测序技术/Assay",
    "sex": "性别/Sex",
}


class KnowledgePromptBuilder:
    """将数据库统计知识注入 LLM prompt 的构建器"""

    def __init__(
        self,
        stats_analyzer: DataStatsAnalyzer,
        cardinality_est: Optional[CardinalityEstimator] = None,
        *,
        schema_config: Optional[SchemaConfig] = None,
        core_fields: Optional[list[str]] = None,
        field_labels: Optional[dict[str, str]] = None,
        default_table: str = "",
    ):
        self.stats = stats_analyzer
        self.cardinality = cardinality_est
        self.default_table = default_table

        # 优先级: 显式参数 > SchemaConfig > 硬编码默认值
        if core_fields is not None:
            self._core_fields = core_fields
        elif schema_config is not None:
            self._core_fields = schema_config.core_fields
            self.default_table = schema_config.main_table
        else:
            self._core_fields = list(_DEFAULT_CORE_FIELDS)

        self._field_labels = field_labels or dict(_DEFAULT_FIELD_LABELS)

    async def build_sql_knowledge_block(
        self,
        table: str = "",
        filters: Optional[dict[str, list[str]]] = None,
        max_values_per_field: int = 8,
    ) -> str:
        """
        构建 SQL 生成 prompt 的知识注入块。

        包含:
        - 表行数
        - 各字段 distinct count + top values
        - 基数估计 (如果有过滤条件)
        - 选择性提示
        """
        if not self.stats:
            return ""
        table = table or self.default_table

        lines = ["## Database Statistics (auto-generated)"]

        # 表行数
        try:
            row_count = await self.stats.get_table_row_count(table)
            lines.append(f"Total rows in {table}: {row_count:,}")
        except Exception:
            row_count = 0

        lines.append("")

        # 各字段统计
        for field in self._core_fields:
            try:
                fs = await self.stats.get_field_stats(table, field)
                if not fs:
                    continue
                label = self._field_labels.get(field, field)
                top_vals = [f'"{v}" ({c:,})' for v, c in fs.histogram[:max_values_per_field]]
                lines.append(
                    f"- {label}: {fs.distinct_count} distinct values, "
                    f"null={fs.null_pct:.1f}%"
                )
                if top_vals:
                    lines.append(f"  Top values: {', '.join(top_vals)}")
            except Exception as e:
                logger.debug("Failed to get stats for %s.%s: %s", table, field, e)

        # 基数估计
        if filters and self.cardinality:
            lines.append("")
            try:
                est = await self.cardinality.estimate_result_size(table, filters)
                lines.append(f"Estimated result size for current filters: ~{est:,} rows")
                if est > 50000:
                    lines.append("⚠ Large result set — use restrictive LIMIT and consider adding filters")
                elif est < 5:
                    lines.append("⚠ Very few results — consider using LIKE for broader matching")
            except Exception:
                pass

        # 选择性提示
        if filters:
            lines.append("")
            lines.append("Filter selectivity hints:")
            for field, values in filters.items():
                for val in values[:3]:
                    try:
                        est = await self.stats.estimate_selectivity(table, field, val)
                        pct = est.estimated_selectivity * 100
                        lines.append(
                            f"  - {field}='{val}': ~{pct:.1f}% of rows "
                            f"(confidence={est.confidence:.0%}, method={est.based_on})"
                        )
                    except Exception:
                        pass

        return "\n".join(lines)

    async def build_parser_knowledge_block(
        self,
        table: str = "",
        max_values_per_field: int = 10,
    ) -> str:
        """
        构建 Query Parser prompt 的知识注入块。

        包含:
        - 各字段 top values (帮助 LLM 映射用户输入到 DB 值)
        - 同义词提示
        """
        table = table or self.default_table
        lines = ["## Known Database Values"]

        for field in self._core_fields:
            try:
                fs = await self.stats.get_field_stats(table, field)
                if not fs or not fs.histogram:
                    continue
                label = self._field_labels.get(field, field)
                vals = [v for v, _ in fs.histogram[:max_values_per_field]]
                lines.append(f"- {label}: {', '.join(vals)}")
            except Exception:
                pass

        lines.append("")
        lines.append("Map user terms to these exact DB values. Use LIKE for partial matches.")

        return "\n".join(lines)

    async def build_recovery_knowledge_block(
        self,
        table: str = "",
        failed_filters: Optional[dict[str, list[str]]] = None,
        max_values_per_field: int = 15,
    ) -> str:
        """
        构建 Zero-result Recovery prompt 的知识注入块。

        包含:
        - 失败过滤条件的选择性分析
        - 相关字段的实际值分布 (帮助 LLM 建议替代值)
        """
        table = table or self.default_table
        lines = ["## Data Distribution for Recovery"]

        if failed_filters:
            lines.append("")
            lines.append("Failed filter analysis:")
            for field, values in failed_filters.items():
                for val in values:
                    try:
                        est = await self.stats.estimate_selectivity(table, field, val)
                        if est.based_on == "semantic_default":
                            lines.append(
                                f"  ⚠ {field}='{val}': NOT FOUND in database "
                                f"(no histogram match)"
                            )
                        else:
                            pct = est.estimated_selectivity * 100
                            lines.append(
                                f"  - {field}='{val}': ~{pct:.1f}% of rows"
                            )
                    except Exception:
                        pass

        # 提供相关字段的完整值列表
        relevant_fields = set()
        if failed_filters:
            relevant_fields = set(failed_filters.keys())
        if not relevant_fields:
            relevant_fields = {"tissue", "disease"}

        lines.append("")
        lines.append("Available values in database:")
        for field in relevant_fields:
            try:
                fs = await self.stats.get_field_stats(table, field)
                if not fs or not fs.histogram:
                    continue
                vals = [f'"{v}" ({c})' for v, c in fs.histogram[:max_values_per_field]]
                lines.append(f"  {field}: {', '.join(vals)}")
            except Exception:
                pass

        return "\n".join(lines)

    async def build_knowledge_context(
        self,
        table: str = "",
        filters: Optional[dict[str, list[str]]] = None,
    ) -> KnowledgeContext:
        """
        构建完整的 KnowledgeContext 对象 (供 ContextualSQLGenerator 使用)。
        """
        table = table or self.default_table
        ctx = KnowledgeContext()

        # 收集字段统计
        for field in self._core_fields:
            try:
                fs = await self.stats.get_field_stats(table, field)
                if fs:
                    ctx.field_stats[field] = fs
            except Exception:
                pass

        # 基数估计
        if filters and self.cardinality:
            try:
                est = await self.cardinality.estimate_result_size(table, filters)
                ctx.estimated_result_size = est

                limit = await self.cardinality.suggest_limit(table, filters)
                ctx.suggested_limit = limit

                warn, _, msg = await self.cardinality.should_warn_large_result(
                    table, filters,
                )
                if warn:
                    ctx.warnings.append(msg)
            except Exception:
                pass

        # 选择性提示
        if filters:
            for field, values in filters.items():
                for val in values[:3]:
                    try:
                        est = await self.stats.estimate_selectivity(table, field, val)
                        ctx.selectivity_hints.append(est)
                    except Exception:
                        pass

        return ctx

    def build_session_context_block(
        self,
        session_history: list[dict],
        max_turns: int = 3,
    ) -> str:
        """
        构建多轮对话上下文摘要块。

        包含:
        - 最近 N 轮对话的查询+结果摘要
        - 上一轮的过滤条件 (用于 "这些中" / "其中" 引用)
        """
        if not session_history:
            return ""

        recent = session_history[-max_turns:]
        lines = ["## Conversation Context"]

        for i, turn in enumerate(recent, 1):
            query = turn.get("input", "")
            count = turn.get("result_count", 0)
            intent = turn.get("intent", "SEARCH")
            filters = turn.get("filters", {})

            lines.append(f"Turn {i}: \"{query}\"")
            lines.append(f"  → {count} results, intent={intent}")
            if filters:
                filter_parts = []
                for k, v in filters.items():
                    if v:
                        filter_parts.append(f"{k}={v}")
                if filter_parts:
                    lines.append(f"  Filters: {', '.join(filter_parts)}")

        # 最后一轮的结果集引用提示
        if len(recent) >= 2:
            # 查找最近一个有结果的轮次 (用于引用)
            prev_with_results = None
            for turn in reversed(recent[:-1]):
                if turn.get("result_count", 0) > 0:
                    prev_with_results = turn
                    break
            if prev_with_results:
                prev_count = prev_with_results.get("result_count", 0)
                prev_filters = prev_with_results.get("filters", {})
                lines.append("")
                lines.append(
                    f"If user says '这些/其中/those/above', they refer to the "
                    f"previous result set ({prev_count} records with filters: {prev_filters})"
                )

        return "\n".join(lines)
