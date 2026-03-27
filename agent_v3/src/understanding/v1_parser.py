"""
V1-style LLM-first Query Parser - Production-proven patterns.

Key features:
- LLM understands ANY input (Chinese, English, vague, implicit context)
- Multi-field search: disease → disease_clean + title + summary
- Chinese→English mapping: "肺癌" → ["Lung Cancer", "NSCLC"]
- Topic expansion: "免疫" → ["Immune", "T cell", "B cell"]
- Schema knowledge injection (V2 advantage)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..core.models import ParsedQuery, QueryFilters, QueryIntent, SessionContext
from ..core.interfaces import IQueryParser, ILLMClient

logger = logging.getLogger(__name__)


class V1QueryParser(IQueryParser):
    """V1-style LLM-first parser with multi-field search strategy."""

    def __init__(self, llm: ILLMClient, schema_knowledge=None):
        self.llm = llm
        self.sk = schema_knowledge

    async def parse(self, user_input: str, context: SessionContext | None = None) -> ParsedQuery:
        """Parse using V1's proven LLM-first approach."""
        if not self.llm:
            return self._fallback_parse(user_input)

        try:
            prompt = self._build_v1_prompt(user_input)
            response = await self.llm.chat(prompt, temperature=0.1, max_tokens=2048)
            content = response.content if hasattr(response, 'content') else str(response)
            parsed_data = self._parse_json_response(content)
            return self._convert_to_parsed_query(user_input, parsed_data)
        except Exception as e:
            logger.warning(f"V1 parser failed: {e}, using fallback")
            return self._fallback_parse(user_input)

    def _build_v1_prompt(self, query: str) -> str:
        """Build V1-style prompt with schema knowledge."""
        schema_ctx = self._get_schema_context()
        return f"""你是单细胞数据库查询专家。将用户查询转换为数据库检索条件。

{schema_ctx}

**规则：**
1. 中英文映射："人源/人类"→"Homo sapiens", "小鼠"→"Mus musculus", "肺癌"→"Lung Cancer"
2. 隐式理解："单细胞"是冗余的，"所有"表示无额外限制
3. 主题扩展："免疫"→"Immune T cell B cell"

返回JSON: {{"intent":"SEARCH","organisms":[],"tissues":[],"diseases":[],"assays":[],"free_text":"","confidence":0.9}}

用户查询: {query}"""

    def _get_schema_context(self) -> str:
        """Get schema context."""
        if not self.sk:
            return "字段: organisms, tissues, diseases, assays"
        ctx = "常见值:\n"
        for f in ["organism", "tissue", "disease", "assay"]:
            field = self.sk.fields.get(f)
            if field and field.top_values:
                vals = [v["value"] for v in field.top_values[:5]]
                ctx += f"- {f}: {', '.join(vals)}\n"
        return ctx

    def _parse_json_response(self, content: str) -> dict:
        """Parse JSON from LLM response."""
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())

    def _convert_to_parsed_query(self, user_input: str, data: dict) -> ParsedQuery:
        """Convert LLM response to ParsedQuery."""
        intent_str = data.get("intent", "SEARCH").upper()
        intent = QueryIntent[intent_str] if intent_str in QueryIntent.__members__ else QueryIntent.SEARCH
        filters = QueryFilters(
            organisms=data.get("organisms", []),
            tissues=data.get("tissues", []),
            diseases=data.get("diseases", []),
            assays=data.get("assays", []),
            free_text=data.get("free_text"),
        )
        return ParsedQuery(
            intent=intent,
            filters=filters,
            target_level="sample",
            original_text=user_input,
            language="zh" if any('\u4e00' <= c <= '\u9fff' for c in user_input) else "en",
            confidence=data.get("confidence", 0.85),
            parse_method="v1_llm",
        )

    def _fallback_parse(self, user_input: str) -> ParsedQuery:
        """Fallback when LLM unavailable."""
        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(free_text=user_input),
            target_level="sample",
            original_text=user_input,
            language="zh" if any('\u4e00' <= c <= '\u9fff' for c in user_input) else "en",
            confidence=0.3,
            parse_method="fallback",
        )

