"""
LLM-Driven Query Enricher — 智能查询富化层

核心设计理念：
- LLM 是查询理解的主引擎，不是关键词穷举
- 接收任意用户输入（中文、英文、混合、模糊、隐含上下文），
  用 LLM + Schema Knowledge 一次理解全部语义
- 输出完整的、可直接供 SQL 引擎消费的 ParsedQuery

Pipeline 位置：
  Parse (initial) → **Enrich (LLM)** → Ontology → SQL → Execute → Fuse → Synthesize

两种工作模式：
1. LLM 模式（推荐）：LLM 做全量语义理解 + 条件生成
2. 降级模式（无 LLM）：仅做基础的同义词匹配和冗余词剥离
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

from ..core.interfaces import ILLMClient
from ..core.models import (
    BioEntity,
    ParsedQuery,
    QueryFilters,
    QueryIntent,
)

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    return json.loads(text)


# ── Prompt 模板 ──

_ENRICH_PROMPT = """You are the query understanding engine for a **single-cell RNA-seq metadata database**.

Your job: take the raw user input and produce a precise, enriched query specification that downstream SQL and retrieval modules can directly consume.

## Database Context
{schema_context}

## Current Parse State (from initial rule-based parser)
Intent: {intent}
Entities extracted: {entities}
Filters populated: {filters}
Confidence: {confidence}
Parse method: {parse_method}

## Raw User Input
"{user_input}"

## Your Task
Analyze the user's ACTUAL intent and produce a corrected + enriched query. Be smart about:

1. **Semantic Understanding**: "人源" means organism=Homo sapiens. "小鼠" means Mus musculus. Understand domain jargon in ANY language.
2. **Implicit Context**: This is a single-cell database. Terms like "单细胞"/"single-cell" are redundant context, NOT filters. Don't create assay filters from them.
3. **Scope Modifiers**: "所有"/"全部"/"all" mean "don't restrict beyond the explicit filters". "最新" means order by date desc.
4. **Concept Expansion**: "免疫" should expand to relevant English search terms (immune, immunology, T cell, etc.) as `free_text` for full-text search. Don't over-expand.
5. **Entity Translation**: Always map Chinese biological terms to their English canonical DB values. The database stores values in English.
6. **Filter Correction**: If the initial parser missed something or got it wrong, fix it. If a filter value doesn't match known DB values, find the closest match.
7. **Graceful Handling**: For vague/broad queries, produce reasonable filters rather than empty ones. For nonsensical input, set free_text search.

## Output (JSON only)
{{
  "intent": "SEARCH | COMPARE | STATISTICS | EXPLORE | DOWNLOAD | LINEAGE",
  "target_level": "project | series | sample | celltype",
  "entities": [
    {{"text": "original term", "type": "tissue|disease|cell_type|assay|organism|source_database|sex", "value": "canonical DB value"}}
  ],
  "filters": {{
    "tissues": [],
    "diseases": [],
    "cell_types": [],
    "assays": [],
    "organisms": [],
    "source_databases": [],
    "sex": null,
    "project_ids": [],
    "sample_ids": [],
    "pmids": [],
    "free_text": null
  }},
  "aggregation": null | {{"group_by": ["field"], "metric": "count"}},
  "ordering": null | {{"field": "...", "direction": "asc|desc"}},
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of key enrichment decisions"
}}

