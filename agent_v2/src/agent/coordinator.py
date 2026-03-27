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
from ..dal.database import DatabaseAbstractionLayer
from ..synthesis.answer import AnswerSynthesizer

logger = logging.getLogger(__name__)


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
        enricher=None,
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
        self._enricher = enricher

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
    ) -> CoordinatorAgent:
        """
        工厂方法 — 自动构建完整依赖图。

        向后兼容旧的直接构造方式。
        """
        from ..understanding.parser import QueryParser
        from ..sql.engine import SQLGenerator, ParallelSQLExecutor
        from ..fusion.engine import CrossDBFusionEngine

        schema_context = dal.get_schema_summary()

        # Load Schema Knowledge (optional)
        sk = None
        if schema_knowledge_path and Path(schema_knowledge_path).exists():
            try:
                from ..knowledge.schema_knowledge import SchemaKnowledge
                sk = SchemaKnowledge(schema_knowledge_path)
                logger.info("SchemaKnowledge loaded from %s", schema_knowledge_path)
            except Exception as e:
                logger.warning("Failed to load SchemaKnowledge: %s", e)

        # Choose parser: LLM-first (if LLM + SK available) or rule-based (fallback)
        if llm and sk:
            try:
                from ..understanding.llm_parser import LLMQueryParser
                parser = LLMQueryParser(llm=llm, schema_knowledge=sk)
                logger.info("Using LLMQueryParser (LLM-first)")
            except Exception as e:
                logger.warning("LLMQueryParser init failed, falling back to rule parser: %s", e)
                parser = QueryParser(llm=llm, schema_context=schema_context)
        else:
            parser = QueryParser(llm=llm, schema_context=schema_context)

        sql_gen = SQLGenerator(dal=dal, llm=llm)
        sql_exec = ParallelSQLExecutor(dal=dal)
        fusion = CrossDBFusionEngine(dal=dal)
        synthesizer = AnswerSynthesizer(llm=llm)

        # LLM-driven query enricher (enhances rule-parsed queries)
        enricher = None
        if llm:
            try:
                from ..understanding.enricher import QueryEnricher
                enricher = QueryEnricher(llm=llm, schema_knowledge=sk)
                logger.info("QueryEnricher initialized (LLM-driven enrichment enabled)")
            except Exception as e:
                logger.warning("Failed to init QueryEnricher: %s", e)

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

        return cls(
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
            enricher=enricher,
        )

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
    ) -> AgentResponse:
        """
        端到端查询入口

        Pipeline:
        1. Parse → 2. Ontology Resolve → 3. Generate SQL → 4. Execute → 5. Fuse → 6. Synthesize
        """
        t0 = time.perf_counter()

        # Load session context
        context = self._sessions.get(session_id, SessionContext(session_id=session_id))
        wmem = self._get_working_memory(session_id)

        if wmem:
            context = wmem.get_context()

        try:
            # Step 1: Query Understanding
            parsed = await self.parser.parse(user_input, context)
            logger.info(
                "Parsed: intent=%s, entities=%d, confidence=%.2f, method=%s",
                parsed.intent.name, len(parsed.entities),
                parsed.confidence, parsed.parse_method,
            )

            # Step 1b: LLM Enrichment (for rule-parsed queries)
            # LLM acts as the primary intelligence layer — enriches/corrects
            # the initial parse with full semantic understanding
            if self._enricher:
                try:
                    parsed = await self._enricher.enrich(parsed)
                except Exception as e:
                    logger.warning("LLM enrichment failed: %s", e)

            # Step 2: Ontology Resolution
            resolved_entities = None
            ontology_expansions = []
            if self.ontology and parsed.entities:
                resolved_entities = self.ontology.resolve_all(parsed.entities)
                for re_ in resolved_entities:
                    if re_.ontology_term:
                        ontology_expansions.append({
                            "original": re_.original.text,
                            "ontology_id": re_.ontology_term.ontology_id,
                            "label": re_.ontology_term.label,
                            "db_values_count": len(re_.db_values),
                            "total_samples": re_.total_sample_count,
                        })
                if ontology_expansions:
                    logger.info("Ontology resolved %d entities", len(ontology_expansions))

            # Step 3: SQL Generation
            candidates = await self.sql_gen.generate(parsed, resolved_entities)
            logger.info("Generated %d SQL candidates", len(candidates))

            # Step 4: Parallel Execution
            exec_result = await self.sql_exec.execute(candidates)
            logger.info(
                "Executed: %d rows, method=%s, %.0fms",
                exec_result.row_count, exec_result.method, exec_result.exec_time_ms,
            )

            # Step 4b: Zero-result recovery (when LLM parser available)
            if exec_result.row_count == 0:
                try:
                    from ..understanding.llm_parser import LLMQueryParser
                    if isinstance(self.parser, LLMQueryParser):
                        recovered = await self.parser.recover_zero_result(
                            parsed, exec_result.sql, context,
                        )
                        if recovered:
                            logger.info("Zero-result recovery: re-executing with relaxed filters")
                            candidates2 = await self.sql_gen.generate(recovered, resolved_entities)
                            exec_result2 = await self.sql_exec.execute(candidates2)
                            if exec_result2.row_count > 0:
                                parsed = recovered
                                exec_result = exec_result2
                                logger.info(
                                    "Recovery succeeded: %d rows, method=%s",
                                    exec_result.row_count, exec_result.method,
                                )
                    elif self._enricher and self.llm:
                        # Fallback recovery via enricher: re-enrich with relaxed prompt
                        logger.info("Zero-result: attempting re-enrichment for recovery")
                except ImportError:
                    pass
                except Exception as e:
                    logger.warning("Zero-result recovery error: %s", e)

            # Step 5: Cross-DB Fusion
            fused = self.fusion.fuse(exec_result.rows)
            logger.info(
                "Fused: %d → %d records (%.0f%% dedup)",
                exec_result.row_count, len(fused),
                (1 - len(fused) / max(exec_result.row_count, 1)) * 100,
            )

            # Step 6: Answer Synthesis (via injected synthesizer)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            response = self.synthesizer.synthesize_from_execution(
                parsed, fused, exec_result, elapsed_ms, ontology_expansions,
            )

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
            )

            return response

        except SCeQTLError as e:
            logger.error("Query failed at stage [%s]: %s", e.stage, e, exc_info=True)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return AgentResponse(
                summary=f"查询处理出错 [{e.stage}]: {str(e)}",
                error=str(e),
                provenance=ProvenanceInfo(
                    original_query=user_input,
                    execution_time_ms=elapsed_ms,
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
    ):
        """Update all memory layers after a query."""
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
