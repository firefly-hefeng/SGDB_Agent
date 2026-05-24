"""
Coordinator Agent — V3 (Protocol-based DI)

端到端查询流水线:
用户输入 → 查询理解 → 本体解析 → SQL生成(FTS5) → 并行执行 → 跨库融合 → 答案合成

设计原则:
- 所有核心模块通过 Protocol 接口注入，支持独立测试和替换
- 提供 create() 工厂方法，自动构建完整依赖图
- 向后兼容: 旧的 __init__(dal=, llm=, ...) 签名仍可使用
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..core.models import (
    AgentResponse,
    FusedRecord,
    ParsedQuery,
    ProvenanceInfo,
    SessionContext,
    Suggestion,
)
from ..core.interfaces import (
    IAnswerSynthesizer,
    IFusionEngine,
    ILLMClient,
    IQueryParser,
    ISQLExecutor,
    ISQLGenerator,
)
from ..core.exceptions import SCeQTLError
from ..core.reasoning import ReasoningStep, ReasoningTrace
from ..dal.database import DatabaseAbstractionLayer
from ..synthesis.answer import AnswerSynthesizer

logger = logging.getLogger(__name__)


def _is_unparseable_query(parsed) -> bool:
    """True iff the parser found no positive entities/filters to anchor the
    query. Used by Phase 32 F15 to fast-fail nonsense queries instead of
    chasing the LLM through a 60-90s zero-result recovery round.
    """
    if not parsed:
        return True
    if parsed.intent.name in {"STATISTICS", "EXPLORE", "DOWNLOAD"}:
        # These intents are legitimate even with no filter constraints.
        return False
    if parsed.entities:
        return False
    if parsed.aggregation:
        return False
    if getattr(parsed, "ordering", None):
        return False
    f = parsed.filters
    for attr in (
        "tissues", "diseases", "organisms", "cell_types", "assays",
        "source_databases", "sample_types", "disease_categories",
        "tissue_systems", "project_ids", "sample_ids", "pmids", "dois",
    ):
        if getattr(f, attr, None):
            return False
    for attr in (
        "sex", "min_cells", "min_series_cells", "has_h5ad",
        "require_pmid", "require_doi", "require_h5ad",
        "treatment_present", "require_disease",
        "published_after", "published_before",
        "age_range", "free_text",
    ):
        v = getattr(f, attr, None)
        if v not in (None, "", False):
            return False
    return True


class CoordinatorAgent:
    """
    Agent 协调器 — Protocol-based dependency injection.

    支持两种构造方式:
    1. DI注入: CoordinatorAgent(parser=..., sql_gen=..., sql_exec=..., fusion=..., synthesizer=...)
    2. 工厂方法: CoordinatorAgent.create(dal=..., llm=..., ontology_cache_path=..., memory_db_path=...)
    """

    def __init__(
        self,
        *,
        parser: IQueryParser,
        sql_gen: ISQLGenerator,
        sql_exec: ISQLExecutor,
        fusion: IFusionEngine,
        synthesizer: IAnswerSynthesizer,
        ontology=None,
        episodic=None,
        semantic=None,
        dal: DatabaseAbstractionLayer | None = None,
        llm: ILLMClient | None = None,
        schema_knowledge=None,
    ):
        self.parser = parser
        self.sql_gen = sql_gen
        self.sql_exec = sql_exec
        self.fusion = fusion
        self.synthesizer = synthesizer
        self.ontology = ontology
        self.episodic = episodic
        self.semantic = semantic
        self.dal = dal
        self.llm = llm
        self.schema_knowledge = schema_knowledge

        # Session state
        self.working_memories: dict[str, object] = {}
        self._sessions: dict[str, SessionContext] = {}

        logger.info(
            "CoordinatorAgent initialized (ontology=%s, memory=%s, schema_knowledge=%s)",
            self.ontology is not None,
            self.episodic is not None,
            self.schema_knowledge is not None,
        )

    @classmethod
    def create(
        cls,
        dal: DatabaseAbstractionLayer,
        llm: ILLMClient | None = None,
        ontology_cache_path: str | Path | None = None,
        memory_db_path: str | Path | None = None,
        schema_knowledge_path: str | Path | None = None,
        enable_knowledge_layer: bool = True,
        stats_cache_path: str | Path | None = None,
        parser_mode: str = "auto",
    ) -> CoordinatorAgent:
        """
        工厂方法 — 自动构建完整依赖图。

        新增参数:
        - enable_knowledge_layer: 是否启用动态知识层 (DataStats + Cardinality + Feedback)
        - stats_cache_path: 统计缓存数据库路径
        - parser_mode: "auto" | "cascade" | "reasoning" | "v1" | "rule".
            "auto" = reasoning if LLM, else rule (Phase 14 default).
            "cascade" = LLM-on-demand: rule-first, escalate to LLM only when the
                calibrated confidence/complexity gate fires (Phase 40+; the
                eval-grounded optimal LLM-participation policy).
        """
        from ..understanding.parser import QueryParser
        from ..sql.engine import SQLGenerator, ParallelSQLExecutor
        from ..fusion.engine import CrossDBFusionEngine

        schema_context = dal.get_schema_summary()

        # Build SchemaConfig (dynamic schema abstraction)
        schema_config = None
        try:
            from ..core.schema_config import SchemaConfig
            schema_config = SchemaConfig.from_dal(dal)
            logger.info("SchemaConfig built: %d tables, %d core fields",
                        len(schema_config.tables), len(schema_config.core_fields))
        except Exception as e:
            logger.warning("Failed to build SchemaConfig: %s", e)

        # Load Schema Knowledge (optional)
        sk = None
        if schema_knowledge_path and Path(schema_knowledge_path).exists():
            try:
                from ..knowledge.schema_knowledge import SchemaKnowledge
                sk = SchemaKnowledge(schema_knowledge_path)
                logger.info("SchemaKnowledge loaded from %s", schema_knowledge_path)
            except Exception as e:
                logger.warning("Failed to load SchemaKnowledge: %s", e)

        # V3: Use V1-style parser (production-proven)
        # Phase 14: also support ReasoningParser via parser_mode="reasoning".
        # Schema tree is built lazily because it needs the DB path.
        schema_tree = None
        try:
            from ..knowledge.schema_tree import load_schema_tree, augment_from_db
            sk_path = schema_knowledge_path or "data/schema_knowledge.yaml"
            if Path(sk_path).exists():
                schema_tree = load_schema_tree(sk_path)
                # Pull live schema info from the DAL's underlying file
                db_path = getattr(dal, "db_path", None) or getattr(dal, "_db_path", None)
                if db_path and Path(db_path).exists():
                    augment_from_db(schema_tree, db_path)
                logger.info("SchemaKnowledgeTree built (Phase 14)")
        except Exception as e:
            logger.warning("SchemaKnowledgeTree init failed: %s", e)

        effective_mode = parser_mode
        if effective_mode == "auto":
            # Phase 40+: "auto" now selects the eval-grounded LLM-on-demand
            # cascade (rule-first, escalate only on the calibrated gate) instead
            # of always-LLM reasoning. On the cr_target gold the cascade beats
            # always-LLM by a wide margin AND calls the LLM on ~30% of queries,
            # so the interactive portal is both more accurate and much faster.
            effective_mode = "cascade" if llm else "rule"

        if effective_mode == "reasoning" and llm:
            try:
                from ..understanding.reasoning_parser import ReasoningParser
                parser = ReasoningParser(
                    llm=llm,
                    schema_tree=schema_tree,
                    rule_parser=QueryParser(),
                )
                logger.info("Using ReasoningParser (Phase 14 CoT)")
            except Exception as e:
                logger.warning("ReasoningParser init failed: %s — falling back to V1", e)
                effective_mode = "v1"

        if effective_mode == "cascade" and llm:
            # Phase 40+: LLM-on-demand. Run the rule parser first and escalate to
            # the LLM parser only when the calibrated confidence/complexity gate
            # fires — the eval-grounded optimal LLM participation policy.
            try:
                from ..understanding.v1_parser import V1QueryParser, build_live_vocab
                from ..understanding.cascade_parser import GatedCascadeParser
                try:
                    live_vocab = build_live_vocab(dal)
                except Exception:  # noqa: BLE001
                    live_vocab = None
                llm_parser = V1QueryParser(llm=llm, schema_knowledge=sk, live_vocab=live_vocab)
                parser = GatedCascadeParser(rule_parser=QueryParser(), llm_parser=llm_parser)
                logger.info("Using GatedCascadeParser (LLM-on-demand, confidence-gated)")
            except Exception as e:  # noqa: BLE001
                logger.warning("CascadeParser init failed: %s — falling back to V1", e)
                effective_mode = "v1"

        if effective_mode == "v1" and llm:
            try:
                from ..understanding.v1_parser import V1QueryParser, build_live_vocab
                # Phase 38: dynamic knowledge injection — read REAL field values
                # from the loaded DB so the LLM is anchored to actual vocabulary
                # (anti-hallucination) regardless of any stale schema_knowledge.yaml.
                try:
                    live_vocab = build_live_vocab(dal)
                    logger.info("Live vocab injected: %s", list(live_vocab.keys()))
                except Exception as e:  # noqa: BLE001
                    live_vocab = None
                    logger.warning("build_live_vocab failed (%s); LLM parser uses static SK", e)
                parser = V1QueryParser(llm=llm, schema_knowledge=sk, live_vocab=live_vocab)
                logger.info("Using V1QueryParser (production-proven LLM-first)")
            except Exception as e:
                logger.warning("V1Parser init failed, falling back to rule parser: %s", e)
                parser = QueryParser(llm=llm, schema_context=schema_context)
        elif effective_mode == "rule" or not llm:
            parser = QueryParser(llm=llm, schema_context=schema_context)

        # Phase 30.A — wrap any LLM-backed parser in a CachingParser so
        # repeat NL queries (theme tile clicks, example queries) skip
        # the 30–60 s reasoning round-trip. Rule-only parsers are fast
        # already and don't need caching.
        if effective_mode in ("reasoning", "v1", "cascade") and llm:
            try:
                from ..understanding.caching_parser import CachingParser
                parser = CachingParser(parser)
                logger.info("Parser wrapped with CachingParser (Phase 30.A)")
            except Exception as e:
                logger.warning("CachingParser init failed: %s", e)

        # Dynamic Knowledge Layer (NEW)
        stats_analyzer = None
        cardinality_est = None
        feedback_loop = None

        if enable_knowledge_layer:
            try:
                from ..knowledge.data_stats import DataStatsAnalyzer
                from ..knowledge.cardinality import CardinalityEstimator

                cache_path = str(stats_cache_path) if stats_cache_path else None
                if not cache_path and memory_db_path:
                    cache_path = str(Path(memory_db_path) / "stats_cache.db")

                stats_analyzer = DataStatsAnalyzer(dal, cache_db_path=cache_path)
                cardinality_est = CardinalityEstimator(stats_analyzer)
                logger.info("Knowledge layer enabled (stats_cache=%s)", cache_path)
            except Exception as e:
                logger.warning("Failed to init knowledge layer: %s", e)

        if enable_knowledge_layer and memory_db_path:
            try:
                from ..knowledge.feedback_loop import QueryFeedbackLoop
                feedback_loop = QueryFeedbackLoop(
                    str(Path(memory_db_path) / "feedback.db")
                )
                logger.info("QueryFeedbackLoop enabled")
            except Exception as e:
                logger.warning("Failed to init feedback loop: %s", e)

        # SQL Generator: use ContextualSQLGenerator if knowledge layer is available
        if stats_analyzer or cardinality_est:
            try:
                from ..sql.contextual_engine import ContextualSQLGenerator
                sql_gen = ContextualSQLGenerator(
                    dal=dal, llm=llm,
                    stats_analyzer=stats_analyzer,
                    cardinality_est=cardinality_est,
                    schema_config=schema_config,
                )
                logger.info("Using ContextualSQLGenerator (knowledge-aware)")
            except Exception as e:
                logger.warning("ContextualSQLGenerator init failed, using base: %s", e)
                sql_gen = SQLGenerator(dal=dal, llm=llm, schema_config=schema_config)
        else:
            sql_gen = SQLGenerator(dal=dal, llm=llm, schema_config=schema_config)

        fallback_view = (schema_config.main_view if schema_config else "v_sample_with_hierarchy") or "v_sample_with_hierarchy"
        sql_exec = ParallelSQLExecutor(dal=dal, fallback_view=fallback_view)
        fusion = CrossDBFusionEngine(dal=dal)
        synthesizer = AnswerSynthesizer(llm=llm)

        # Ontology resolver (optional)
        ontology = None
        if ontology_cache_path and Path(ontology_cache_path).exists():
            try:
                from ..ontology.resolver import OntologyResolver
                ontology = OntologyResolver(ontology_cache_path, llm=llm)
                logger.info("OntologyResolver loaded from %s", ontology_cache_path)
            except Exception as e:
                logger.warning("Failed to load OntologyResolver: %s", e)

        # Memory system (optional)
        episodic = None
        semantic = None
        if memory_db_path:
            try:
                from ..memory.episodic import EpisodicMemory
                from ..memory.semantic import SemanticMemory
                mem_path = Path(memory_db_path)
                mem_path.mkdir(parents=True, exist_ok=True)
                episodic = EpisodicMemory(mem_path / "episodic.db")
                semantic = SemanticMemory(mem_path / "semantic.db")
                logger.info("Memory system loaded from %s", memory_db_path)
            except Exception as e:
                logger.warning("Failed to load memory system: %s", e)

        instance = cls(
            parser=parser,
            sql_gen=sql_gen,
            sql_exec=sql_exec,
            fusion=fusion,
            synthesizer=synthesizer,
            ontology=ontology,
            episodic=episodic,
            semantic=semantic,
            dal=dal,
            llm=llm,
            schema_knowledge=sk,
        )
        instance.schema_tree = schema_tree
        instance.parser_mode = effective_mode

        # Attach knowledge layer components for external access
        instance.stats_analyzer = stats_analyzer
        instance.cardinality_est = cardinality_est
        instance.feedback_loop = feedback_loop

        # Attach KnowledgePromptBuilder for prompt injection
        instance.prompt_builder = None
        if stats_analyzer:
            try:
                from ..knowledge.prompt_builder import KnowledgePromptBuilder
                instance.prompt_builder = KnowledgePromptBuilder(
                    stats_analyzer, cardinality_est,
                    schema_config=schema_config,
                )
                logger.info("KnowledgePromptBuilder attached")
            except Exception as e:
                logger.warning("Failed to init KnowledgePromptBuilder: %s", e)

        return instance

    def _get_working_memory(self, session_id: str):
        """Get or create WorkingMemory for a session."""
        if session_id not in self.working_memories:
            try:
                from ..memory.working import WorkingMemory
                self.working_memories[session_id] = WorkingMemory(session_id)
            except ImportError:
                return None
        return self.working_memories[session_id]

    async def query(
        self,
        user_input: str,
        session_id: str = "default",
        user_id: str = "anonymous",
        *,
        limit: int | None = None,
    ) -> AgentResponse:
        """
        端到端查询入口

        Pipeline:
        1. Parse → 2. Ontology Resolve → 3. Generate SQL → 4. Execute → 5. Fuse → 6. Synthesize

        Args:
            limit: optional override for the parsed query's display limit.
                   The default 100 (set by the parser) is right for the UI;
                   benchmarks may want a larger value to evaluate top-K
                   precision against larger oracle samples.
        """
        t0 = time.perf_counter()

        # Phase 14: build a reasoning trace alongside the pipeline so the
        # frontend / evaluators can see what the agent actually decided.
        trace = ReasoningTrace()

        # Load session context
        context = self._sessions.get(session_id, SessionContext(session_id=session_id))
        wmem = self._get_working_memory(session_id)

        if wmem:
            context = wmem.get_context()

        try:
            # Step 1: Query Understanding (V1Parser handles all enrichment)
            parse_step = trace.start(
                "parse", f"Parse user query: \"{user_input[:80]}\"",
                input={"text": user_input, "session_id": session_id},
            )
            parsed = await self.parser.parse(user_input, context)
            if limit is not None:
                parsed.limit = limit
            parse_step.output = {
                "intent": parsed.intent.name,
                "entity_count": len(parsed.entities),
                "filter_keys": [k for k, v in parsed.filters.__dict__.items()
                                if v not in (None, [], "", False)],
                "confidence": parsed.confidence,
                "method": parsed.parse_method,
                "strict_mode": parsed.strict_mode,
            }
            parse_step.confidence = parsed.confidence
            parse_step.rationale = (
                f"parser={parsed.parse_method}; "
                f"{len(parsed.entities)} entities; "
                f"strict={parsed.strict_mode}"
            )
            parse_step.end()
            logger.info(
                "Parsed: intent=%s, entities=%d, confidence=%.2f, method=%s",
                parsed.intent.name, len(parsed.entities),
                parsed.confidence, parsed.parse_method,
            )

            # If V1Parser returned low confidence, re-parse with rule parser
            if parsed.confidence < 0.5 and parsed.parse_method != "rule":
                from ..understanding.parser import QueryParser
                rule_parser = QueryParser()
                rule_result = await rule_parser.parse(user_input, context)
                if rule_result.confidence > parsed.confidence:
                    correction = trace.correction(
                        replaces=parse_step.step_id,
                        title="Rule parser supersedes low-confidence LLM parse",
                        rationale=(
                            f"V1 confidence {parsed.confidence:.2f} < 0.5; "
                            f"rule parser {rule_result.confidence:.2f} chosen"
                        ),
                        new_output={
                            "intent": rule_result.intent.name,
                            "entity_count": len(rule_result.entities),
                            "confidence": rule_result.confidence,
                            "method": rule_result.parse_method,
                        },
                    )
                    correction.confidence = rule_result.confidence
                    parsed = rule_result
                    logger.info("Re-parsed with rule parser: confidence=%.2f", parsed.confidence)

            # Merge rule-parser features that V1 doesn't extract: negation
            # (exclude_*), temporal filters, strict_mode, entities. Only
            # augment — never overwrite V1's filters.
            if parsed.parse_method != "rule":
                try:
                    from ..understanding.parser import QueryParser
                    aux = await QueryParser().parse(user_input, context)
                    f, af = parsed.filters, aux.filters
                    for attr in ("exclude_tissues", "exclude_diseases",
                                 "exclude_organisms", "exclude_source_databases",
                                 "exclude_sample_types", "exclude_disease_categories",
                                 "sample_types", "disease_categories",
                                 "tissue_systems"):
                        vals = getattr(af, attr, None)
                        if vals and not getattr(f, attr, None):
                            setattr(f, attr, list(vals))
                    # Augment positive filters when V1 missed mentions the
                    # rule parser caught (e.g. "from GEO" → source_databases).
                    # Phase 33: also accession IDs — a pasted "GSE149614" /
                    # "PRJNA625551" / "GSM…" must filter by project/sample id,
                    # not become a free_text LIKE that matches nothing.
                    for attr in ("source_databases", "cell_types",
                                 "project_ids", "sample_ids", "pmids"):
                        vals = getattr(af, attr, None)
                        if vals and not getattr(f, attr, None):
                            setattr(f, attr, list(vals))
                    if af.published_after and not f.published_after:
                        f.published_after = af.published_after
                    if af.published_before and not f.published_before:
                        f.published_before = af.published_before
                    if af.sex and not f.sex:
                        f.sex = af.sex
                    # Phase 33: numeric cell-count thresholds. The LLM sometimes
                    # emits "at least 100000 cells" as a bogus free_text filter
                    # expression ("cell_count >= 100000") instead of the
                    # structured min_cells/min_series_cells — which then becomes
                    # a LIKE that matches nothing. Merge the rule parser's
                    # deterministic extraction when V1 missed it.
                    if af.min_cells and not f.min_cells:
                        f.min_cells = af.min_cells
                    if getattr(af, "min_series_cells", None) and not getattr(f, "min_series_cells", None):
                        f.min_series_cells = af.min_series_cells
                    # Phase 33: file-availability flag. The LLM sometimes drops
                    # "with h5ad files" into free_text (→ a LIKE that matches
                    # nothing) instead of the structured has_h5ad flag.
                    if af.has_h5ad is True and f.has_h5ad is None:
                        f.has_h5ad = True
                    # Drop a free_text that's actually a structured concept the
                    # rule parser already captured (a comparison/cell-count
                    # expression, or a file-format keyword). Real search terms
                    # don't contain ">=" / "cell_count" / "h5ad" / "rds".
                    ft = (f.free_text or "")
                    ftl = ft.lower()
                    import re as _re_acc
                    # An accession the rule parser already captured structurally
                    # (project/sample id) — dropping it from free_text avoids an
                    # AND'd LIKE that matches nothing.
                    accession_captured = bool(
                        (f.project_ids or f.sample_ids)
                        and _re_acc.fullmatch(
                            r"(gse|gsm|prjna|prjeb|srr|srs|srp|e-\w+-)\d*[\w-]*",
                            ftl.strip(),
                        )
                    )
                    looks_like_expr = (
                        any(op in ft for op in (">=", "<=", ">", "<", "cell_count", "n_cells"))
                        or ((af.min_cells or getattr(af, "min_series_cells", None))
                            and any(ch.isdigit() for ch in ft) and "cell" in ftl)
                        or (f.has_h5ad is True and ("h5ad" in ftl or "rds" in ftl
                            or "matrix file" in ftl or "download" in ftl))
                        or accession_captured
                    )
                    if ft and looks_like_expr:
                        f.free_text = None
                    if aux.strict_mode and not parsed.strict_mode:
                        parsed.strict_mode = True
                    if aux.entities and not parsed.entities:
                        parsed.entities = aux.entities
                except Exception as e:
                    logger.debug("Auxiliary rule-parse merge skipped: %s", e)

            # Phase 33: developmental-stage keywords ("pediatric", "adult",
            # "fetal", …). Neither parser extracts these, but the data is rich
            # (dev_stage_category). Runs for ANY parser path; only fills when the
            # parser left development_stages empty.
            if not parsed.filters.development_stages:
                try:
                    from ..sql.engine import (
                        extract_dev_stage_categories, _DEV_STAGE_KEYWORDS,
                    )
                    ds = extract_dev_stage_categories(user_input)
                    if ds:
                        parsed.filters.development_stages = ds
                        logger.info("Dev-stage keywords → %s", ds)
                        # Drop a free_text that's just the stage keyword(s) the
                        # LLM echoed (e.g. "pediatric") — now captured
                        # structurally, the redundant FTS match only over-narrows.
                        ft = (parsed.filters.free_text or "").lower().strip()
                        if ft:
                            _generic = {"samples", "sample", "patients", "patient",
                                        "donors", "donor", "data", "datasets",
                                        "dataset", "subjects", "cells"}
                            ft_words = [w for w in ft.split() if w not in _generic]
                            if ft_words and all(w in _DEV_STAGE_KEYWORDS for w in ft_words):
                                parsed.filters.free_text = None
                except Exception as e:
                    logger.debug("Dev-stage extraction skipped: %s", e)

            # NB (Phase 33): a *general* free_text de-duplication (drop free_text
            # whose tokens are all covered by structured filters) was tried and
            # REJECTED by the gold benchmark — cr_target 92.29% → 90.12%. Reason:
            # free_text sometimes adds genuine recall via FTS (e.g. cell-type-
            # ontology-01 dropped 89.7%→87.6%), so it is NOT pure over-narrowing.
            # Only the *targeted* sanitizers above (filter-expression / accession
            # / file-format / stage echoes) are kept — those drop genuinely
            # useless free_text and are individually verified-beneficial.

            # Step 2: Ontology Resolution
            resolved_entities = None
            ontology_expansions = []
            if self.ontology and parsed.entities:
                onto_step = trace.start(
                    "ontology", f"Resolve {len(parsed.entities)} entities against ontology cache",
                    input={"entities": [e.text for e in parsed.entities]},
                )
                resolved_entities = self.ontology.resolve_all(parsed.entities)
                for re_ in resolved_entities:
                    if re_.ontology_term:
                        # Surface the actual expanded labels — evaluators rely
                        # on this to verify ontology coverage (e.g. T cell →
                        # CD4+ T cell, CD8+ T cell, regulatory T cell, ...).
                        expanded_labels = []
                        for v in re_.db_values:
                            if v.raw_value:
                                expanded_labels.append(v.raw_value)
                        # Cap at 30 to keep provenance JSON reasonable
                        expanded_labels = expanded_labels[:30]
                        ontology_expansions.append({
                            "original": re_.original.text,
                            "ontology_id": re_.ontology_term.ontology_id,
                            "ontology": re_.ontology_term.ontology_source,
                            "label": re_.ontology_term.label,
                            "expanded_terms": expanded_labels,
                            "db_values_count": len(re_.db_values),
                            "total_samples": re_.total_sample_count,
                        })
                onto_step.output = {
                    "expansions": [
                        {"original": e["original"],
                         "term": e["label"],
                         "expanded_count": e["db_values_count"]}
                        for e in ontology_expansions
                    ],
                }
                onto_step.rationale = (
                    f"{len(ontology_expansions)} of {len(parsed.entities)} "
                    f"entities resolved to ontology terms"
                )
                onto_step.status = "ok" if ontology_expansions else "warn"
                onto_step.end()
                if ontology_expansions:
                    logger.info("Ontology resolved %d entities", len(ontology_expansions))

            # Step 2b: Cardinality pre-estimate (for feedback loop)
            estimated_rows = 0
            cardinality_est = getattr(self, "cardinality_est", None)
            if cardinality_est:
                try:
                    from ..sql.contextual_engine import ContextualSQLGenerator
                    filters_dict = ContextualSQLGenerator._filters_to_dict(parsed.filters)
                    main_table = getattr(self.sql_gen, '_main_table', 'unified_samples')
                    estimated_rows = await cardinality_est.estimate_result_size(
                        main_table, filters_dict,
                    )
                except Exception:
                    pass

            # Step 3: SQL Generation
            sql_step = trace.start(
                "sql_gen", "Generate SQL candidate(s) from parsed query",
                input={"intent": parsed.intent.name,
                       "filter_keys": [k for k, v in parsed.filters.__dict__.items()
                                       if v not in (None, [], "", False)]},
            )
            candidates = await self.sql_gen.generate(parsed, resolved_entities)
            sql_step.output = {
                "candidate_count": len(candidates),
                "methods": [c.method for c in candidates],
                "first_sql_preview": (candidates[0].sql[:240] + "...") if candidates else "",
            }
            sql_step.rationale = (
                f"{len(candidates)} candidate(s) emitted; "
                f"strategies: {', '.join({c.method for c in candidates})}"
            )
            sql_step.end()
            logger.info("Generated %d SQL candidates", len(candidates))

            # Step 4: Parallel Execution
            exec_step = trace.start(
                "execute", f"Execute {len(candidates)} candidate(s) in parallel",
            )
            exec_result = await self.sql_exec.execute(candidates)
            exec_step.output = {
                "row_count": exec_result.row_count,
                "method": exec_result.method,
                "exec_time_ms": round(exec_result.exec_time_ms, 1),
                "sql": (exec_result.sql or "")[:240],
            }
            exec_step.status = "ok" if exec_result.row_count > 0 else "warn"
            exec_step.rationale = (
                f"{exec_result.row_count} rows via {exec_result.method} "
                f"in {exec_result.exec_time_ms:.0f}ms"
            )
            exec_step.end()
            logger.info(
                "Executed: %d rows, method=%s, %.0fms",
                exec_result.row_count, exec_result.method, exec_result.exec_time_ms,
            )

            # Step 4b: Self-correction — zero-result recovery + oversize warning.
            # Phase 14/19-A: unified correction triggers. Safe substitutions
            # replace; broaden options become Suggestions deferred to synth.
            #
            # Phase 32 F15: fast-fail. If the parser couldn't extract any
            # entities AND the filters are empty, there's nothing to relax
            # or recover — skip the recovery path (which would otherwise
            # cost another ~60-90s LLM round-trip via recover_zero_result).
            zero_result_suggestions: list[Suggestion] = []
            if exec_result.row_count == 0 and not _is_unparseable_query(parsed):
                corrected = await self._correct_zero_result(
                    parsed, exec_result, resolved_entities, context, trace, exec_step,
                )
                if corrected is not None:
                    if len(corrected) == 3:
                        parsed, exec_result, zero_result_suggestions = corrected
                    else:
                        parsed, exec_result = corrected
            elif exec_result.row_count == 0:
                logger.info(
                    "Zero-result fast-fail: no extractable entities/filters "
                    "for query %r — skipping LLM-driven recovery",
                    parsed.original_text,
                )

            # C1 (Phase 41): a non-human organism honest-zero is the dual-agent
            # HANDOFF moment — the curated catalog is human-only, but the Discover
            # agent federates live multi-species archives. Surface it explicitly so
            # the 0 reads as an honest answer + a route forward, not a dead end.
            if exec_result.row_count == 0 and self._is_nonhuman_organism_zero(parsed):
                orgs = ", ".join(parsed.filters.organisms) or "this organism"
                zero_result_suggestions.append(Suggestion(
                    type="related",
                    text=(f"The curated catalog is human-only, so there are 0 results for "
                          f"{orgs}. Search live multi-species archives with the Discover agent."),
                    action_query=parsed.original_text,
                    reason="non_human_organism_human_only_catalog",
                ))

            # Oversize warning — do not silently truncate, surface it in the trace
            if exec_result.row_count > 50000 and not parsed.aggregation:
                warn = ReasoningStep(
                    stage="correct",
                    title=f"Result set is very large ({exec_result.row_count:,} rows)",
                    status="warn",
                    rationale=(
                        "query is broad and non-aggregated; consider narrowing"
                        " by tissue_standard / disease_category / source_database"
                    ),
                    output={"row_count": exec_result.row_count},
                )
                warn.end()
                trace.add(warn)

            # Validation failure correction
            if exec_result.validation and not exec_result.validation.is_valid:
                vstep = ReasoningStep(
                    stage="correct",
                    title=f"SQL validation failed: {exec_result.validation.issue}",
                    status="error",
                    rationale=exec_result.validation.note
                              or exec_result.validation.suggestion,
                    correction_of=exec_step.step_id,
                )
                vstep.end()
                trace.add(vstep)

            # Step 5: Cross-DB Fusion
            fuse_step = trace.start(
                "fuse", f"Cross-DB dedup + interleave on {exec_result.row_count} rows",
            )
            fused = self.fusion.fuse(exec_result.rows)
            dedup_pct = (1 - len(fused) / max(exec_result.row_count, 1)) * 100
            fuse_step.output = {
                "raw_count": exec_result.row_count,
                "fused_count": len(fused),
                "dedup_rate_pct": round(dedup_pct, 1),
            }
            fuse_step.rationale = (
                f"{exec_result.row_count} → {len(fused)} after hash dedup + "
                f"round-robin interleave ({dedup_pct:.0f}% dedup)"
            )
            fuse_step.end()
            logger.info(
                "Fused: %d → %d records (%.0f%% dedup)",
                exec_result.row_count, len(fused), dedup_pct,
            )

            # Step 6: Answer Synthesis (via injected synthesizer)
            synth_step = trace.start(
                "synthesize", "Compose answer + suggestions",
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            response = self.synthesizer.synthesize_from_execution(
                parsed, fused, exec_result, elapsed_ms, ontology_expansions,
            )
            # Attach the ParsedQuery so callers (e.g. advanced_search) can
            # surface conditions back to the UI without re-parsing.
            response._parsed_query = parsed
            synth_step.output = {
                "summary_length": len(response.summary or ""),
                "suggestion_count": len(response.suggestions),
                "chart_count": len(response.charts),
                "total_count": response.total_count,
                "displayed_count": response.displayed_count,
            }
            synth_step.rationale = (
                f"{response.total_count} total, "
                f"{response.displayed_count} displayed; "
                f"{len(response.suggestions)} suggestion(s)"
            )
            synth_step.end()

            # Stash trace into provenance + finalise confidence.
            trace.final_confidence = parsed.confidence
            response.provenance.reasoning_trace = trace.to_dict()

            # Phase 19-A: surface deferred zero-result broaden suggestions
            if zero_result_suggestions:
                response.suggestions = list(response.suggestions or []) + \
                    zero_result_suggestions

            # Step 6b: LLM-generated suggestions
            try:
                from ..understanding.llm_parser import LLMQueryParser
                if isinstance(self.parser, LLMQueryParser) and fused:
                    suggestions = await self.parser.generate_suggestions(
                        parsed, len(fused), response.summary,
                    )
                    if suggestions:
                        response.suggestions = suggestions
            except ImportError:
                pass
            except Exception as e:
                logger.warning("LLM suggestion generation error: %s", e)

            # Update memories
            self._update_memories(
                session_id, user_id, parsed, fused, exec_result, elapsed_ms, wmem,
                estimated_rows=estimated_rows,
            )

            return response

        except SCeQTLError as e:
            logger.error("Query failed at stage [%s]: %s", e.stage, e, exc_info=True)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            trace.add_step = None  # noop placeholder; trace already captures up to failure
            return AgentResponse(
                summary=f"查询处理出错 [{e.stage}]: {str(e)}",
                error=str(e),
                provenance=ProvenanceInfo(
                    original_query=user_input,
                    execution_time_ms=elapsed_ms,
                    reasoning_trace=trace.to_dict(),
                ),
            )
        except Exception as e:
            logger.error("Query failed: %s", e, exc_info=True)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return AgentResponse(
                summary=f"查询处理出错: {str(e)}",
                error=str(e),
                provenance=ProvenanceInfo(
                    original_query=user_input,
                    execution_time_ms=elapsed_ms,
                    reasoning_trace=trace.to_dict(),
                ),
            )

    def _update_memories(
        self,
        session_id: str,
        user_id: str,
        parsed: ParsedQuery,
        fused: list[FusedRecord],
        exec_result,
        elapsed_ms: float,
        wmem,
        estimated_rows: int = 0,
    ):
        """Update all memory layers after a query."""
        # Feedback loop — record execution for cardinality calibration
        feedback_loop = getattr(self, "feedback_loop", None)
        if feedback_loop:
            try:
                pattern = self._generalize_pattern(parsed)
                filters_dict = {}
                f = parsed.filters
                if f.tissues:
                    filters_dict["tissue"] = f.tissues
                if f.diseases:
                    filters_dict["disease"] = f.diseases
                if f.cell_types:
                    filters_dict["cell_type"] = f.cell_types
                if f.organisms:
                    filters_dict["organism"] = f.organisms

                feedback_loop.record_execution(
                    query_pattern=pattern,
                    sql=exec_result.sql or "",
                    estimated_rows=estimated_rows,
                    actual_rows=exec_result.row_count,
                    execution_time_ms=exec_result.exec_time_ms,
                    filters_used=filters_dict,
                    intent=parsed.intent.name,
                )
            except Exception as e:
                logger.warning("Feedback loop recording failed: %s", e)

        # Working memory
        if wmem:
            wmem.add_turn(parsed, fused, exec_result.method, elapsed_ms)

        # Session context
        ctx = self._sessions.get(session_id, SessionContext(session_id=session_id))
        ctx.active_filters = parsed.filters
        ctx.last_result_count = len(fused)
        ctx.turns.append({
            "input": parsed.original_text,
            "intent": parsed.intent.name,
            "result_count": len(fused),
        })
        # Phase 14: persist the schema scope — the union of fields the user
        # has touched across this session. The next-turn parser uses this
        # to prioritise the same subtree (carry-over schema awareness).
        active_fields = set(ctx.active_schema_fields or [])
        for attr in (
            "tissues", "diseases", "organisms", "cell_types", "assays",
            "source_databases", "sample_types", "disease_categories",
            "tissue_systems",
        ):
            if getattr(parsed.filters, attr, None):
                active_fields.add(attr.rstrip("s") if not attr.endswith("ies") else attr)
        # Also surface temporal / strict scope for downstream prompts.
        if parsed.filters.published_after or parsed.filters.published_before:
            active_fields.add("publication_date")
        if parsed.strict_mode:
            active_fields.add("strict_mode")
        ctx.active_schema_fields = sorted(active_fields)
        # Capture last source mix for follow-up "show me only the GEO ones" turns.
        if fused:
            dist: dict[str, int] = {}
            for r in fused[:200]:
                for s in r.sources:
                    dist[s] = dist.get(s, 0) + 1
            ctx.last_source_distribution = dist
        self._sessions[session_id] = ctx

        # Episodic memory
        if self.episodic:
            try:
                self.episodic.record_query(
                    user_id=user_id,
                    session_id=session_id,
                    query=parsed,
                    result_count=len(fused),
                    sql_method=exec_result.method,
                    exec_time_ms=elapsed_ms,
                )
            except Exception as e:
                logger.warning("Episodic memory update failed: %s", e)

        # Semantic memory — learn from successful queries
        if self.semantic and exec_result.row_count > 0:
            try:
                pattern = self._generalize_pattern(parsed)
                self.semantic.record_successful_query(
                    intent=parsed.intent.name,
                    pattern=pattern,
                    sql=exec_result.sql,
                    exec_time_ms=elapsed_ms,
                )
            except Exception as e:
                logger.warning("Semantic memory update failed: %s", e)

    @staticmethod
    def _generalize_pattern(parsed: ParsedQuery) -> str:
        """Generalize a query into a reusable pattern description."""
        parts = [parsed.intent.name]
        f = parsed.filters
        if f.tissues:
            parts.append("tissue_filter")
        if f.diseases:
            parts.append("disease_filter")
        if f.cell_types:
            parts.append("cell_type_filter")
        if f.assays:
            parts.append("assay_filter")
        if f.source_databases:
            parts.append("source_filter")
        if parsed.aggregation:
            parts.append(f"group_by_{parsed.aggregation.group_by[0]}")
        return "+".join(parts)

    # ─── Self-correction (Phase 14, Phase 19-A revised) ─────────────────
    # Organism strings that mean "human" — the curated catalog is human-only.
    _HUMAN_ORGANISM = {"homo sapiens", "human", "h. sapiens", "h sapiens", "人源", "人类", "人的"}

    @classmethod
    def _is_nonhuman_organism_zero(cls, parsed: ParsedQuery) -> bool:
        """True if the parse carries a non-human organism filter. The curated
        catalog is human-only, so such a query legitimately returns 0 — an
        honest-zero that must STAND (and trigger a Discover handoff), never be
        'recovered' into the wrong human count (the organism honest-zero bug)."""
        orgs = getattr(getattr(parsed, "filters", None), "organisms", None) or []
        return any(str(o).strip().lower() not in cls._HUMAN_ORGANISM for o in orgs)

    @staticmethod
    def _recovery_preserves_organism(orig: ParsedQuery, cand: ParsedQuery) -> bool:
        """A zero-result LLM recovery is valid only if it PRESERVES the organism
        constraint. If the LLM dropped it, the honest-zero is correct and the
        recovery would return a wrong, over-broad count — so reject it."""
        o = {str(x).strip().lower() for x in (getattr(orig.filters, "organisms", None) or [])}
        if not o:
            return True
        c = {str(x).strip().lower() for x in (getattr(cand.filters, "organisms", None) or [])}
        return o.issubset(c)

    async def _correct_zero_result(
        self,
        parsed: ParsedQuery,
        exec_result,
        resolved_entities,
        context: SessionContext,
        trace: ReasoningTrace,
        exec_step: ReasoningStep,
    ):
        """Recover from a zero-result query — semantics-preserving substitutions
        replace the primary result; semantic-altering ones become *suggestions*
        only (not substituted into total_count). This keeps the agent honest
        when the user's literal query has zero matches in the DB.

        Strategies that **replace** the primary result (safe — same semantic
        intent, narrow internal widening):
          A. drop strict_mode (relax literal-LIKE → umbrella/IN ontology paths)
          B. LLM-driven rewrite (when LLMQueryParser is the parser; the LLM
             rewrites synonyms while preserving intent)

        Strategies that surface as **suggestions only** (different intent —
        the user asked for X∩Y∩Z and got 0, so suggest broadening to X∩Y
        instead of silently substituting it):
          S1. drop the most specific positive filter (cell_types > assays >
              diseases > tissues > disease_categories > tissue_systems)
          S2. drop min_series_cells / min_cells thresholds (often the user
              over-specified the count cutoff)

        Returns:
          (parsed_new, exec_result_new) when a safe correction recovered
          rows, OR (parsed, exec_result, suggestions) when only broaden-
          suggestions are available, OR None when nothing can be offered.
        """
        from copy import deepcopy

        # ---- Safe substitutions ----------------------------------------------
        substitutions: list[tuple[str, ParsedQuery]] = []

        if parsed.strict_mode:
            relaxed = deepcopy(parsed)
            relaxed.strict_mode = False
            substitutions.append(("drop_strict_mode", relaxed))

        try:
            from ..understanding.llm_parser import LLMQueryParser
            if isinstance(self.parser, LLMQueryParser):
                llm_recovered = await self.parser.recover_zero_result(
                    parsed, exec_result.sql, context,
                )
                if llm_recovered:
                    substitutions.append(("llm_recover", llm_recovered))
        except ImportError:
            pass
        except Exception as e:
            logger.debug("LLM recover attempt skipped: %s", e)

        # Phase 40+: RESULT-gate for the cascade. The parse-gate kept this query
        # on the rule arm (parse_method == "cascade:rule") but it returned 0 —
        # an honest-zero is exactly where real/messy queries need the LLM, so
        # escalate the LLM arm now for a second parse. Only fires when the rule
        # arm produced the zero (not when the LLM arm already ran).
        try:
            if getattr(parsed, "parse_method", "") == "cascade:rule" and not self._is_nonhuman_organism_zero(parsed):
                # NB: a NON-HUMAN organism honest-zero is CORRECT (the curated
                # catalog is human-only) and must NOT be "recovered" — the LLM
                # re-parse tends to drop the organism and return the wrong human
                # count (the organism honest-zero bug). Those are handled by the
                # explicit honest-zero + Discover-handoff path, not here.
                from ..understanding.cascade_parser import GatedCascadeParser
                from ..understanding.caching_parser import CachingParser
                casc = self.parser
                if isinstance(casc, CachingParser):
                    casc = casc._inner
                if isinstance(casc, GatedCascadeParser):
                    llm_pq = await casc.escalate_for_recovery(parsed.original_text, context)
                    # Recovery must be semantics-preserving: reject it if the LLM
                    # dropped the organism constraint (else 0 → wrong over-broad count).
                    if llm_pq is not None and self._recovery_preserves_organism(parsed, llm_pq):
                        substitutions.append(("cascade_llm_recover", llm_pq))
        except Exception as e:  # noqa: BLE001
            logger.debug("cascade zero-result recovery skipped: %s", e)

        for label, candidate in substitutions:
            try:
                cands = await self.sql_gen.generate(candidate, resolved_entities)
                er2 = await self.sql_exec.execute(cands)
                if er2.row_count > 0:
                    trace.correction(
                        replaces=exec_step.step_id,
                        title=f"Zero-result corrected via [{label}]: {er2.row_count} rows",
                        rationale=(
                            f"original SQL returned 0 rows; relaxed via "
                            f"{label} returned {er2.row_count}"
                        ),
                        new_output={
                            "strategy": label,
                            "row_count": er2.row_count,
                            "method": er2.method,
                        },
                    )
                    return candidate, er2
            except Exception as e:
                logger.warning("Correction strategy %s failed: %s", label, e)

        # ---- Broaden-suggestions (do NOT substitute) ------------------------
        suggestions: list[Suggestion] = []
        broaden_attempts: list[tuple[str, str, ParsedQuery]] = []

        for attr, label in [
            ("cell_types", "cell type"),
            ("assays", "assay"),
            ("diseases", "disease"),
            ("tissues", "tissue"),
            ("disease_categories", "disease category"),
            ("tissue_systems", "tissue system"),
        ]:
            vals = getattr(parsed.filters, attr, None)
            if vals:
                relaxed = deepcopy(parsed)
                setattr(relaxed.filters, attr, [])
                broaden_attempts.append((attr, label, relaxed))

        if parsed.filters.min_series_cells is not None:
            relaxed = deepcopy(parsed)
            relaxed.filters.min_series_cells = None
            broaden_attempts.append(("min_series_cells",
                                     "minimum dataset cell threshold", relaxed))
        if parsed.filters.min_cells is not None:
            relaxed = deepcopy(parsed)
            relaxed.filters.min_cells = None
            broaden_attempts.append(("min_cells",
                                     "minimum sample cell threshold", relaxed))

        for attr_key, human_label, candidate in broaden_attempts[:3]:
            try:
                cands = await self.sql_gen.generate(candidate, resolved_entities)
                er2 = await self.sql_exec.execute(cands)
                if er2.row_count > 0:
                    original_vals = getattr(parsed.filters, attr_key, None)
                    drop_desc = (
                        f"{human_label} = {original_vals}" if original_vals
                        else human_label
                    )
                    suggestions.append(Suggestion(
                        type="expand",
                        text=(f"Drop {human_label} filter → "
                              f"{er2.row_count:,} matches"),
                        action_query=(
                            f"{parsed.original_text} (without {human_label})"
                        ),
                        reason=(
                            f"Your original query returned 0 matches. "
                            f"Removing {drop_desc} would broaden to "
                            f"{er2.row_count:,} records."
                        ),
                    ))
            except Exception as e:
                logger.debug("Broaden suggestion %s failed: %s", attr_key, e)

        if suggestions:
            trace.correction(
                replaces=exec_step.step_id,
                title=f"Zero-result: {len(suggestions)} broaden-suggestion(s)",
                rationale=(
                    "no safe substitution available; surfacing relaxation "
                    "options as suggestions instead of overwriting"
                ),
                new_output={
                    "strategy": "broaden_suggestions",
                    "suggestion_count": len(suggestions),
                },
            )
            return parsed, exec_result, suggestions

        return None
