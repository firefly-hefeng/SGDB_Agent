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

from ..core.models import (
    AggregationSpec, BioEntity, ParsedQuery, QueryFilters,
    QueryIntent, SessionContext,
)
from ..core.interfaces import IQueryParser, ILLMClient

logger = logging.getLogger(__name__)

# Phase 37: a lazily-built, cached rule parser used only for its deterministic
# aggregation detector (superlative-ranking fallback). Lightweight to construct.
_RULE_PARSER_SINGLETON = None


def _rule_parser():
    global _RULE_PARSER_SINGLETON
    if _RULE_PARSER_SINGLETON is None:
        from src.understanding.parser import QueryParser
        _RULE_PARSER_SINGLETON = QueryParser()
    return _RULE_PARSER_SINGLETON


# Phase 38: dynamic knowledge-injection vocabulary. Enumerated fields are CLOSED
# sets — the LLM must pick from the real values (anti-hallucination); text fields
# inject top-N as guidance. Built from the LIVE DB at startup so it always matches
# whatever DB is loaded (the old static schema_knowledge.yaml was a stale snapshot
# of a multi-organism DB and actively told the LLM "mouse data exists").
_LIVE_VOCAB_FIELDS: dict[str, tuple[str, int]] = {
    "organism_common": ("enum", 8),
    "sample_type": ("enum", 12),
    "disease_category": ("enum", 20),
    "source_database": ("enum", 12),
    "sex_normalized": ("enum", 6),
    "tissue_standard_l1": ("text", 18),
    "cell_type_lineage": ("text", 14),
    "disease_standard": ("text", 16),
}


def build_live_vocab(dal, table: str = "unified_samples") -> dict:
    """Read real field values from the LIVE DB for prompt injection. Cheap
    (a handful of GROUP BYs on an indexed/ext4 DB). Returns {field: {kind, values}}."""
    vocab: dict = {}
    for field, (kind, n) in _LIVE_VOCAB_FIELDS.items():
        try:
            res = dal.execute(
                f"SELECT {field} AS v, COUNT(*) AS c FROM {table} "
                f"WHERE {field} IS NOT NULL AND {field} != '' "
                f"GROUP BY {field} ORDER BY c DESC LIMIT {n}"
            )
            vals = [str(r["v"]) for r in res.rows if r.get("v") is not None]
            if vals:
                vocab[field] = {"kind": kind, "values": vals}
        except Exception:  # noqa: BLE001 — best-effort; injection is optional
            continue
    return vocab