Rules:
- Use actual DB values from the schema context above (top_values, synonyms)
- organism values in DB: "Homo sapiens", "Mus musculus", "Drosophila melanogaster", etc. (Latin names)
- source_database values: "geo", "ncbi", "ebi", "cellxgene", "hca", "htan", "psychad"
- For Chinese topic keywords with no direct DB field match, put English translations in free_text
- Only set filters you are confident about. Empty list = no filter on that field.
- Return ONLY valid JSON, no explanation outside the JSON"""


class QueryEnricher:
    """
    LLM-driven query enrichment.

    Takes a ParsedQuery (from initial parser) and enriches it using LLM intelligence:
    - Fills missing filters the rule parser couldn't detect
    - Translates Chinese terms to English DB values
    - Understands implicit context (e.g., "单细胞" is redundant)
    - Expands topic keywords to English search terms
    - Corrects wrong/imprecise filter values

    Falls back gracefully when LLM is unavailable.
    """

    def __init__(
        self,
        llm: ILLMClient | None = None,
        schema_knowledge=None,
    ):
        self.llm = llm
        self.sk = schema_knowledge

    async def enrich(self, parsed: ParsedQuery) -> ParsedQuery:
        """
        Enrich a ParsedQuery using LLM + Schema Knowledge.

        If LLM is available: does full semantic enrichment.
        If not: returns the input unchanged (rule parser result stands).
        """
        if not self.llm:
            logger.debug("No LLM available, skipping enrichment")
            return parsed

        # Don't re-enrich LLM-parsed queries (they're already LLM-enriched)
        if parsed.parse_method in ("llm", "llm_validated", "llm_recovery"):
            logger.debug("Query already LLM-parsed, skipping enrichment")
            return parsed

        # Don't enrich high-confidence ID queries
        if parsed.confidence >= 0.95 and (parsed.filters.project_ids or parsed.filters.sample_ids or parsed.filters.pmids):
            logger.debug("High-confidence ID query, skipping enrichment")
            return parsed

        try:
            enriched = await self._llm_enrich(parsed)
            if enriched:
                logger.info(
                    "Enriched: intent=%s→%s, entities=%d→%d, organisms=%s, method=%s→enriched",
                    parsed.intent.name, enriched.intent.name,
                    len(parsed.entities), len(enriched.entities),
                    enriched.filters.organisms,
                    parsed.parse_method,
                )
                return enriched
        except Exception as e:
            logger.warning("LLM enrichment failed: %s, using original parse", e)

        return parsed

    async def _llm_enrich(self, parsed: ParsedQuery) -> ParsedQuery | None:
        """Core LLM enrichment call."""
        # Build schema context
        schema_context = ""
        if self.sk:
            schema_context = self.sk.format_for_parse_prompt()
        else:
            schema_context = "(No schema knowledge available — use your knowledge of single-cell databases)"

        # Serialize current parse state for LLM
        entities_str = ", ".join(
            f"{e.entity_type}={e.normalized_value or e.text}" for e in parsed.entities
        ) or "(none)"

        filters_dict = {
            "tissues": parsed.filters.tissues,
            "diseases": parsed.filters.diseases,
            "cell_types": parsed.filters.cell_types,
            "assays": parsed.filters.assays,
            "organisms": parsed.filters.organisms,
            "source_databases": parsed.filters.source_databases,
            "sex": parsed.filters.sex,
            "free_text": parsed.filters.free_text,
        }
        # Remove empty lists for cleaner display
        filters_str = json.dumps(
            {k: v for k, v in filters_dict.items() if v},
            ensure_ascii=False,
        ) or "(none)"

        prompt = _ENRICH_PROMPT.format(
            schema_context=schema_context,
            intent=parsed.intent.name,
            entities=entities_str,
            filters=filters_str,
            confidence=f"{parsed.confidence:.2f}",
            parse_method=parsed.parse_method,
            user_input=parsed.original_text,
        )

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )

        data = _extract_json(response.content)

        # Build enriched entities
        entities = []
        for e in data.get("entities", []):
            entities.append(BioEntity(
                text=e.get("text", ""),
                entity_type=e.get("type", ""),
                normalized_value=e.get("value"),
            ))

        # Build enriched filters
        f = data.get("filters", {})
        filters = QueryFilters(
            tissues=f.get("tissues", []),
            diseases=f.get("diseases", []),
            cell_types=f.get("cell_types", []),
            assays=f.get("assays", []),
            organisms=f.get("organisms", []),
            source_databases=f.get("source_databases", []),
            sex=f.get("sex"),
            project_ids=f.get("project_ids", parsed.filters.project_ids),
            sample_ids=f.get("sample_ids", parsed.filters.sample_ids),
            pmids=f.get("pmids", parsed.filters.pmids),
            dois=parsed.filters.dois,  # Preserve from original
            free_text=f.get("free_text"),
        )

        # Intent
        intent_str = data.get("intent", "SEARCH").upper()
        try:
            intent = QueryIntent[intent_str]
        except KeyError:
            intent = parsed.intent

        # Aggregation
        from ..core.models import AggregationSpec, OrderingSpec
        agg_data = data.get("aggregation")
        aggregation = None
        if agg_data and isinstance(agg_data, dict):
            aggregation = AggregationSpec(
                group_by=agg_data.get("group_by", []),
                metric=agg_data.get("metric", "count"),
            )

        ordering = parsed.ordering
        ord_data = data.get("ordering")
        if ord_data and isinstance(ord_data, dict):
            ordering = OrderingSpec(
                field=ord_data.get("field", ""),
                direction=ord_data.get("direction", "desc"),
            )

        confidence = data.get("confidence", 0.85)

        return ParsedQuery(
            intent=intent,
            complexity=parsed.complexity,
            entities=entities,
            filters=filters,
            target_level=data.get("target_level", parsed.target_level),
            aggregation=aggregation or parsed.aggregation,
            ordering=ordering,
            limit=parsed.limit,
            original_text=parsed.original_text,
            language=parsed.language,
            confidence=confidence,
            parse_method="enriched",
        )
