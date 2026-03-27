"""
LLM-First Query Parser — Schema Knowledge injected, LLM-driven understanding.

Strategy:
1. Fast track: Pure ID queries → rule parse (no LLM needed)
2. LLM parse: Inject Schema Knowledge, one call for full understanding
3. LLM validate: If confidence < 0.95, second call to verify + correct
4. Return ParsedQuery

Implements IQueryParser protocol — drop-in replacement for the rule-based QueryParser.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict

from ..core.interfaces import ILLMClient
from ..core.models import (
    AggregationSpec,
    BioEntity,
    OrderingSpec,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    SessionContext,
    Suggestion,
)
from ..knowledge.schema_knowledge import SchemaKnowledge
from ..knowledge.prompts import (
    build_parse_prompt,
    build_recovery_prompt,
    build_suggestion_prompt,
    build_validation_prompt,
)

logger = logging.getLogger(__name__)

# ID patterns for fast-track detection
_ID_RE = {
    "geo_project": re.compile(r"\b(GSE\d{4,8})\b", re.I),
    "geo_sample": re.compile(r"\b(GSM\d{4,8})\b", re.I),
    "sra_project": re.compile(r"\b(PRJNA\d{4,8})\b", re.I),
    "sra_study": re.compile(r"\b(SRP\d{4,8})\b", re.I),
    "sra_sample": re.compile(r"\b(SRS\d{4,8})\b", re.I),
    "biosample": re.compile(r"\b(SAM[NE]A?\d{6,12})\b", re.I),
    "pmid": re.compile(r"(?:PMID[:\s]*|pubmed[:\s]*)(\d{6,9})\b", re.I),
    "doi": re.compile(r"\b(10\.\d{4,}/[^\s,;]+)\b"),
}


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        # Remove code fence
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
    # Try direct parse
    return json.loads(text)


def _detect_language(text: str) -> str:
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return "zh" if chinese_chars > len(text) * 0.1 else "en"


class LLMQueryParser:
    """
    LLM-first query parser with Schema Knowledge injection.

    Implements IQueryParser protocol.
    """

    def __init__(self, llm: ILLMClient, schema_knowledge: SchemaKnowledge):
        self.llm = llm
        self.sk = schema_knowledge

    async def parse(
        self,
        query: str,
        context: SessionContext | None = None,
    ) -> ParsedQuery:
        """
        Parse user query with LLM + Schema Knowledge.

        1. Fast track: pure ID queries → rule parse
        2. LLM parse with full schema context
        3. LLM validate if confidence < 0.95
        """
        query = query.strip()
        if not query:
            return ParsedQuery(
                intent=QueryIntent.EXPLORE,
                original_text=query,
                confidence=0.0,
            )

        lang = _detect_language(query)

        # 1. Fast track: pure ID queries
        ids = self._extract_ids(query)
        if ids and not self._has_non_id_content(query, ids):
            return self._build_id_query(ids, query, lang)

        # 2. LLM parse
        try:
            parsed = await self._llm_parse(query, lang, context)
            if parsed:
                # 3. Validate if not highly confident
                if parsed.confidence < 0.95:
                    parsed = await self._llm_validate(parsed, query)
                return parsed
        except Exception as e:
            logger.warning("LLM parse failed: %s, falling back to synonym resolution", e)

        # 4. Fallback: use schema knowledge synonym resolution without LLM
        return self._synonym_fallback(query, lang)

    async def recover_zero_result(
        self,
        parsed: ParsedQuery,
        sql: str,
        context: SessionContext | None = None,
    ) -> ParsedQuery | None:
        """
        Zero-result recovery: LLM decides how to relax filters.

        Returns a new ParsedQuery with relaxed filters, or None if recovery not possible.
        """
        filters_dict = self._filters_to_dict(parsed.filters)
        recovery_context = self.sk.format_for_recovery(filters_dict)

        prompt = build_recovery_prompt(
            recovery_context=recovery_context,
            original_query=parsed.original_text,
            failed_filters=filters_dict,
            sql=sql,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )
            data = _extract_json(response.content)

            relaxed = data.get("relaxed_filters", {})
            if not relaxed:
                return None

            new_filters = self._dict_to_filters(relaxed)
            explanation = data.get("explanation", "")

            logger.info(
                "Zero-result recovery: strategy=%s, explanation=%s",
                data.get("strategy", "?"), explanation,
            )

            return ParsedQuery(
                intent=parsed.intent,
                complexity=parsed.complexity,
                entities=parsed.entities,
                filters=new_filters,
                target_level=parsed.target_level,
                aggregation=parsed.aggregation,
                ordering=parsed.ordering,
                limit=parsed.limit,
                original_text=parsed.original_text,
                language=parsed.language,
                confidence=max(parsed.confidence - 0.2, 0.3),
                parse_method="llm_recovery",
            )
        except Exception as e:
            logger.warning("Zero-result recovery failed: %s", e)
            return None

    async def generate_suggestions(
        self,
        parsed: ParsedQuery,
        result_count: int,
        summary: str,
    ) -> list[Suggestion]:
        """LLM-generated contextual follow-up suggestions."""
        schema_context = self.sk.format_for_suggestions()

        prompt = build_suggestion_prompt(
            schema_context=schema_context,
            query=parsed.original_text,
            result_count=result_count,
            summary=summary,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=512,
            )
            data = _extract_json(response.content)

            suggestions = []
            for s in data.get("suggestions", [])[:4]:
                suggestions.append(Suggestion(
                    type=s.get("type", "related"),
                    text=s.get("text", ""),
                    action_query=s.get("action_query", ""),
                    reason=s.get("reason", ""),
                ))
            return suggestions
        except Exception as e:
            logger.warning("Suggestion generation failed: %s", e)
            return []

    # ── Internal methods ──

    def _extract_ids(self, query: str) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for id_type, pattern in _ID_RE.items():
            matches = pattern.findall(query)
            if matches:
                found[id_type] = matches
        return found

    def _has_non_id_content(self, query: str, ids: dict) -> bool:
        """Check if query has meaningful content beyond IDs."""
        remaining = query
        for values in ids.values():
            for v in values:
                remaining = remaining.replace(v, "")
        # Remove common filler words
        remaining = re.sub(r"(?:PMID|pubmed|doi)[:\s]*", "", remaining, flags=re.I)
        remaining = remaining.strip(" ,;.?!，。？！")
        # If significant text remains, it's not a pure ID query
        return len(remaining) > 5

    def _build_id_query(self, ids: dict, query: str, lang: str) -> ParsedQuery:
        filters = QueryFilters()
        entities: list[BioEntity] = []

        for id_type, values in ids.items():
            if id_type in ("geo_project", "sra_project"):
                filters.project_ids.extend(values)
            elif id_type in ("geo_sample", "sra_sample", "biosample"):
                filters.sample_ids.extend(values)
            elif id_type == "pmid":
                filters.pmids.extend(values)
            elif id_type == "doi":
                filters.dois.extend(values)

            for v in values:
                entities.append(BioEntity(text=v, entity_type="id", normalized_value=v))

        q_lower = query.lower()
        intent = QueryIntent.SEARCH
        if any(kw in q_lower for kw in ["关联", "跨库", "linked", "related", "cross"]):
            intent = QueryIntent.LINEAGE

        return ParsedQuery(
            intent=intent,
            complexity=QueryComplexity.SIMPLE,
            entities=entities,
            filters=filters,
            target_level="project" if filters.project_ids else "sample",
            original_text=query,
            language=lang,
            confidence=0.95,
            parse_method="rule",
        )

    async def _llm_parse(
        self, query: str, lang: str, context: SessionContext | None,
    ) -> ParsedQuery | None:
        schema_context = self.sk.format_for_parse_prompt()
        session_history = context.turns if context else None

        prompt = build_parse_prompt(
            schema_context=schema_context,
            user_query=query,
            session_history=session_history,
        )

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )

        data = _extract_json(response.content)

        # Build entities
        entities = []
        for e in data.get("entities", []):
            entities.append(BioEntity(
                text=e.get("text", ""),
                entity_type=e.get("type", ""),
                normalized_value=e.get("value"),
            ))

        # Build filters
        f = data.get("filters", {})
        filters = QueryFilters(
            tissues=f.get("tissues", []),
            diseases=f.get("diseases", []),
            cell_types=f.get("cell_types", []),
            assays=f.get("assays", []),
            organisms=f.get("organisms", []),
            source_databases=f.get("source_databases", []),
            sex=f.get("sex"),
            project_ids=f.get("project_ids", []),
            sample_ids=f.get("sample_ids", []),
            pmids=f.get("pmids", []),
            free_text=f.get("free_text"),
        )

        # Aggregation
        agg_data = data.get("aggregation")
        aggregation = None
        if agg_data and isinstance(agg_data, dict):
            aggregation = AggregationSpec(
                group_by=agg_data.get("group_by", []),
                metric=agg_data.get("metric", "count"),
            )

        # Ordering
        ord_data = data.get("ordering")
        ordering = None
        if ord_data and isinstance(ord_data, dict):
            ordering = OrderingSpec(
                field=ord_data.get("field", ""),
                direction=ord_data.get("direction", "desc"),
            )

        # Intent
        intent_str = data.get("intent", "SEARCH").upper()
        try:
            intent = QueryIntent[intent_str]
        except KeyError:
            intent = QueryIntent.SEARCH

        confidence = data.get("confidence", 0.8)

        # Complexity assessment
        complexity = QueryComplexity.SIMPLE
        if aggregation and len(entities) > 2:
            complexity = QueryComplexity.COMPLEX
        elif intent == QueryIntent.COMPARE or len(entities) > 3:
            complexity = QueryComplexity.COMPLEX
        elif len(entities) > 1:
            complexity = QueryComplexity.MODERATE

        return ParsedQuery(
            intent=intent,
            complexity=complexity,
            entities=entities,
            filters=filters,
            target_level=data.get("target_level", "sample"),
            aggregation=aggregation,
            ordering=ordering,
            limit=20,
            original_text=query,
            language=lang,
            confidence=confidence,
            parse_method="llm",
        )

    async def _llm_validate(self, parsed: ParsedQuery, query: str) -> ParsedQuery:
        """Validate and correct parsed result using LLM + schema knowledge."""
        filters_dict = self._filters_to_dict(parsed.filters)
        validation_context = self.sk.format_for_validation(filters_dict)

        parsed_dict = {
            "intent": parsed.intent.name,
            "filters": filters_dict,
            "entities": [
                {"text": e.text, "type": e.entity_type, "value": e.normalized_value}
                for e in parsed.entities
            ],
        }

        prompt = build_validation_prompt(
            validation_context=validation_context,
            parsed_result=parsed_dict,
            user_query=query,
        )

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )
            data = _extract_json(response.content)

            if data.get("is_valid", True):
                return parsed

            # Apply corrections
            corrected = data.get("corrected_filters")
            if corrected:
                parsed.filters = self._dict_to_filters(corrected)
                parsed.parse_method = "llm_validated"
                # Boost confidence after validation
                parsed.confidence = min(parsed.confidence + 0.1, 0.95)

            warnings = data.get("warnings", [])
            if warnings:
                logger.info("Validation warnings: %s", warnings)

            return parsed
        except Exception as e:
            logger.warning("LLM validation failed: %s", e)
            return parsed

    def _synonym_fallback(self, query: str, lang: str) -> ParsedQuery:
        """Fallback: use schema knowledge synonyms without LLM."""
        query_lower = query.lower()
        entities: list[BioEntity] = []
        filters = QueryFilters()

        # Try synonym resolution for each field
        for field_name in ["tissue", "disease", "cell_type", "assay", "organism", "source_database"]:
            synonyms = self.sk.get_synonyms(field_name)
            for canonical, aliases in synonyms.items():
                all_terms = [canonical.lower()] + [a.lower() for a in aliases]
                for term in all_terms:
                    if term in query_lower:
                        entities.append(BioEntity(
                            text=term,
                            entity_type=field_name,
                            normalized_value=canonical,
                        ))
                        # Add to filters
                        if field_name == "tissue":
                            filters.tissues.append(canonical)
                        elif field_name == "disease":
                            filters.diseases.append(canonical)
                        elif field_name == "cell_type":
                            filters.cell_types.append(canonical)
                        elif field_name == "assay":
                            filters.assays.append(canonical)
                        elif field_name == "organism":
                            filters.organisms.append(canonical)
                        elif field_name == "source_database":
                            filters.source_databases.append(canonical)
                        break  # One match per canonical

        confidence = 0.5 + min(len(entities) * 0.15, 0.35)

        if not entities:
            filters.free_text = query

        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            entities=entities,
            filters=filters,
            target_level="sample",
            original_text=query,
            language=lang,
            confidence=confidence if entities else 0.3,
            parse_method="synonym_fallback",
        )

    @staticmethod
    def _filters_to_dict(filters: QueryFilters) -> dict:
        return {
            "tissues": filters.tissues,
            "diseases": filters.diseases,
            "cell_types": filters.cell_types,
            "assays": filters.assays,
            "organisms": filters.organisms,
            "source_databases": filters.source_databases,
            "sex": filters.sex,
            "project_ids": filters.project_ids,
            "sample_ids": filters.sample_ids,
            "pmids": filters.pmids,
            "free_text": filters.free_text,
        }

    @staticmethod
    def _dict_to_filters(d: dict) -> QueryFilters:
        return QueryFilters(
            tissues=d.get("tissues", []),
            diseases=d.get("diseases", []),
            cell_types=d.get("cell_types", []),
            assays=d.get("assays", []),
            organisms=d.get("organisms", []),
            source_databases=d.get("source_databases", []),
            sex=d.get("sex"),
            project_ids=d.get("project_ids", []),
            sample_ids=d.get("sample_ids", []),
            pmids=d.get("pmids", []),
            free_text=d.get("free_text"),
        )
