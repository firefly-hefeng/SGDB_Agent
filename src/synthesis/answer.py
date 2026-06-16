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
        # Phase 22-D: per-result facet match — explains why each record was
        # returned, surfaces partial matches, supports the user "score 3 → 4"
        # confidence lift identified in the UX feedback design.
        self._annotate_facet_match(parsed, fused)

        provenance = ProvenanceInfo(
            original_query=parsed.original_text,
            parsed_intent=parsed.intent.name,
            parsed_filters=_filters_to_dict(parsed.filters),
            sql_executed=_inline_params(exec_result.sql, exec_result.params),
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

        # If the SQL was truncated by LIMIT, surface the TRUE total from
        # exec_result.row_count (which the executor populates via COUNT(*)).
        fetched = len(fused)
        true_total = max(fetched, exec_result.row_count)
        # For an aggregation the executor's COUNT(*) is the underlying row
        # count (e.g. 943K), which is meaningless as a result total — the
        # "total" the user cares about is the number of groups returned.
        if parsed.intent == QueryIntent.STATISTICS and parsed.aggregation:
            true_total = fetched

        return AgentResponse(
            summary=summary,
            results=fused[:parsed.limit],
            total_count=true_total,
            displayed_count=min(fetched, parsed.limit),
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
                logger.info("LLM summary fallback to template: %s", e)

        return template_summary

    def _generate_summary_sync(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        exec_result: ExecutionResult,
    ) -> str:
        """Synchronous template-only summary."""
        meta = exec_result.metadata or {}
        return self._build_template_summary(
            parsed, fused,
            {
                "raw_count": exec_result.row_count,
                # row_count is the TRUE COUNT(*) (engine.py:1952); fetched_rows
                # is how many we actually pulled before the LIMIT cap. When
                # true_total > fetched the result set was truncated, so the
                # "deduped to N" framing would be a lie — N is a display cap.
                "true_total": exec_result.row_count,
                "fetched": meta.get("fetched_rows", len(fused)),
            },
        )

    def _build_template_summary(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        provenance: dict,
    ) -> str:
        """Template summary + an honest QC-coverage disclosure (C2)."""
        return (self._build_template_summary_inner(parsed, fused, provenance)
                + self._qc_coverage_note(parsed, fused))

    @classmethod
    def _qc_coverage_note(cls, parsed: ParsedQuery, fused: list[FusedRecord]) -> str:
        """Honest coverage disclosures for SPARSELY-annotated filters that would
        otherwise silently narrow the result to a small slice of the catalog:
          - cell-count (min_cells / min_series_cells): n_cells is chiefly CellxGene (C2)
          - assay/platform: series-level assay annotation exists for ~3.6% of the
            catalog (CellxGene only) — an assay filter collapses to that slice.
        Without these notes a narrow result reads as the whole picture."""
        f = getattr(parsed, "filters", None)
        if not fused or f is None:
            return ""
        en = cls._is_en(parsed)
        notes: list[str] = []
        if getattr(f, "min_cells", None) is not None or getattr(f, "min_series_cells", None) is not None:
            notes.append(
                " Note: the cell-count filter applies only to samples with a recorded "
                "cell count (a minority of the catalog, chiefly CellxGene); samples "
                "without one are excluded."
                if en else
                "（注意：细胞数筛选仅作用于有记录细胞数的样本——目录中的少数，主要来自 "
                "CellxGene；无记录的样本被排除。）")
        if getattr(f, "assays", None):
            notes.append(
                " Note: sequencing-assay annotation is currently available for a small "
                "fraction of the catalog (chiefly CellxGene), so an assay filter narrows "
                "results to that subset — absence of an assay label does not mean a sample "
                "is not 10x/etc."
                if en else
                "（注意：测序平台标注目前仅覆盖目录的一小部分（主要为 CellxGene），因此测序平台筛选"
                "会将结果收窄到该子集——没有平台标注并不代表该样本不是 10x 等平台。）")
        return "".join(notes)

    def _build_template_summary_inner(
        self,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        provenance: dict,
    ) -> str:
        """Template-based summary — deterministic, zero cost."""
        en = self._is_en(parsed)
        n = len(fused)
        raw_n = provenance.get("raw_count", n)
        true_total = provenance.get("true_total", raw_n)
        fetched = provenance.get("fetched", n)
        # The result set was hard-capped by the SQL LIMIT iff the true match
        # count exceeds what we actually fetched. In that case `n` is a display
        # cap, NOT a cross-DB dedup total — we must not present it as one.
        truncated = true_total > fetched

        if n == 0:
            return self._zero_result_summary(parsed)

        src_counts = self._count_sources(fused)
        src_str = ", ".join(
            f"{db}({cnt})" for db, cnt in
            sorted(src_counts.items(), key=lambda x: -x[1])[:5]
        )

        conds = self._describe_conditions(parsed)
        cond_desc = " + ".join(conds) if conds else ("all" if en else "所有")

        if parsed.intent == QueryIntent.STATISTICS:
            return self._statistics_summary(parsed, fused, n)

        if truncated and en:
            displayed = min(n, parsed.limit) if getattr(parsed, "limit", None) else n
            return (
                f"Found ~{true_total:,} samples matching {cond_desc} — showing the "
                f"first {displayed:,} for browsing. Narrow the search (add tissue / "
                f"disease / organism / assay) for an exact cross-database deduplicated count."
            )
        if truncated:
            # Honest framing: headline the TRUE match count, make clear the
            # shown rows are a browsing subset, and nudge toward narrowing.
            # Audit F6: the response only returns fused[:limit], so the "shown"
            # count must be the capped displayed count — not len(fused), which
            # overstated it (e.g. claimed 2,931 shown while returning 100).
            displayed = min(n, parsed.limit) if getattr(parsed, "limit", None) else n
            return (
                f"找到约 {true_total:,} 个{cond_desc}相关样本，结果较多——"
                f"当前展示前 {displayed:,} 条用于浏览。"
                f"建议智能收窄检索范围（叠加组织 / 疾病 / 物种 / 测序平台等限定）"
                f"以获得精确的跨库去重结果。"
            )

        # Not truncated: every matching row was fetched, so the raw→dedup note
        # is accurate and useful.
        if en:
            dedup_note = f" ({fetched:,} raw cross-database records, {n:,} after dedup)" if fetched > n else ""
            base = (f"Found {n:,} datasets matching {cond_desc}{dedup_note}, "
                    f"across {len(src_counts)} databases: {src_str}.")
            if n < 5:
                base += " Few results — try broadening (drop a filter or use a broader synonym)."
            return base
        dedup_note = ""
        if fetched > n:
            dedup_note = f" (原始 {fetched:,} 条跨库记录，去重后 {n:,} 条)"
        base = (
            f"找到 {n:,} 个{cond_desc}相关数据集{dedup_note}，"
            f"覆盖 {len(src_counts)} 个数据库: {src_str}。"
        )
        if n < 5:
            base += " 结果较少，可尝试智能扩大范围（去掉部分限定词或改用更宽泛的同义词）。"
        return base

    # Human labels for the grouping dimension, keyed by GROUP BY column.
    _AGG_DIM_LABELS = {
        "tissue_standard": "组织", "tissue_system": "组织系统",
        "disease_standard": "疾病", "disease_category": "疾病类别",
        "cell_type": "细胞类型", "cell_type_standard": "细胞类型",
        "source_database": "数据库", "sample_source": "数据库",
        "assay": "测序平台", "organism_common": "物种",
        "sex_normalized": "性别", "sample_type": "样本类型",
    }

    @classmethod
    def _statistics_summary(
        cls, parsed: ParsedQuery, fused: list[FusedRecord], n: int,
    ) -> str:
        """Describe an aggregation: name the dimension, list the largest
        buckets, and surface the unlabeled (NULL) share — instead of the old
        meaningless '数据来源: unknown(N)'."""
        agg = parsed.aggregation
        group_key = agg.group_by[0] if agg and agg.group_by else ""
        dim = cls._AGG_DIM_LABELS.get(group_key, group_key or "维度")

        def _val(r: FusedRecord):
            return r.data.get(group_key)

        def _cnt(r: FusedRecord) -> int:
            return int(r.data.get("count", 0) or 0)

        labeled = [r for r in fused if _val(r) not in (None, "", "None")]
        unlabeled = sum(_cnt(r) for r in fused if _val(r) in (None, "", "None"))

        top = sorted(labeled, key=_cnt, reverse=True)[:5]

        if cls._is_en(parsed):
            en_dim = group_key or "dimension"
            top_str = ", ".join(f"{_val(r)} ({_cnt(r):,})" for r in top)
            parts = [f"By {en_dim}: {n:,} groups"]
            if top_str:
                parts.append(f". Largest: {top_str}")
            if unlabeled:
                parts.append(f". Plus {unlabeled:,} with no {en_dim} label")
            return "".join(parts) + "."

        top_str = "、".join(f"{_val(r)} ({_cnt(r):,})" for r in top)
        parts = [f"按{dim}统计：共 {n:,} 个分组"]
        if top_str:
            parts.append(f"。最多为 {top_str}")
        if unlabeled:
            parts.append(f"。另有 {unlabeled:,} 条未标注{dim}")
        return "".join(parts) + "。"

    @staticmethod
    def _is_en(parsed: ParsedQuery) -> bool:
        """Answer in the QUERY's language. CJK in the original text is the primary,
        most reliable signal (the `language` field defaults to 'en' and isn't always
        set by every parser path); fall back to an explicit language='zh'. Default
        English."""
        t = getattr(parsed, "original_text", "") or ""
        if any("一" <= c <= "鿿" for c in t):
            return False
        return getattr(parsed, "language", None) != "zh"

    @classmethod
    def _zero_result_summary(cls, parsed: ParsedQuery) -> str:
        """Summary for zero-result queries.

        Audit F7: this previously reported only tissue + disease, so a query like
        'mouse kidney' (which honest-zeros because the catalogue is human-only)
        blamed 'kidney' — even though kidney has thousands of rows and the real
        discriminator is organism=mouse. Now report every active filter and, when
        a non-human organism is the likely cause, say so explicitly."""
        f = parsed.filters
        conditions = []
        if f.tissues:
            conditions.append(f"tissue={f.tissues}")
        if f.diseases:
            conditions.append(f"disease={f.diseases}")
        if getattr(f, "organisms", None):
            conditions.append(f"organism={f.organisms}")
        if getattr(f, "cell_types", None):
            conditions.append(f"cell_type={f.cell_types}")
        if getattr(f, "assays", None):
            conditions.append(f"assay={f.assays}")
        cond_str = ", ".join(conditions) if conditions else parsed.original_text

        orgs = getattr(f, "organisms", None) or []
        non_human = [
            o for o in orgs
            if not any(k in str(o).lower() for k in ("human", "sapiens", "homo"))
        ]
        en = cls._is_en(parsed)
        if non_human:
            if en:
                return (
                    f"No results matching [{cond_str}]. Note: the curated catalog is "
                    f"human-only (Homo sapiens), so organism={non_human} returns 0 here — "
                    f"the other conditions may have plenty of data. Try the Discover agent "
                    f"for live multi-species search."
                )
            return (
                f"未找到匹配 [{cond_str}] 的结果。"
                f"注意：本数据库目前仅收录人类（Homo sapiens）样本，"
                f"因此 organism={non_human} 不会有结果——其他条件本身可能有大量数据。"
                f"可使用 Discover 智能体进行多物种实时检索。"
            )
        if en:
            return f"No results matching [{cond_str}]. Try broadening the search criteria."
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
    def _annotate_facet_match(parsed: ParsedQuery,
                              fused: list[FusedRecord]) -> None:
        """Phase 22-D: per-record facet match annotation.

        For each FusedRecord, mark how each requested filter dimension
        is satisfied:
          - "match"          — explicit field equality / substring hit
          - "partial"        — overlaps with an ontology-expanded value
          - "miss"           — requested but record data doesn't show it
          - "not_requested"  — filter not in the query (omitted from UI)

        Mutates the records in-place via `record.facet_match`. UI then
        shows e.g. "disease ✓ Alzheimer | tissue ✓ brain | tech ~ 10x v2".
        """
        f = parsed.filters
        # Build per-facet "requested terms" (lowercased)
        req: dict[str, list[str]] = {}
        if f.tissues:
            req["tissue"] = [v.lower().strip() for v in f.tissues]
        if f.diseases:
            req["disease"] = [v.lower().strip() for v in f.diseases]
        if f.cell_types:
            req["cell_type"] = [v.lower().strip() for v in f.cell_types]
        if f.assays:
            req["assay"] = [v.lower().strip() for v in f.assays]
        if f.organisms:
            req["organism"] = [v.lower().strip() for v in f.organisms]
        if f.source_databases:
            req["source"] = [v.lower().strip() for v in f.source_databases]
        if f.sex:
            req["sex"] = [f.sex.lower()]
        if f.disease_categories:
            req["disease_category"] = [v.lower().strip()
                                       for v in f.disease_categories]
        if f.sample_types:
            req["sample_type"] = [v.lower().strip() for v in f.sample_types]

        if not req:
            return  # nothing to annotate

        for record in fused:
            d = record.data or {}
            facet: dict[str, str] = {}
            # Field name → (record field, "lower str" extractor)
            field_alias = {
                "tissue": ("tissue", "tissue_standard"),
                "disease": ("disease", "disease_standard", "disease_category"),
                "cell_type": ("cell_type",),
                "assay": ("assay", "platform"),
                "organism": ("organism", "organism_common"),
                "source": ("source_database", "sample_source"),
                "sex": ("sex", "sex_normalized"),
                "disease_category": ("disease_category",),
                "sample_type": ("sample_type",),
            }
            for fkey, terms in req.items():
                cols = field_alias.get(fkey, (fkey,))
                rec_vals = []
                for c in cols:
                    v = d.get(c)
                    if v:
                        rec_vals.append(str(v).lower())
                if not rec_vals:
                    facet[fkey] = "miss"
                    continue
                # match if any requested term equals or appears in any rec_val
                hit_exact = any(t == rv for t in terms for rv in rec_vals)
                hit_partial = any(t in rv or rv in t
                                  for t in terms for rv in rec_vals)
                if hit_exact:
                    facet[fkey] = "match"
                elif hit_partial:
                    facet[fkey] = "partial"
                else:
                    facet[fkey] = "miss"
            record.facet_match = facet

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
        """Generate contextual follow-up suggestions (in the query's language)."""
        suggestions: list[Suggestion] = []
        en = self._is_en(parsed)

        if not fused:
            suggestions.append(Suggestion(
                type="expand",
                text=("Try dropping a filter to broaden the search"
                      if en else "尝试去掉部分条件扩大搜索范围"),
                action_query=(
                    parsed.filters.tissues[0]
                    if parsed.filters.tissues
                    else "explore"
                ),
                reason="no_results_for_current_filters",
            ))
            return suggestions

        # Broaden if very few results. Point at the most specific active filter.
        if 0 < len(fused) < 10:
            drop_en = drop_zh = None
            if parsed.filters.cell_types:
                drop_en, drop_zh = "cell type", "细胞类型"
            elif parsed.filters.diseases:
                drop_en, drop_zh = "disease", "疾病"
            elif parsed.filters.assays:
                drop_en, drop_zh = "assay", "测序平台"
            elif parsed.filters.sample_types:
                drop_en, drop_zh = "sample type", "样本类型"
            if en:
                text = (f"Few results ({len(fused)}) — broaden"
                        + (f" by dropping the '{drop_en}' filter" if drop_en
                           else " with a broader synonym"))
            else:
                text = (f"结果较少({len(fused)}条)，可智能扩大范围"
                        + (f"：去掉「{drop_zh}」限定" if drop_zh else "：改用更宽泛的同义词"))
            suggestions.append(Suggestion(
                type="expand", text=text,
                action_query=parsed.original_text, reason="few_results_broaden",
            ))

        # Refine if too many results
        if len(fused) > 50:
            if not parsed.filters.diseases:
                suggestions.append(Suggestion(
                    type="refine",
                    text=(f"Many results ({len(fused)}) — refine by disease"
                          if en else f"结果较多({len(fused)}条)，可以按疾病类型细化"),
                    action_query=(f"{parsed.original_text} disease distribution"
                                  if en else f"{parsed.original_text} 疾病分布"),
                    reason="no_disease_filter",
                ))
            if not parsed.filters.assays:
                suggestions.append(Suggestion(
                    type="refine",
                    text=("Refine by assay, e.g. 10x" if en
                          else "可以按测序平台(如10x)进一步筛选"),
                    action_query=f"{parsed.original_text} 10x",
                    reason="no_assay_filter",
                ))

        # Downloadable datasets
        downloadable = sum(
            1 for r in fused[:20]
            if r.data.get("has_h5ad") or r.data.get("access_url")
        )
        if downloadable > 0:
            suggestions.append(Suggestion(
                type="download",
                text=(f"{downloadable} of these have directly-downloadable h5ad/rds files"
                      if en else f"其中{downloadable}个数据集有可直接下载的h5ad/rds文件"),
                action_query=f"download {parsed.original_text}",
                reason="downloadable_detected",
            ))

        # Cross-source comparison
        sources = set(s for r in fused for s in r.sources)
        if len(sources) > 1:
            suggestions.append(Suggestion(
                type="compare",
                text=(f"Results span {len(sources)} databases — compare their coverage?"
                      if en else f"结果来自{len(sources)}个数据库，是否比较各库数据覆盖？"),
                action_query=(f"compare databases {parsed.original_text}"
                              if en else f"统计各数据库 {parsed.original_text}"),
                reason="multi_source",
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
            dim = self._AGG_DIM_LABELS.get(group_key, group_key)
            chart_data: dict[str, int] = {}
            for r in fused:
                raw = r.data.get(group_key)
                # The NULL/unlabeled bucket is often the largest (e.g. ~52% of
                # samples lack tissue_standard); plotting it flattens every real
                # bar to a sliver. The summary already states its count, so the
                # chart shows the *labeled* distribution only.
                if raw in (None, "", "None"):
                    continue
                chart_data[str(raw)] = r.data.get("count", 0)
                if len(chart_data) >= 20:
                    break
            charts.append(ChartSpec(
                type="bar", title=f"按{dim}分布（已标注）", data=chart_data,
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


def _filters_to_dict(filters) -> dict:
    """Serialise QueryFilters → dict with only populated fields.

    Used in provenance so downstream evaluators can check filter extraction.
    """
    if filters is None:
        return {}
    out: dict[str, object] = {}
    for key in ("organisms", "tissues", "diseases", "cell_types", "assays",
                "source_databases", "sample_ids", "project_ids", "pmids",
                "dois", "development_stages",
                "sample_types", "disease_categories", "tissue_systems",
                "exclude_tissues", "exclude_diseases", "exclude_organisms",
                "exclude_source_databases", "exclude_sample_types",
                "exclude_disease_categories"):
        val = getattr(filters, key, None)
        if val:
            out[key] = list(val)
    # Scalar fields
    for key in ("sex", "free_text", "has_h5ad",
                "min_cells", "min_citation_count",
                "published_after", "published_before"):
        val = getattr(filters, key, None)
        if val not in (None, "", []):
            out[key] = val
    # Derived "virtual" fields — useful for evaluators looking for sample/type/etc
    # that aren't direct QueryFilters attributes but we can surface from the
    # database via pattern matching.
    return out


def _inline_params(sql: str, params: list) -> str:
    """Inline ? placeholders with their bound parameters for evaluator legibility.

    Best-effort: numeric values stay as numbers, strings get quoted with single
    quotes (with naive escaping). NULLs become NULL. Used for provenance
    recording so the agent_executed SQL is independently runnable.
    """
    if not sql or not params:
        return sql or ""
    out = []
    pi = 0
    in_str = False
    str_ch = ""
    for ch in sql:
        if in_str:
            out.append(ch)
            if ch == str_ch:
                in_str = False
            continue
        if ch in ("\"", "\x27"):
            in_str = True
            str_ch = ch
            out.append(ch)
            continue
        if ch == "?" and pi < len(params):
            v = params[pi]
            pi += 1
            if v is None:
                out.append("NULL")
            elif isinstance(v, (int, float)):
                out.append(str(v))
            else:
                s = str(v).replace("\x27", "\x27\x27")
                out.append("\x27" + s + "\x27")
            continue
        out.append(ch)
    return "".join(out)

