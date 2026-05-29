"""
ContextualSQLGenerator — 上下文感知SQL生成器

在基础SQLGenerator之上增加:
1. 数据统计感知 (基数估计 → 自动LIMIT)
2. 复杂JOIN支持 (BFS路径推导)
3. 子查询支持 (CellType EXISTS)
4. 增强聚合 (多字段GROUP BY + HAVING)
5. SQL预验证
6. LLM Prompt 知识注入 (字段分布 + 选择性提示)
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.models import (
    ParsedQuery,
    QueryIntent,
    ResolvedEntity,
    SQLCandidate,
)
from ..core.interfaces import ILLMClient
from ..dal.database import DatabaseAbstractionLayer
from ..knowledge.data_stats import DataStatsAnalyzer
from ..knowledge.cardinality import CardinalityEstimator
from ..knowledge.prompt_builder import KnowledgePromptBuilder
from .engine import SQLGenerator
from .subquery_builder import CellTypeQueryBuilder
from .aggregation_builder import AggregationBuilder, AggFunc, AggSpec
from .validator import SQLValidator

logger = logging.getLogger(__name__)


class ContextualSQLGenerator(SQLGenerator):
    """
    上下文感知SQL生成器

    继承基础SQLGenerator，增加:
    - 数据统计感知
    - CellType子查询
    - 增强聚合
    - SQL预验证
    - LLM知识注入
    """

    def __init__(
        self,
        dal: DatabaseAbstractionLayer,
        llm: Optional[ILLMClient] = None,
        stats_analyzer: Optional[DataStatsAnalyzer] = None,
        cardinality_est: Optional[CardinalityEstimator] = None,
        *,
        schema_config=None,
    ):
        super().__init__(dal, llm)
        self.stats = stats_analyzer
        self.cardinality = cardinality_est
        self._schema_config = schema_config

        # 从 SchemaConfig 获取主表名，否则使用默认值
        self._main_table = schema_config.main_table if schema_config else "unified_samples"
        self._main_view = (schema_config.main_view if schema_config else "v_sample_with_hierarchy") or "v_sample_with_hierarchy"

        self.celltype_builder = CellTypeQueryBuilder(schema_config=schema_config)
        self.agg_builder = AggregationBuilder()
        self.validator = SQLValidator(dal, schema_config=schema_config)
        self.prompt_builder = (
            KnowledgePromptBuilder(stats_analyzer, cardinality_est, schema_config=schema_config)
            if stats_analyzer else None
        )

    async def generate(
        self,
        query: ParsedQuery,
        resolved_entities: list[ResolvedEntity] | None = None,
    ) -> list[SQLCandidate]:
        """增强版SQL生成"""
        candidates: list[SQLCandidate] = []

        # Step 1: 基数估计 → 自动调整LIMIT (仅对超大结果集)
        estimated_size = 0
        if self.cardinality:
            try:
                filters_dict = self._filters_to_dict(query.filters)
                estimated_size = await self.cardinality.estimate_result_size(
                    self._main_table, filters_dict,
                )
                # 仅对超大结果集限制 (>100K)
                if estimated_size > 100000:
                    query.limit = min(query.limit, 100)
                logger.info("Cardinality estimate: ~%d rows", estimated_size)
            except Exception as e:
                logger.warning("Cardinality estimation failed: %s", e)

        # Step 2: 判断查询类型，选择生成策略
        query_type = self._classify_query_type(query)

        if query_type == "celltype_filter":
            ct_candidate = self._generate_celltype_query(query, resolved_entities)
            if ct_candidate:
                candidates.append(ct_candidate)
            # For cell-type filter queries, the EXISTS subquery against
            # unified_celltypes is semantically correct; the base `rule` path
            # uses the denormalised cell_type column which only carries the
            # *primary* cell-type annotation and silently misses samples whose
            # primary type differs from the query. Skip it.
            base_candidates = await super().generate(query, resolved_entities)
            # Only keep template/llm candidates; drop the rule path.
            for cand in base_candidates:
                if cand.method != "rule":
                    candidates.append(cand)

        elif query_type == "complex_aggregate":
            agg_candidate = self._generate_aggregate_query(query)
            if agg_candidate:
                candidates.append(agg_candidate)
            base_candidates = await super().generate(query, resolved_entities)
            candidates.extend(base_candidates)

        else:
            # Step 3: 始终生成基础候选
            base_candidates = await super().generate(query, resolved_entities)
            candidates.extend(base_candidates)

        # Step 4: 验证所有候选
        validated = []
        for candidate in candidates:
            result = self.validator.validate(candidate.sql, candidate.params)
            if result.is_valid:
                validated.append(candidate)
            else:
                logger.warning(
                    "SQL validation failed [%s]: %s",
                    candidate.method, result.errors,
                )

        # 如果全部验证失败，返回原始候选 (让执行器处理)
        return validated if validated else candidates

    def _classify_query_type(self, query: ParsedQuery) -> str:
        """分类查询类型"""
        f = query.filters

        # 细胞类型过滤: 需要子查询
        if f.cell_types and query.intent in (QueryIntent.SEARCH, QueryIntent.EXPLORE):
            return "celltype_filter"

        # 复杂聚合: 多字段GROUP BY 或 HAVING
        if (query.aggregation
                and query.intent == QueryIntent.STATISTICS
                and len(query.aggregation.group_by) > 1):
            return "complex_aggregate"

        return "standard"

    def _generate_celltype_query(
        self,
        query: ParsedQuery,
        resolved_entities: list[ResolvedEntity] | None = None,
    ) -> SQLCandidate | None:
        """生成含细胞类型过滤的查询 — uses indexed fast-path for tissue/disease/organism."""
        from .engine import (
            _TISSUE_KEYWORD_TO_STANDARD, _DISEASE_KEYWORD_TO_STANDARD,
            _DISEASE_KEYWORD_TO_CATEGORY, _ORGANISM_KEYWORD_TO_COMMON,
            _SPECIFIC_DISEASE_LIKE, _TISSUE_KEYWORD_TO_L1,
        )
        f = query.filters
        where_parts: list[str] = []
        params: list = []

        def _indexed(field: str, std_field: str, mapping: dict, values: list[str]):
            if not values:
                return
            indexed: list[str] = []
            unmapped: list[str] = []
            for v in values:
                k = v.lower().strip()
                m = mapping.get(k)
                if m is None:
                    unmapped.append(v)
                elif isinstance(m, list):
                    indexed.extend(m)
                else:
                    indexed.append(m)
            # Phase 19-C: drop expanded values that the user explicitly excluded
            if field == "tissue" and f.exclude_tissues:
                excl = {t.lower().strip() for t in f.exclude_tissues}
                indexed = [v for v in indexed if v.lower().strip() not in excl]
            if field == "disease" and f.exclude_diseases:
                excl = {t.lower().strip() for t in f.exclude_diseases}
                indexed = [v for v in indexed if v.lower().strip() not in excl]
            sub: list[str] = []
            if indexed:
                indexed = list(dict.fromkeys(indexed))
                placeholders = ", ".join("?" * len(indexed))
                sub.append(f"s.{std_field} IN ({placeholders})")
                params.extend(indexed)
            if unmapped:
                or_clauses = [f"s.{field} LIKE ?" for _ in unmapped]
                sub.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{v}%" for v in unmapped)
            if sub:
                where_parts.append("(" + " OR ".join(sub) + ")" if len(sub) > 1 else sub[0])

        # Phase 38: organ-level tissues route to the canonical anatomical roll-up
        # (tissue_standard_l1), exactly as engine.py's entity fast-path does — so
        # the tissue×cell-type path agrees with the tissue-only path AND with the
        # L1-based oracles. Without this the two code paths diverged: "brain
        # samples with macrophage annotations" matched only raw `tissue LIKE
        # '%brain%'` (16,374 → 331 with macrophages) instead of
        # tissue_standard_l1='brain' (39,960 → 2,348, matching oracle 2,354).
        # Non-organ / sub-region tissues (and strict_mode) fall back to the
        # leaf-level tissue_standard / raw LIKE handling below.
        _strict = bool(getattr(query, "strict_mode", False))
        _l1_tissues: list[str] = []
        _remaining_tissues: list[str] = []
        for v in (f.tissues or []):
            k = v.lower().strip()
            l1 = _TISSUE_KEYWORD_TO_L1.get(k)
            if l1 and not _strict:
                _l1_tissues.append(l1)
            else:
                _remaining_tissues.append(v)
        if _l1_tissues:
            _l1_tissues = list(dict.fromkeys(_l1_tissues))
            ph = ", ".join("?" * len(_l1_tissues))
            where_parts.append(f"s.tissue_standard_l1 IN ({ph})")
            params.extend(_l1_tissues)
        _indexed("tissue", "tissue_standard", _TISSUE_KEYWORD_TO_STANDARD, _remaining_tissues)
        tissue_handled_by_index = bool(f.tissues) and (
            bool(_l1_tissues)
            or any(v.lower().strip() in _TISSUE_KEYWORD_TO_STANDARD for v in _remaining_tissues)
        )
        # Disease — try category first, fall back to standard, then LIKE.
        # strict_mode forces LIKE on the raw disease column.
        # Phase 23-C: specific diseases (covid, alzheimer, diabetes, leukemia,
        # …) skip category widening — emit (disease_standard OR LIKE) only.
        # Phase 33: diseases the ontology resolved to concrete db_values (e.g.
        # "lung fibrosis" → "pulmonary fibrosis"). For these we must NOT also
        # emit a standalone literal LIKE on the raw term — the DB stores the
        # standardised name, so the literal matches nothing and AND-ing it with
        # the ontology IN() yields 0. Instead the ontology block below ORs the
        # literal with the resolved IN() in a single clause.
        _onto_disease_originals: set[str] = set()
        if resolved_entities:
            for _ent in resolved_entities:
                if _ent.original.entity_type == "disease" and _ent.db_values:
                    _onto_disease_originals.add(_ent.original.text.lower().strip())
        disease_handled_by_index = False
        if f.diseases:
            if query.strict_mode:
                or_clauses = ["s.disease LIKE ?" for _ in f.diseases]
                where_parts.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{v}%" for v in f.diseases)
            else:
                cat_vals: list[str] = []
                std_vals: list[str] = []
                like_tokens: list[str] = []
                unmapped: list[str] = []
                for d in f.diseases:
                    k = d.lower().strip()
                    if k in _SPECIFIC_DISEASE_LIKE:
                        if k in _DISEASE_KEYWORD_TO_STANDARD:
                            std_vals.append(_DISEASE_KEYWORD_TO_STANDARD[k])
                        like_tokens.append(_SPECIFIC_DISEASE_LIKE[k])
                        disease_handled_by_index = True
                    elif k in _DISEASE_KEYWORD_TO_CATEGORY:
                        cat_vals.append(_DISEASE_KEYWORD_TO_CATEGORY[k])
                        disease_handled_by_index = True
                    elif k in _DISEASE_KEYWORD_TO_STANDARD:
                        std_vals.append(_DISEASE_KEYWORD_TO_STANDARD[k])
                        disease_handled_by_index = True
                    else:
                        unmapped.append(d)
                sub: list[str] = []
                if cat_vals:
                    cat_vals = list(dict.fromkeys(cat_vals))
                    placeholders = ", ".join("?" * len(cat_vals))
                    sub.append(f"s.disease_category IN ({placeholders})")
                    params.extend(cat_vals)
                if std_vals:
                    std_vals = list(dict.fromkeys(std_vals))
                    placeholders = ", ".join("?" * len(std_vals))
                    sub.append(f"s.disease_standard IN ({placeholders})")
                    params.extend(std_vals)
                if like_tokens:
                    like_tokens = list(dict.fromkeys(like_tokens))
                    or_clauses = ["s.disease LIKE ?" for _ in like_tokens]
                    sub.append("(" + " OR ".join(or_clauses) + ")")
                    params.extend(f"%{t}%" for t in like_tokens)
                if unmapped:
                    # Skip the standalone literal LIKE for terms the ontology
                    # resolved (handled as an OR with the IN() below); keep it
                    # for genuinely unresolved terms so the query isn't dropped.
                    unmapped_like = [v for v in unmapped
                                     if v.lower().strip() not in _onto_disease_originals]
                    if unmapped_like:
                        or_clauses = ["s.disease LIKE ?" for _ in unmapped_like]
                        sub.append("(" + " OR ".join(or_clauses) + ")")
                        params.extend(f"%{v}%" for v in unmapped_like)
                if sub:
                    where_parts.append("(" + " OR ".join(sub) + ")" if len(sub) > 1 else sub[0])
        if f.organisms:
            commons: list[str] = []
            unmapped_org: list[str] = []
            for o in f.organisms:
                k = o.lower().strip()
                mapped = _ORGANISM_KEYWORD_TO_COMMON.get(k)
                if mapped:
                    commons.append(mapped)
                else:
                    unmapped_org.append(o)
            sub: list[str] = []
            if commons:
                placeholders = ", ".join("?" * len(commons))
                sub.append(f"s.organism_common IN ({placeholders})")
                params.extend(commons)
            if unmapped_org:
                or_clauses = ["s.organism LIKE ?" for _ in unmapped_org]
                sub.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{o}%" for o in unmapped_org)
            if sub:
                where_parts.append("(" + " OR ".join(sub) + ")" if len(sub) > 1 else sub[0])

        if f.source_databases:
            placeholders = ", ".join("?" * len(f.source_databases))
            where_parts.append(f"s.source_database IN ({placeholders})")
            params.extend(f.source_databases)

        if f.sample_types:
            # Phase 19-G: iPSC/PSC widening (see engine._build_where)
            expanded = list(f.sample_types)
            if "iPSC_derived" in expanded and "PSC_derived" not in expanded:
                expanded.append("PSC_derived")
            elif "PSC_derived" in expanded and "iPSC_derived" not in expanded:
                expanded.append("iPSC_derived")
            placeholders = ", ".join("?" * len(expanded))
            if "iPSC_derived" in expanded or "PSC_derived" in expanded:
                where_parts.append(
                    f"(s.sample_type IN ({placeholders}) "
                    f"OR s.cell_line_name LIKE '%iPSC%')"
                )
            else:
                where_parts.append(f"s.sample_type IN ({placeholders})")
            params.extend(expanded)

        if f.disease_categories:
            placeholders = ", ".join("?" * len(f.disease_categories))
            where_parts.append(f"s.disease_category IN ({placeholders})")
            params.extend(f.disease_categories)

        # Phase 33: developmental-stage filter. `development_stages` holds
        # canonical dev_stage_category values (adult / aged / juvenile /
        # neonatal / embryonic / fetal) — see _DEV_STAGE_KEYWORDS in engine.py.
        if f.development_stages:
            placeholders = ", ".join("?" * len(f.development_stages))
            where_parts.append(f"s.dev_stage_category IN ({placeholders})")
            params.extend(f.development_stages)

        if f.tissue_systems:
            placeholders = ", ".join("?" * len(f.tissue_systems))
            where_parts.append(f"s.tissue_system IN ({placeholders})")
            params.extend(f.tissue_systems)

        if f.exclude_sample_types:
            placeholders = ", ".join("?" * len(f.exclude_sample_types))
            where_parts.append(f"s.sample_type NOT IN ({placeholders})")
            params.extend(f.exclude_sample_types)

        if f.exclude_disease_categories:
            placeholders = ", ".join("?" * len(f.exclude_disease_categories))
            where_parts.append(
                f"(s.disease_category IS NULL OR s.disease_category NOT IN ({placeholders}))"
            )
            params.extend(f.exclude_disease_categories)

        # Phase 19-C: emit explicit NOT LIKE for excluded tissues/diseases —
        # in case the umbrella IN() above doesn't fully suppress, or the
        # excluded term appears in the raw column.
        if f.exclude_tissues:
            for t in f.exclude_tissues:
                where_parts.append(
                    "(s.tissue_standard IS NULL "
                    "OR s.tissue_standard != ?)"
                )
                params.append(t)
        if f.exclude_diseases:
            for d in f.exclude_diseases:
                where_parts.append(
                    "(s.disease IS NULL OR s.disease NOT LIKE ?)"
                )
                params.append(f"%{d}%")
        if f.exclude_organisms:
            for o in f.exclude_organisms:
                where_parts.append(
                    "(s.organism IS NULL OR s.organism NOT LIKE ?)"
                )
                params.append(f"%{o}%")

        if f.sex:
            if f.sex in ("male", "female"):
                where_parts.append("s.sex_normalized = ?")
                params.append(f.sex)
            else:
                where_parts.append("s.sex = ?")
                params.append(f.sex)

        if f.min_cells is not None:
            where_parts.append("s.n_cells >= ?")
            params.append(f.min_cells)

        # Phase 19-G: treatment-present filter
        if getattr(f, "treatment_present", None) is True:
            where_parts.append("(s.treatment IS NOT NULL AND s.treatment != '')")
        # Phase 19-G: require_disease — strict non-null disease_category
        if getattr(f, "require_disease", None) is True:
            where_parts.append("(s.disease_category IS NOT NULL)")
        if getattr(f, "min_series_cells", None) is not None:
            where_parts.append(
                "s.series_pk IN (SELECT pk FROM unified_series WHERE cell_count >= ?)"
            )
            params.append(f.min_series_cells)
        if getattr(f, "has_h5ad", None) is True:
            where_parts.append(
                "s.series_pk IN (SELECT pk FROM unified_series WHERE has_h5ad = 1)"
            )
        # Phase 23-C: assay filter (HRS-18 was missing this in celltype path)
        if f.assays:
            assay_tokens: list[str] = []
            for a in f.assays:
                head = a.split()[0] if a else a
                if head and head not in assay_tokens:
                    assay_tokens.append(head)
            or_clauses_a = []
            for t in assay_tokens:
                or_clauses_a.append("assay LIKE ? OR platform LIKE ?")
                params.extend([f"%{t}%", f"%{t}%"])
            where_parts.append(
                "s.series_pk IN (SELECT pk FROM unified_series WHERE "
                + " OR ".join(or_clauses_a) + ")"
            )
        if getattr(f, "exclude_assays", None):
            ex_tokens: list[str] = []
            for a in f.exclude_assays:
                head = a.split()[0] if a else a
                if head and head not in ex_tokens:
                    ex_tokens.append(head)
            or_clauses_a = []
            for t in ex_tokens:
                or_clauses_a.append("assay LIKE ? OR platform LIKE ?")
                params.extend([f"%{t}%", f"%{t}%"])
            where_parts.append(
                "(s.series_pk IS NULL OR s.series_pk NOT IN "
                "(SELECT pk FROM unified_series WHERE "
                + " OR ".join(or_clauses_a) + "))"
            )

        # Temporal filter (publication_date lives on unified_projects)
        if f.published_after or f.published_before:
            sub_parts = []
            if f.published_after:
                sub_parts.append("publication_date >= ?")
                params.append(f.published_after)
            if f.published_before:
                sub_parts.append("publication_date <= ?")
                params.append(f.published_before)
            where_parts.append(
                f"s.project_pk IN (SELECT pk FROM unified_projects WHERE "
                f"{' AND '.join(sub_parts)})"
            )

        # 添加本体扩展条件 (tissue / disease) — use as OR expansion, not AND
        onto_cell_type_terms: list[str] = []
        if resolved_entities:
            for ent in resolved_entities:
                if not ent.db_values:
                    continue
                if ent.original.entity_type in ("tissue", "disease"):
                    # If the field's indexed fast-path already applied (e.g.
                    # disease_category='neoplasm' or tissue_standard='liver'),
                    # skip the ontology IN() expansion — AND-ing it would
                    # restrict to the intersection of two overlapping sets,
                    # which often yields zero rows.
                    if ent.original.entity_type == "tissue" and tissue_handled_by_index:
                        continue
                    if ent.original.entity_type == "disease" and disease_handled_by_index:
                        continue
                    field = ent.original.entity_type
                    values = [v.raw_value for v in ent.db_values[:50]]
                    if not values:
                        continue
                    # Check whether the base LIKE filter already covers all
                    # ontology-expanded values. If so, the IN() would either
                    # be redundant or (worse) restrict to a subset of the LIKE
                    # matches. Skip in that case.
                    base_terms = f.tissues if field == "tissue" else f.diseases
                    if base_terms and all(
                        any(bt.lower() in v.lower() for bt in base_terms)
                        for v in values
                    ):
                        continue
                    # Otherwise OR the ontology expansions alongside the raw
                    # literal IN ONE clause — never as a separate AND clause
                    # (Phase 33: AND-ing dropped synonym queries like
                    # "lung fibrosis" → "pulmonary fibrosis" to zero rows).
                    placeholders = ", ".join("?" * len(values))
                    where_parts.append(
                        f"(s.{field} IN ({placeholders}) OR s.{field} LIKE ?)"
                    )
                    params.extend(values)
                    params.append(f"%{ent.original.text}%")
                elif ent.original.entity_type == "cell_type":
                    # Collect expanded cell-type labels so the EXISTS subquery
                    # can match across T cell → CD4+, CD8+, ... and the like.
                    onto_cell_type_terms.extend(v.raw_value for v in ent.db_values[:50])

        # 添加细胞类型EXISTS子查询 (合并 raw 输入 + ontology 扩展)
        # Phase 38: cell-type queries are *composition-membership* queries — a
        # single-cell sample CONTAINS many cell types (the unified_celltypes
        # composition has up to ~120 rows/sample), so "liver datasets with T cell
        # annotations" / "epithelial cells in lung" means "samples whose cell-type
        # composition includes that type", not "samples whose single dominant
        # cell_type column equals it". Filtering only the sample-level dominant
        # column systematically under-counted (MC07 145 vs oracle 498; ON07 334 vs
        # 1823). All 20 cell-type oracles use the composition JOIN, so we widen to
        # `(dominant LIKE  OR  EXISTS composition)`, which matches that convention.
        expanded_cell_types = list(dict.fromkeys(f.cell_types + onto_cell_type_terms))
        ct_filter, ct_params = self.celltype_builder.build_celltype_filter(
            expanded_cell_types, parent_alias="s", parent_pk="pk",
            use_subquery=True,
        )
        if ct_filter:
            where_parts.append(ct_filter)
            params.extend(ct_params)

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        sql = (
            f"SELECT s.* FROM {self._main_table} s\n"
            f"WHERE {where_sql}\n"
            f"LIMIT {min(max((query.limit or 100) * 10, 5000), 20000)}"
        )

        return SQLCandidate(sql=sql, params=params, method="celltype_subquery")

    def _generate_aggregate_query(self, query: ParsedQuery) -> SQLCandidate | None:
        """生成复杂聚合查询"""
        if not query.aggregation:
            return None

        agg = query.aggregation
        f = query.filters

        # 构建WHERE
        where_parts: list[str] = []
        params: list = []

        if f.tissues:
            or_clauses = ["tissue LIKE ?" for _ in f.tissues]
            where_parts.append(f"({' OR '.join(or_clauses)})")
            params.extend(f"%{t}%" for t in f.tissues)

        if f.diseases:
            or_clauses = ["disease LIKE ?" for _ in f.diseases]
            where_parts.append(f"({' OR '.join(or_clauses)})")
            params.extend(f"%{d}%" for d in f.diseases)

        if f.organisms:
            or_clauses = ["organism LIKE ?" for _ in f.organisms]
            where_parts.append(f"({' OR '.join(or_clauses)})")
            params.extend(f"%{o}%" for o in f.organisms)

        if f.source_databases:
            placeholders = ", ".join("?" * len(f.source_databases))
            where_parts.append(f"source_database IN ({placeholders})")
            params.extend(f.source_databases)

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        # 构建聚合规格
        aggregates = [(AggFunc.COUNT, "*", "count")]

        # 根据metric添加额外聚合
        if agg.metric == "sum":
            aggregates.append((AggFunc.SUM, "n_cells", "total_cells"))
        elif agg.metric == "avg":
            aggregates.append((AggFunc.AVG, "n_cells", "avg_cells"))
        else:
            # 默认也加上total_cells
            aggregates.append(
                (AggFunc.SUM, "CASE WHEN n_cells IS NOT NULL THEN n_cells ELSE 0 END", "total_cells")
            )

        spec = AggSpec(
            group_by=agg.group_by,
            aggregates=aggregates,
            order_by=[("count", "DESC")],
            limit=query.limit,
        )

        sql, agg_params = self.agg_builder.build(
            spec, f"FROM {self._main_table}", where_sql, params,
        )

        return SQLCandidate(sql=sql, params=agg_params, method="enhanced_aggregate")

    @staticmethod
    def _filters_to_dict(filters) -> dict[str, list[str]]:
        """转换QueryFilters为字典 (用于基数估计).

        Only includes filter fields that exist on the main table
        (unified_samples). `assay` lives on unified_series and should be
        estimated separately; including it here raises "no such column" errors.
        """
        result = {}
        if filters.tissues:
            result["tissue"] = filters.tissues
        if filters.diseases:
            result["disease"] = filters.diseases
        if filters.cell_types:
            # cell_type is on samples as denormalised column
            result["cell_type"] = filters.cell_types
        if filters.organisms:
            result["organism"] = filters.organisms
        if filters.source_databases:
            result["source_database"] = filters.source_databases
        if filters.sample_types:
            result["sample_type"] = filters.sample_types
        if filters.disease_categories:
            result["disease_category"] = filters.disease_categories
        if filters.tissue_systems:
            result["tissue_system"] = filters.tissue_systems
        # assay intentionally skipped — it's on unified_series, not unified_samples
        return result

    # ---------- LLM知识注入覆盖 ----------

    async def _from_llm(self, query, entities, plan) -> SQLCandidate | None:
        """覆盖父类LLM生成，注入数据统计知识到prompt。"""
        if not self.llm:
            return None

        ddl = self.dal.schema_inspector.get_ddl_summary()

        # 构建知识注入块
        knowledge_block = ""
        if self.prompt_builder:
            try:
                filters_dict = self._filters_to_dict(query.filters)
                knowledge_block = await self.prompt_builder.build_sql_knowledge_block(
                    table=self._main_table,
                    filters=filters_dict if filters_dict else None,
                )
            except Exception as e:
                logger.debug("Knowledge block build failed: %s", e)

        prompt = f"""Generate a SQLite query for this request.

Schema:
{ddl}

View {self._main_view} joins samples+series+projects. Use it for simple queries.

{knowledge_block}

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
- Use the Database Statistics above to choose appropriate values and LIMIT
- If a filter value doesn't appear in Top values, use LIKE for fuzzy matching
- Return ONLY the SQL, no explanation

SQL:"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                max_tokens=512,
            )

            sql = response.content.strip()
            if sql.startswith("```"):
                sql = sql.split("```")[1].strip()
                if sql.startswith("sql"):
                    sql = sql[3:].strip()
            sql = sql.rstrip(";")

            if not sql.upper().startswith("SELECT"):
                return None

            return SQLCandidate(sql=sql, params=[], method="llm_knowledge_enhanced")
        except Exception as e:
            logger.warning("Knowledge-enhanced LLM SQL generation failed: %s", e)
            return None
