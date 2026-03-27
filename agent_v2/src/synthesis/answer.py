"""
Answer Synthesizer — 答案合成模块

将执行结果转化为用户可理解的自然语言响应。
实现 IAnswerSynthesizer 协议。

功能:
1. 自然语言摘要生成 (template-based + LLM-enhanced)
2. 后续操作建议生成
3. 数据可视化规格生成
4. 数据质量评估
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.interfaces import ILLMClient
from ..core.models import (
    AgentResponse,
    ChartSpec,
    ExecutionResult,
    FusedRecord,
    ParsedQuery,
    ProvenanceInfo,
    QualityReport,
    QueryIntent,
    Suggestion,
)
from ..core.exceptions import SynthesisError

logger = logging.getLogger(__name__)


class AnswerSynthesizer:
    """
    答案合成器 — 实现 IAnswerSynthesizer 协议

    两种模式:
    - Template模式 (默认): 纯规则模板，零 LLM 成本
    - LLM增强模式: 对复杂结果调用 LLM 生成更自然的摘要
    """

    def __init__(self, llm: ILLMClient | None = None):
        self.llm = llm

    async def synthesize(
        self,
        query: ParsedQuery,
        results: list[FusedRecord],
        provenance: dict,
    ) -> AgentResponse:
        """
        协议方法 — 完整合成流程

        Args:
            query: 解析后的查询
            results: 融合后的记录列表
            provenance: 原始 provenance 字典 (包含 sql, method, timing 等)

        Returns:
            完整的 AgentResponse
        """
        try:
            summary = await self._generate_summary(query, results, provenance)
            suggestions = self._generate_suggestions(query, results)
            charts = self._generate_charts(query, results)
            quality = self._assess_quality(results)

            prov = ProvenanceInfo(
                original_query=provenance.get("original_query", query.original_text),
                parsed_intent=provenance.get("parsed_intent", query.intent.name),
                sql_executed=provenance.get("sql", ""),
                sql_method=provenance.get("method", ""),
                execution_time_ms=provenance.get("execution_time_ms", 0.0),
                data_sources=provenance.get("data_sources", []),
                fusion_stats=provenance.get("fusion_stats", {}),
                ontology_expansions=provenance.get("ontology_expansions", []),
            )

            return AgentResponse(
                summary=summary,
                results=results[:query.limit],
                total_count=len(results),
                displayed_count=min(len(results), query.limit),
                provenance=prov,
                quality_report=quality,
                suggestions=suggestions,
                charts=charts,
            )
        except Exception as e:
            raise SynthesisError(str(e)) from e

    def synthesize_from_execution(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        exec_result: ExecutionResult,
        elapsed_ms: float,
        ontology_expansions: list[dict] | None = None,
    ) -> AgentResponse:
        """
        便捷方法 — 直接从执行结果合成 (同步，用于 Coordinator)

        与 Coordinator 旧 _synthesize 方法签名一致，便于迁移。
        """
        summary = self._generate_summary_sync(parsed, fused, exec_result)
        suggestions = self._generate_suggestions(parsed, fused)
        charts = self._generate_charts(parsed, fused)

        provenance = ProvenanceInfo(
            original_query=parsed.original_text,
            parsed_intent=parsed.intent.name,
            sql_executed=exec_result.sql,
            sql_method=exec_result.method,
            execution_time_ms=elapsed_ms,
            data_sources=list(set(
                s for r in fused for s in r.sources
            )),
            fusion_stats={
                "raw_count": exec_result.row_count,
                "fused_count": len(fused),
                "dedup_rate": round(
                    (1 - len(fused) / max(exec_result.row_count, 1)) * 100, 1
                ),
            },
            ontology_expansions=ontology_expansions or [],
        )

        quality = self._assess_quality(fused)

        return AgentResponse(
            summary=summary,
            results=fused[:parsed.limit],
            total_count=len(fused),
            displayed_count=min(len(fused), parsed.limit),
            provenance=provenance,
            quality_report=quality,
            suggestions=suggestions,
            charts=charts,
        )

    # ─── Summary Generation ───

    async def _generate_summary(
        self,
        query: ParsedQuery,
        fused: list[FusedRecord],
        provenance: dict,
    ) -> str:
        """Generate summary — LLM-enhanced when available."""
        template_summary = self._build_template_summary(query, fused, provenance)

        if self.llm and len(fused) > 0 and query.intent != QueryIntent.STATISTICS:
            try:
                return await self._llm_enhanced_summary(query, fused, template_summary)
            except Exception as e:
                logger.debug("LLM summary fallback to template: %s", e)

        return template_summary

    def _generate_summary_sync(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        exec_result: ExecutionResult,
    ) -> str:
        """Synchronous template-only summary."""
        return self._build_template_summary(
            parsed, fused,
            {"raw_count": exec_result.row_count},
        )

    def _build_template_summary(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        provenance: dict,
    ) -> str:
        """Template-based summary — deterministic, zero cost."""
        n = len(fused)
        raw_n = provenance.get("raw_count", n)

        if n == 0:
            return self._zero_result_summary(parsed)

        src_counts = self._count_sources(fused)
        src_str = ", ".join(
            f"{db}({cnt})" for db, cnt in
            sorted(src_counts.items(), key=lambda x: -x[1])[:5]
        )

        conds = self._describe_conditions(parsed)

        if parsed.intent == QueryIntent.STATISTICS:
            return f"统计结果: {n}个分组。数据来源: {src_str}。"

        dedup_note = ""
        if raw_n > n:
            dedup_note = f" (原始{raw_n}条，跨库去重后{n}条)"

        cond_desc = " + ".join(conds) if conds else "所有"
        return f"找到 {n} 个{cond_desc}相关数据集{dedup_note}，覆盖 {len(src_counts)} 个数据库: {src_str}。"

    @staticmethod
    def _zero_result_summary(parsed: ParsedQuery) -> str:
        """Summary for zero-result queries."""
        conditions = []
        if parsed.filters.tissues:
            conditions.append(f"tissue={parsed.filters.tissues}")
        if parsed.filters.diseases:
            conditions.append(f"disease={parsed.filters.diseases}")
        cond_str = ", ".join(conditions) if conditions else parsed.original_text
        return f"未找到匹配 [{cond_str}] 的结果。建议尝试更宽泛的搜索条件。"

    @staticmethod
    def _count_sources(fused: list[FusedRecord]) -> dict[str, int]:
        """Count records per data source."""
        src_counts: dict[str, int] = {}
        for r in fused:
            for s in r.sources:
                src_counts[s] = src_counts.get(s, 0) + 1
        return src_counts

    @staticmethod
    def _describe_conditions(parsed: ParsedQuery) -> list[str]:
        """Extract human-readable condition descriptions."""
        conds = []
        if parsed.filters.tissues:
            conds.append("/".join(parsed.filters.tissues))
        if parsed.filters.diseases:
            conds.append("/".join(parsed.filters.diseases))
        if parsed.filters.cell_types:
            conds.append("/".join(parsed.filters.cell_types))
        if parsed.filters.assays:
            conds.append("/".join(parsed.filters.assays))
        return conds

    async def _llm_enhanced_summary(
        self,
        query: ParsedQuery,
        fused: list[FusedRecord],
        template_summary: str,
    ) -> str:
        """LLM-enhanced summary for richer natural language output."""
        # Build a concise data snapshot for the LLM
        top_3 = fused[:3]
        snapshot = []
        for r in top_3:
            entry = {
                k: r.data.get(k)
                for k in ["tissue", "disease", "organism", "source_database", "n_cells"]
                if r.data.get(k)
            }
            snapshot.append(entry)

        prompt = f"""Rewrite this database query result summary in fluent, informative English.