class V1QueryParser(IQueryParser):
    """V1-style LLM-first parser with multi-field search strategy."""

    def __init__(self, llm: ILLMClient, schema_knowledge=None, live_vocab=None):
        self.llm = llm
        self.sk = schema_knowledge
        self.live_vocab = live_vocab or {}

    async def parse(self, user_input: str, context: SessionContext | None = None) -> ParsedQuery:
        """Parse using V1's proven LLM-first approach."""
        if not self.llm:
            return self._fallback_parse(user_input)

        try:
            prompt = self._build_v1_prompt(user_input)
            try:
                response = await self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    # NOTE: kimi-k2.6 (a "thinking" model) ONLY accepts temperature=1
                    # — it 400s on any other value, which silently fell every parse
                    # back to the rule parser (Phase 38). So LLM-mode nondeterminism
                    # is intrinsic; the benchmark reports it via repeated runs.
                    # response_format forces a JSON object so the thinking model
                    # can't return un-parseable reasoning prose.
                    # k2.6 "thinking" spends tokens on reasoning BEFORE the JSON
                    # answer; 2048 got exhausted mid-reason and truncated the JSON
                    # to empty (7/40 empty parses). Give it room.
                    temperature=1.0, max_tokens=8192,
                    response_format={"type": "json_object"},
                )
            except TypeError:
                # client without response_format support (older signature)
                response = await self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=1.0, max_tokens=8192,
                )
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
4. **聚合识别 (Phase 26)**: 如果查询要求按某字段分组统计 (e.g. "按疾病/组织/性别统计", "How many ... per X", "Count by X", "分别有多少", "各类别"), 设置 intent="STATISTICS" 并填充 aggregation.group_by 为分组字段名 (合法值: disease_category, tissue_standard, source_database, cell_type, organism_common, sample_type, sex, disease, assay). 否则 aggregation 为 null.
5. **疾病大类识别 (umbrella, Phase 26)**: 如果查询提到大类 (neurological/neoplasm/cardiovascular/autoimmune/hematological/immune等) 而非具体疾病, 填充 disease_categories 而非 diseases。合法值: neurological, neoplasm, cardiovascular, autoimmune, hematological, genetic_congenital, injury_poisoning, infectious, endocrine, normal。
6. **严格模式 (strict_mode, Phase 26)**: 如果查询有 "strictly/exactly/严格/仅限/只要/just/only" 等强调字眼, 设置 strict_mode=true, 表示不要扩展到上位 umbrella 或 ontology 同义词。
7. **排除条件 (negation, Phase 26)**: 如果查询有 "but not/exclude/排除/除了/不包括" 等否定字眼, 填充 exclude_diseases / exclude_disease_categories / exclude_tissues / exclude_sample_types 等数组。例如 "breast tissue but exclude neoplasm or cancer subtypes" → exclude_disease_categories=["neoplasm"] AND exclude_diseases=["cancer"]; "排除细胞系" → exclude_sample_types=["cell_line"]。
8. **样本类型 (sample_types, Phase 38)**: "肿瘤/tumor 样本"→["tumor"]; "细胞系/cell line"→["cell_line"]; "类器官/organoid"→["organoid"]; "体外培养/培养的/grown in a dish/cultured/in vitro/非患者来源"→["cell_line","organoid","iPSC_derived","PSC_derived"]; "原代/primary"→["primary_tissue"]; "iPSC/诱导多能干细胞"→["iPSC_derived"]; "异种移植/xenograft"→["xenograft"]。合法值仅: tumor, cell_line, primary_tissue, organoid, iPSC_derived, PSC_derived, xenograft。
9. **细胞类型 (cell_types, Phase 38)**: 查询提到具体细胞 (T cell, macrophage/巨噬, fibroblast/成纤维, neuron/神经元, epithelial/上皮, NK, B cell, monocyte, dendritic, pericyte...) 填入 cell_types (会在单样本细胞组成表里匹配"含该细胞"). 类别词照填: "免疫细胞/immune cells", "髓系/myeloid", "基质细胞/stromal cells", "淋巴细胞/lymphocytes"。
10. **性别 (sex, Phase 38)**: "女性/女/female"→"female"; "男性/男/male"→"male"; 否则 null。
11. **数据库来源 (source_databases, Phase 38)**: 合法值: geo, ega, ncbi, ebi, cellxgene, hca, htan, scea。例 "来自GEO/from EGA"→["geo"]/["ega"]。
12. **时间 (published_after/published_before, Phase 38)**: "2024年/in 2024/after 2023"→published_after="2024-01-01"; "2020到2022/between 2020 and 2022"→published_after="2020-01-01",published_before="2022-12-31"; "2023年之前/before 2023"→published_before="2023-01-01"; "最近/最新/recent/latest"→published_after = (当前年份-2)+"-01-01"。日期一律 YYYY-MM-DD。
13. **细胞数阈值 (min_cells, Phase 38)**: "超过N个细胞/at least N cells/lots of cells/large datasets/大数据集"→ min_cells=N (含糊量词如"lots/大"用 10000)。

返回JSON: {{"intent":"SEARCH","organisms":[],"tissues":[],"diseases":[],"disease_categories":[],"cell_types":[],"sample_types":[],"assays":[],"sex":null,"source_databases":[],"min_cells":null,"published_after":null,"published_before":null,"exclude_diseases":[],"exclude_disease_categories":[],"exclude_tissues":[],"exclude_sample_types":[],"strict_mode":false,"free_text":"","aggregation":null,"confidence":0.9}}

用户查询: {query}"""

    # Human-readable labels for the injected fields.
    _VOCAB_LABEL = {
        "organism_common": "organism (物种)", "sample_type": "sample_type (样本类型)",
        "disease_category": "disease_category (疾病大类)", "source_database": "source_database (来源库)",
        "sex_normalized": "sex (性别)", "tissue_standard_l1": "常见 tissue (器官)",
        "cell_type_lineage": "常见 cell type (细胞谱系)", "disease_standard": "常见 disease (具体疾病)",
    }

    # Common-name → values the LLM might emit, so the guard recognises a valid
    # organism regardless of which form the model used.
    _ORGANISM_FORMS = {
        "human": ("human", "homo sapiens", "h. sapiens", "h sapiens", "man"),
        "mouse": ("mouse", "mus musculus"), "rat": ("rat", "rattus"),
        "zebrafish": ("zebrafish", "danio rerio"),
    }

    def _enforce_live_vocab(self, filters) -> None:
        """Drop enumerated filter values not present in the live DB vocabulary —
        but keep the list unchanged if NONE are valid (so a genuine query for
        absent data still returns 0 rather than dropping the filter entirely)."""
        if not self.live_vocab:
            return

        def _allowed(field):
            info = self.live_vocab.get(field)
            return {v.strip().lower() for v in info["values"]} if info else None

        def _norm(v):
            return str(v).strip().lower().replace(" ", "_")

        def _prune_enum(values, allowed):
            if allowed is None or not values:
                return values
            valid = [v for v in values if _norm(v) in allowed or str(v).strip().lower() in allowed]
            return valid if valid else values

        filters.sample_types = _prune_enum(filters.sample_types, _allowed("sample_type"))
        filters.exclude_sample_types = _prune_enum(filters.exclude_sample_types, _allowed("sample_type"))
        filters.source_databases = _prune_enum(filters.source_databases, _allowed("source_database"))
        filters.disease_categories = _prune_enum(filters.disease_categories, _allowed("disease_category"))
        filters.exclude_disease_categories = _prune_enum(filters.exclude_disease_categories, _allowed("disease_category"))
        sex_allowed = _allowed("sex_normalized")
        if filters.sex and sex_allowed and filters.sex.strip().lower() not in sex_allowed:
            filters.sex = None

        # Organisms: match against the live common-names + their scientific forms.
        oc = _allowed("organism_common")
        if oc and filters.organisms:
            allowed_forms = set()
            for canon in oc:
                allowed_forms.update(self._ORGANISM_FORMS.get(canon, (canon,)))
            valid = [o for o in filters.organisms
                     if any(form in str(o).lower() for form in allowed_forms)]
            filters.organisms = valid if valid else filters.organisms

    def _get_schema_context(self) -> str:
        """Dynamic knowledge injection.

        Prefer the LIVE vocabulary read from the loaded DB (always current); this
        anchors the LLM to REAL values so it can't hallucinate (e.g. it used to
        invent "Rattus norvegicus" because the stale YAML claimed mouse data
        existed — this DB is human-only). Enumerated fields are presented as
        closed sets with an explicit "choose only from these" instruction.
        """
        if self.live_vocab:
            enum_lines, text_lines = [], []
            for field, info in self.live_vocab.items():
                label = self._VOCAB_LABEL.get(field, field)
                vals = ", ".join(info["values"])
                if info["kind"] == "enum":
                    enum_lines.append(f"- {label} 【合法值仅限以下，必须从中选择】: {vals}")
                else:
                    text_lines.append(f"- {label}（示例，可超出）: {vals}")
            ctx = ("【本数据库真实字段值 — 动态读取自当前库，必须严格遵守，禁止编造库中不存在的值】\n"
                   + "\n".join(enum_lines + text_lines)
                   + "\n⚠️ enumerated 字段(organism/sample_type/disease_category/source_database/sex)"
                     "只能取上面列出的真实值；若用户提到库中不存在的内容(如其它物种)，该字段留空，切勿臆造。\n")
            return ctx
        # Fallback: the (static, possibly stale) schema_knowledge.yaml.
        if not self.sk:
            return "字段: organisms, tissues, diseases, assays"
        ctx = "常见值:\n"
        for f in ["organism", "tissue", "disease", "assay"]:
            finfo = self.sk.fields.get(f)
            if not finfo:
                continue
            top = finfo.get("top_values") if isinstance(finfo, dict) else getattr(finfo, "top_values", None)
            if not top:
                continue
            vals = []
            for v in top[:5]:
                if isinstance(v, dict):
                    vals.append(v.get("value", ""))
                else:
                    vals.append(str(v))
            if vals:
                ctx += f"- {f}: {', '.join(vals)}\n"
        return ctx

    def _parse_json_response(self, content: str) -> dict:
        """Parse JSON from LLM response — robust (Phase 26).

        Tries in order: (1) stripped + fence-trimmed text, (2) inside the
        first ```...``` block, (3) substring from first '{' to last '}'.
        Handles Kimi prose-wrapped + various code-fence styles.
        """
        text = content.strip()
        candidates: list[str] = []
        # Strategy 1: trim known fence prefixes/suffixes
        s1 = text
        if s1.startswith("```json"):
            s1 = s1[7:]
        elif s1.startswith("```"):
            s1 = s1[3:]
        if s1.endswith("```"):
            s1 = s1[:-3]
        candidates.append(s1.strip())
        # Strategy 2: inside first fenced block
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 2:
                chunk = parts[1]
                if chunk.startswith("json"):
                    chunk = chunk[4:]
                candidates.append(chunk.strip())
        # Strategy 3: substring between first '{' and last '}'
        if "{" in text and "}" in text:
            first = text.find("{")
            last = text.rfind("}")
            candidates.append(text[first:last + 1])
        for c in candidates:
            try:
                return json.loads(c)
            except (json.JSONDecodeError, ValueError):
                continue
        raise json.JSONDecodeError("no parseable JSON in response", text, 0)

    def _convert_to_parsed_query(self, user_input: str, data: dict) -> ParsedQuery:
        """Convert LLM response to ParsedQuery."""
        intent_str = data.get("intent", "SEARCH").upper()
        intent = QueryIntent[intent_str] if intent_str in QueryIntent.__members__ else QueryIntent.SEARCH
        def _lst(key):
            v = data.get(key) or []
            return v if isinstance(v, list) else [v]

        _sex = data.get("sex")
        if isinstance(_sex, str):
            _sex = _sex.strip().lower() or None
        _min_cells = data.get("min_cells")
        try:
            _min_cells = int(_min_cells) if _min_cells not in (None, "", []) else None
        except (TypeError, ValueError):
            _min_cells = None
        filters = QueryFilters(
            organisms=data.get("organisms", []),
            tissues=data.get("tissues", []),
            diseases=data.get("diseases", []),
            disease_categories=data.get("disease_categories", []),
            assays=data.get("assays", []),
            # Phase 38: expose the rest of the filter space to the LLM so its
            # understanding reaches the structured engine instead of being dumped
            # into free_text (which only did a useless tissue/disease/title LIKE).
            cell_types=_lst("cell_types"),
            sample_types=_lst("sample_types"),
            sex=_sex,
            source_databases=[s.lower() for s in _lst("source_databases")],
            min_cells=_min_cells,
            published_after=data.get("published_after") or None,
            published_before=data.get("published_before") or None,
            exclude_diseases=data.get("exclude_diseases", []),
            exclude_disease_categories=data.get("exclude_disease_categories", []),
            exclude_tissues=data.get("exclude_tissues", []),
            exclude_sample_types=_lst("exclude_sample_types"),
            free_text=data.get("free_text"),
        )
        # Phase 38: deterministic anti-hallucination guard on top of the dynamic
        # injection. A temp=1 thinking model can still occasionally invent a value
        # the DB doesn't have (e.g. organism "Rattus norvegicus" on a human-only
        # DB). Drop enumerated values absent from the live vocab — but ONLY if a
        # valid value remains, so a genuine request for absent data still yields 0
        # results rather than silently dropping the filter.
        self._enforce_live_vocab(filters)
        # Bug 1 fix: V1 returned filters but never populated entities, so
        # OntologyResolver downstream got an empty list and skipped expansion.
        # Reverse-derive entities from the filters so resolve_all() works.
        entities: list[BioEntity] = []
        for value in filters.tissues:
            entities.append(BioEntity(text=value, entity_type="tissue", normalized_value=value))
        for value in filters.diseases:
            entities.append(BioEntity(text=value, entity_type="disease", normalized_value=value))
        for value in filters.cell_types:
            entities.append(BioEntity(text=value, entity_type="cell_type", normalized_value=value))
        for value in filters.organisms:
            entities.append(BioEntity(text=value, entity_type="organism", normalized_value=value))
        for value in filters.assays:
            entities.append(BioEntity(text=value, entity_type="assay", normalized_value=value))
        # Phase 26: extract aggregation spec when the LLM signals
        # STATISTICS intent or returns an explicit aggregation block.
        agg_data = data.get("aggregation")
        aggregation = None
        if agg_data and isinstance(agg_data, dict):
            gb = agg_data.get("group_by") or []
            if isinstance(gb, str):
                gb = [gb]
            if gb:
                aggregation = AggregationSpec(
                    group_by=list(gb),
                    metric=agg_data.get("metric", "count"),
                )
        # Phase 37: superlative-ranking fallback. The LLM intermittently misses
        # "which X has the most data" / "\u54ea\u79cdX\u6700\u591a" / "which X is most abundant"
        # as an aggregation and returns intent=SEARCH with no aggregation block \u2014
        # so the query found 0 results (CP03/CP05/CP06). Re-derive a GROUP BY from
        # the deterministic rule detector when the LLM gave none, and align intent.
        if aggregation is None:
            rule_agg = _rule_parser()._detect_aggregation(user_input.lower(), entities)
            if rule_agg is not None:
                aggregation = rule_agg
                if intent in (QueryIntent.SEARCH, QueryIntent.EXPLORE):
                    intent = QueryIntent.STATISTICS

        return ParsedQuery(
            intent=intent,
            filters=filters,
            entities=entities,
            aggregation=aggregation,
            target_level="sample",
            original_text=user_input,
            language="zh" if any('\u4e00' <= c <= '\u9fff' for c in user_input) else "en",
            confidence=data.get("confidence", 0.85),
            parse_method="v1_llm",
            strict_mode=bool(data.get("strict_mode", False)),
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