Original query: {query.original_text}
Template summary: {template_summary}
Total results: {len(fused)}
Sample records: {snapshot}

Rules:
- Keep it under 2 sentences
- Mention key biological context
- Include the total count
- Do NOT add information not in the data
"""
        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        result = response.content.strip()
        return result if result else template_summary

    # ─── Suggestion Generation ───

    def _generate_suggestions(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
    ) -> list[Suggestion]:
        """Generate contextual follow-up suggestions."""
        suggestions: list[Suggestion] = []

        if not fused:
            suggestions.append(Suggestion(
                type="expand",
                text="尝试去掉部分条件扩大搜索范围",
                action_query=(
                    parsed.filters.tissues[0]
                    if parsed.filters.tissues
                    else "explore"
                ),
                reason="当前条件无结果",
            ))
            return suggestions

        # Refine if too many results
        if len(fused) > 50:
            if not parsed.filters.diseases:
                suggestions.append(Suggestion(
                    type="refine",
                    text=f"结果较多({len(fused)}条)，可以按疾病类型细化",
                    action_query=f"{parsed.original_text} 疾病分布",
                    reason="未指定disease条件",
                ))
            if not parsed.filters.assays:
                suggestions.append(Suggestion(
                    type="refine",
                    text="可以按测序平台(如10x)进一步筛选",
                    action_query=f"{parsed.original_text} 10x",
                    reason="未指定assay条件",
                ))

        # Downloadable datasets
        downloadable = sum(
            1 for r in fused[:20]
            if r.data.get("has_h5ad") or r.data.get("access_url")
        )
        if downloadable > 0:
            suggestions.append(Suggestion(
                type="download",
                text=f"其中{downloadable}个数据集有可直接下载的h5ad/rds文件",
                action_query=f"download {parsed.original_text}",
                reason="检测到可下载数据",
            ))

        # Cross-source comparison
        sources = set(s for r in fused for s in r.sources)
        if len(sources) > 1:
            suggestions.append(Suggestion(
                type="compare",
                text=f"结果来自{len(sources)}个数据库，是否比较各库数据覆盖？",
                action_query=f"统计各数据库 {parsed.original_text}",
                reason="结果跨多个数据源",
            ))

        return suggestions[:4]

    # ─── Chart Generation ───

    def _generate_charts(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
    ) -> list[ChartSpec]:
        """Generate visualization specs for frontend rendering."""
        charts: list[ChartSpec] = []
        if not fused:
            return charts

        # Statistics: bar chart
        if parsed.intent == QueryIntent.STATISTICS and parsed.aggregation:
            group_key = parsed.aggregation.group_by[0]
            chart_data = {
                str(r.data.get(group_key, "")): r.data.get("count", 0)
                for r in fused[:20]
            }
            charts.append(ChartSpec(
                type="bar", title="统计分布", data=chart_data,
            ))
            return charts

        # Source distribution: pie chart
        src_dist = self._count_sources(fused)
        if len(src_dist) > 1:
            charts.append(ChartSpec(
                type="pie", title="数据来源分布", data=src_dist,
            ))

        return charts

    # ─── Quality Assessment ───

    @staticmethod
    def _assess_quality(fused: list[FusedRecord]) -> QualityReport:
        """Assess data quality of fused results."""
        if not fused:
            return QualityReport()

        completeness: dict[str, float] = {}
        for field_name in ["tissue", "disease", "sex", "assay", "n_cells"]:
            filled = sum(1 for r in fused if r.data.get(field_name))
            completeness[field_name] = round(filled / len(fused) * 100, 1)

        src_coverage: dict[str, int] = {}
        for r in fused:
            for s in r.sources:
                src_coverage[s] = src_coverage.get(s, 0) + 1

        multi_src = sum(1 for r in fused if r.source_count > 1)
        cross_score = round(multi_src / len(fused) * 100, 1) if fused else 0

        return QualityReport(
            field_completeness=completeness,
            cross_validation_score=cross_score,
            source_coverage=src_coverage,
        )
