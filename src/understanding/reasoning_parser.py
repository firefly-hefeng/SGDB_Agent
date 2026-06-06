"""
ReasoningParser — Phase 14.

A Chain-of-Thought (CoT) parser that emits a structured trace of its
own reasoning. Produces:

- ParsedQuery (compatible with the existing pipeline)
- ReasoningTrace (per-step rationale, alternatives, confidence)

Design choices:
- One LLM call returning a single JSON document with explicit ``steps``,
  rather than 6 chained calls. This keeps latency / cost the same as
  the current parser while still surfacing CoT.
- Schema injection uses the new SchemaKnowledgeTree with progressive
  scope so the prompt only contains tables/fields relevant to the
  query (much smaller, more accurate per Spider/BIRD literature).
- Pure rule fallback per-step: if the LLM returns invalid JSON or is
  missing required keys, each step independently falls back to the
  rule QueryParser's extractor; we never lose the whole turn.
- Refinement-aware: previous-turn ParsedQuery (in SessionContext) is
  passed in so the LLM can reuse the prior schema scope.

Caller contract: ``ReasoningParser.parse_with_trace(query, ctx) ->
(parsed, trace)``. The ``parse`` method (IQueryParser protocol) returns
just the ParsedQuery — the trace is attached as ``parsed._trace`` so
callers that *do* care can grab it without breaking the protocol.
"""

from __future__ import annotations

import json
import logging
import re

from ..core.interfaces import IQueryParser, ILLMClient
from ..core.models import (
    AggregationSpec,
    BioEntity,
    OrderingSpec,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    SessionContext,
)
from ..core.reasoning import ReasoningStep, ReasoningTrace
from ..knowledge.schema_tree import RenderConfig, SchemaKnowledgeTree

logger = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────


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


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        for chunk in parts:
            chunk = chunk.strip()
            if not chunk:
                continue
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{"):
                return chunk
    return text


def _extract_json(text: str) -> dict:
    text = _strip_code_fence(text)
    # Empty / no-content response from LLM (e.g. finish=length, output truncated)
    if not text:
        raise ValueError("empty LLM response")
    # Greedy curly-brace extraction in case of trailing prose
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object found in: {text[:120]!r}")
    depth = 0
    in_str = False
    str_ch = ""
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == str_ch:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            str_ch = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unterminated JSON object")


def _detect_language(text: str) -> str:
    chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
    return "zh" if chinese_chars > len(text) * 0.1 else "en"


# ─── Parser ──────────────────────────────────────────────────────────


PROMPT_SYSTEM = (
    "You are a bioinformatics SQL planner. Convert a user query into a "
    "minimal JSON plan. Output JSON ONLY, no markdown fences, no prose."
)


PROMPT_INSTRUCTIONS = """
Return ONLY this JSON shape (use empty arrays/null when not present):
{"intent":"SEARCH|COMPARE|STATISTICS|EXPLORE|DOWNLOAD|LINEAGE",
 "target":"sample|project|series|celltype",
 "is_refinement":false,
 "entities":[{"text":"","type":"tissue|disease|cell_type|organism|assay","value":""}],
 "filters":{"tissues":[],"diseases":[],"organisms":[],"cell_types":[],"assays":[],
            "source_databases":[],"sample_types":[],"disease_categories":[],
            "tissue_systems":[],"sex":null,"min_cells":null,"has_h5ad":null,
            "require_pmid":null,"require_doi":null,"require_h5ad":null,
            "age_min":null,"age_max":null,"age_unit":null,
            "free_text":null},
 "negation":{"exclude_tissues":[],"exclude_diseases":[],"exclude_organisms":[],
             "exclude_source_databases":[],"exclude_sample_types":[]},
 "temporal":{"published_after":null,"published_before":null},
 "strict_mode":false,
 "plan":{"main_table":"unified_samples","needs_ontology":true,
         "use_indexed_fastpath":true,
         "aggregation":null,"ordering":null,"limit":100},
 "confidence":0.9,
 "reasoning":"≤30 words: why these filters/strict_mode/refinement"}

Rules:
- 中→英: 肝→liver, 肺癌→Lung Cancer, 人/人类→Homo sapiens (human), 小鼠→Mus musculus (mouse).
- Prefer standardised columns (★) when their top_values match: tissue_standard, disease_category, organism_common, sample_type.
- strict_mode=true if user wrote: strictly|exactly|literally|specifically|only|just|严格|仅限|只要.
- is_refinement=true if user wrote: these|those|the ones|now|这些|其中|上面|只看|改为|换成. PRIOR_FILTERS will carry over unless explicitly replaced.
- Source aliases: GEO→geo, EBI/ArrayExpress→ebi, NCBI/SRA→ncbi, EGA→ega, CellXGene→cellxgene, HCA→hca, HTAN→htan.
- Disease umbrella: cancer/tumor/neoplasm → disease_categories=["neoplasm"] UNLESS strict_mode.
- require_pmid=true when user asks: with PMID, has PMID, linked to a paper, has citation, 有 PMID, 有引用文献.
- require_doi=true when user asks: with DOI, has DOI, 有 DOI.
- require_h5ad=true when user asks: with downloadable data, with h5ad, downloadable, 可下载数据.
- DO NOT add an assay filter for generic "scRNA-seq"/"single-cell RNA-seq"/"single cell"/"single-cell"/单细胞 — the entire catalog is single-cell, so those tokens describe the data, not a filter. Only emit assays=[...] when the user names a specific kit/platform (10x, Smart-seq, sci-RNA-seq, Drop-seq, BD Rhapsody, Seq-Well, etc.).
- Age parsing (age_min / age_max are floats in years; age_unit is "year"|"month"|"week"|"day"):
  - "over 60", "older than 50", "above 65", "≥40 years" → age_min=X
  - "under 30", "younger than 20", "below 18", "≤18 years" → age_max=X
  - "between 30 and 50", "30-50 year old", "ages 25 to 45" → age_min=lo, age_max=hi
  - "elderly", "geriatric", "senior" → age_min=65
  - "adult" → age_min=18
  - "pediatric", "children" → age_max=17
  - "infant" → age_min=0, age_max=2, age_unit="year"
  - "fetal", "embryonic" → use development_stage NOT age (don't fill age_*)
  - 中文: "60岁以上"→age_min=60; "X岁以下"→age_max=X; "老年"→age_min=65; "儿童"→age_max=17.

CRITICAL: do NOT over-constrain the SQL. Emit ONLY the filters the user
explicitly named. Two anti-patterns to avoid:

  1. "lung cancer" → diseases=["lung cancer"], DO NOT also add tissues=["lung"].
     The disease entity "lung cancer" already implies the lung context;
     adding a separate tissue filter intersects with literal tissue='lung'
     and drops most cancer samples whose tissue is "tumour", "lymph node",
     "metastasis", etc. Same for "breast cancer", "pancreatic cancer".

  2. "tumor immune microenvironment" → a multi-word concept. Do NOT silently
     drop the qualifier "immune microenvironment" and keep only "tumor".
     If the concept can't be split into clean tissue/disease/cell_type
     entities, set free_text="tumor immune microenvironment" so the
     engine can run a textual search instead of a misleading sparse query.

When in doubt, prefer free_text="..." over a partial structured match."""


def _empty_step_output(stage: str) -> dict:
    return {}


# Phase 32: generic "single-cell" tokens describe the catalog, not a kit.
# The DB's `assay` column holds specific platform names ("10x 3' v3",
# "Smart-seq2", "sci-RNA-seq3", ...) — none contains the literal string
# "single-cell". Letting the LLM emit `assays=["single-cell"]` produces
# `assay LIKE '%single-cell%'` which matches zero rows and silently
# kills the result set. Strip those tokens; the platform-specific ones
# (10x, Smart-seq, sci-RNA-seq, Drop-seq, ...) survive.
_GENERIC_ASSAY_TOKENS = {
    "single-cell", "single cell", "singlecell",
    "scrna-seq", "scrnaseq", "scrna",
    "single-cell rna-seq", "single cell rna-seq", "single-cell rna seq",
    "single-cell rnaseq", "rna-seq", "rnaseq", "rna seq",
    "单细胞", "单细胞测序", "单细胞 rna-seq", "单细胞测序 rna-seq",
}


def _drop_redundant_cancer_tissue(tissues: list[str], diseases: list[str]) -> list[str]:
    """Drop a tissue filter that's already implied by a cancer-disease.

    Phase 32 F17: the LLM tends to over-constrain. If the user asks for
    "lung cancer" the LLM frequently emits `tissues=["lung"]` AND
    `diseases=["lung cancer"]`. The intersection requires `tissue` to
    *literally* be "lung", which excludes the majority of lung-cancer
    samples whose tissue is "tumour", "lymph node metastasis",
    "primary tumor", etc. — dropping recall from thousands to a handful.

    Heuristic: when a tissue token is a substring of a cancer-flavoured
    disease, the disease already covers it; the tissue is redundant
    (and harmful). Cancer keywords: "cancer", "carcinoma", "tumor",
    "tumour", "neoplasm", "adenocarcinoma", "sarcoma", "leukemia",
    "lymphoma", "myeloma", "melanoma", "blastoma", "glioma".

    Keeps the tissue when:
      - no disease contains a cancer keyword
      - the tissue isn't a substring of any cancer disease
      - the tissue equals the disease verbatim (then the user
        actually picked the tissue too — leave it alone)
    """
    if not tissues or not diseases:
        return tissues
    cancer_kw = (
        "cancer", "carcinoma", "tumor", "tumour", "neoplasm",
        "adenocarcinoma", "sarcoma", "leukemia", "leukaemia",
        "lymphoma", "myeloma", "melanoma", "blastoma", "glioma",
    )
    # Map common organ → its adjective form so morphologically-modified
    # cancer names ("pancreatic cancer", "renal cancer") are still
    # recognised as subsuming their tissue.
    morph_map = {
        "pancreas": ("pancreatic",),
        "kidney": ("renal", "nephric"),
        "liver": ("hepatic", "hepatocellular"),
        "stomach": ("gastric",),
        "bone": ("osteo", "skeletal"),
        "blood": ("hematological", "haematological", "leukem", "lymphom"),
        "intestine": ("intestinal", "colorectal", "colonic"),
        "lung": ("pulmonary",),
        "brain": ("cerebral", "glio"),
        "skin": ("cutaneous", "dermal"),
        "thyroid": ("thyroidal",),
        "ovary": ("ovarian",),
        "uterus": ("uterine", "endometrial"),
        "prostate": ("prostatic",),
        "breast": ("mammary",),
    }
    cancer_diseases = [
        d.lower() for d in diseases
        if isinstance(d, str) and any(kw in d.lower() for kw in cancer_kw)
    ]
    if not cancer_diseases:
        return tissues
    kept: list[str] = []
    for t in tissues:
        if not isinstance(t, str) or not t.strip():
            continue
        tlow = t.strip().lower()
        # Subsumed if literal substring (lung in "lung cancer") OR any
        # morphological variant is a substring (pancreatic in
        # "pancreatic cancer").
        variants = (tlow,) + morph_map.get(tlow, ())
        redundant = any(
            tlow != d and any(v in d for v in variants)
            for d in cancer_diseases
        )
        if not redundant:
            kept.append(t)
    return kept


def _extract_age_range(filt: dict) -> tuple[float, float] | None:
    """Convert the LLM's age_min/age_max/age_unit triple into a (lo, hi)
    tuple in years.

    The DB stores `age_numeric_min` / `age_numeric_max` as floats whose
    unit lives in `age_unit_normalized` (year, month, week, day, hour).
    We standardise to *years* at parse time so the SQL engine can do a
    single comparison rather than juggling units.

    Returns None when no age constraint was extracted, so downstream
    code can skip the predicate entirely.
    """
    lo = filt.get("age_min")
    hi = filt.get("age_max")
    unit = (filt.get("age_unit") or "year").strip().lower()
    if lo is None and hi is None:
        return None

    # Convert to years. Unknown / unsupported units fall back to "year".
    factor = {
        "year": 1.0,
        "years": 1.0,
        "yr": 1.0,
        "month": 1.0 / 12.0,
        "months": 1.0 / 12.0,
        "mo": 1.0 / 12.0,
        "week": 1.0 / 52.1429,
        "weeks": 1.0 / 52.1429,
        "wk": 1.0 / 52.1429,
        "day": 1.0 / 365.25,
        "days": 1.0 / 365.25,
        "hour": 1.0 / (365.25 * 24),
    }.get(unit, 1.0)

    try:
        lo_f = float(lo) * factor if lo is not None else 0.0
        hi_f = float(hi) * factor if hi is not None else 200.0
    except (TypeError, ValueError):
        return None
    if lo_f > hi_f:
        # Defensive: swap if user / LLM crossed bounds.
        lo_f, hi_f = hi_f, lo_f
    return (lo_f, hi_f)


def _clean_generic_assay_tokens(values: list[str]) -> list[str]:
    """Drop catalog-wide descriptors like 'single-cell' from assay filters.

    Returns the input list minus any entry whose normalised (lowercased,
    stripped) form is in `_GENERIC_ASSAY_TOKENS`. Specific kit names
    (10x, Smart-seq2, sci-RNA-seq3, etc.) are preserved verbatim.
    """
    cleaned: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        norm = v.strip().lower()
        if norm in _GENERIC_ASSAY_TOKENS:
            continue
        cleaned.append(v)
    return cleaned


class ReasoningParser(IQueryParser):
    """CoT-style LLM parser with explicit reasoning trace."""

    def __init__(
        self,
        llm: ILLMClient | None,
        schema_tree: SchemaKnowledgeTree | None = None,
        rule_parser=None,
        max_schema_chars: int = 1800,
        temperature: float = 1.0,
    ):
        self.llm = llm
        self.tree = schema_tree
        self.rule_parser = rule_parser
        self.max_schema_chars = max_schema_chars
        # Kimi only accepts temperature=1; lower values get rejected. Keep
        # the parameter for non-Kimi providers but default to 1.0.
        self.temperature = temperature

    # ── public ───────────────────────────────────────────────────
    async def parse(
        self, query: str, context: SessionContext | None = None,
    ) -> ParsedQuery:
        parsed, trace = await self.parse_with_trace(query, context)
        # Attach trace so the coordinator can read it without altering
        # the IQueryParser protocol.
        try:
            parsed.__dict__["_trace"] = trace
        except Exception:
            pass
        return parsed

    async def parse_with_trace(
        self, query: str, context: SessionContext | None = None,
    ) -> tuple[ParsedQuery, ReasoningTrace]:
        trace = ReasoningTrace()
        lang = _detect_language(query)

        # ── ID fast-track: pure GSE/GSM/PMID/DOI lookups skip the LLM.
        ids = self._extract_ids(query)
        if ids:
            id_step = trace.start("parse", "ID fast-track", input={"ids": ids})
            id_step.rationale = "Query is a structured ID lookup; skip LLM."
            id_step.output = ids
            id_step.confidence = 0.99
            id_step.end()
            parsed = self._build_id_parsed(query, ids, lang)
            return parsed, trace

        # ── Schema scope: render only the relevant subtree
        schema_chars = self.max_schema_chars
        if self.tree is not None:
            schema_step = trace.start(
                "schema", "Pick relevant schema subtree",
                input={"query": query[:120]},
            )
            scope_fields = self.tree.fields_relevant_to(query)
            schema_text = self.tree.render_for_query(
                query,
                RenderConfig(budget_chars=schema_chars, top_values_per_field=6),
            )
            schema_step.output = {
                "scope_fields": sorted(scope_fields),
                "schema_chars": len(schema_text),
            }
            schema_step.rationale = (
                f"{len(scope_fields)} field(s) relevant; "
                f"{len(schema_text)} chars rendered (budget {schema_chars})"
            )
            schema_step.end()
        else:
            schema_text = ""

        # ── Try the LLM CoT call
        if self.llm is not None:
            llm_step = trace.start(
                "reason", "LLM CoT parse",
                input={"schema_chars": len(schema_text)},
            )
            try:
                data = await self._call_llm(query, schema_text, context)
                # Materialise sub-steps from the flat plan so the UI can
                # render them: intent, entities, filters, negation,
                # temporal/strict, plan.
                stages_to_show = [
                    ("intent", "Intent + target",
                     {"intent": data.get("intent"), "target": data.get("target"),
                      "is_refinement": data.get("is_refinement", False)}),
                    ("entities", "Entities",
                     {"count": len(data.get("entities", []) or []),
                      "items": data.get("entities", [])[:6]}),
                    ("filters", "Filters",
                     {k: v for k, v in (data.get("filters") or {}).items() if v}),
                    ("negation", "Negation",
                     {k: v for k, v in (data.get("negation") or {}).items() if v}),
                    ("temporal", "Temporal + strict",
                     {**(data.get("temporal") or {}),
                      "strict_mode": data.get("strict_mode", False)}),
                    ("plan", "Plan",
                     data.get("plan") or {}),
                ]
                rationale = data.get("reasoning", "")
                for sid, title, output in stages_to_show:
                    sub = ReasoningStep(
                        stage="reason", title=f"CoT/{sid}: {title}",
                        output=output,
                        rationale=(rationale if sid == "plan" else ""),
                    )
                    sub.end()
                    trace.add(sub)
                llm_step.status = "ok"
                llm_step.confidence = float(data.get("confidence", 0.85))
                llm_step.output = {
                    "intent": data.get("intent"),
                    "filter_count": sum(
                        1 for v in (data.get("filters") or {}).values() if v
                    ),
                    "is_refinement": data.get("is_refinement", False),
                    "strict_mode": data.get("strict_mode", False),
                    "confidence": data.get("confidence", 0.85),
                }
                llm_step.rationale = (
                    rationale or "LLM produced structured plan"
                )
                llm_step.end()
                parsed = self._assemble(query, lang, data, context)
                return parsed, trace
            except Exception as e:
                llm_step.status = "warn"
                llm_step.rationale = f"LLM CoT failed → rule fallback: {e}"
                llm_step.end()
                logger.warning("LLM CoT parse failed: %s — falling back to rule", e)

        # ── Rule fallback (full parser)
        if self.rule_parser is not None:
            fb_step = trace.start("parse", "Rule parser fallback")
            try:
                parsed = await self.rule_parser.parse(query, context)
                fb_step.output = {
                    "intent": parsed.intent.name,
                    "entity_count": len(parsed.entities),
                    "confidence": parsed.confidence,
                }
                fb_step.confidence = parsed.confidence
                fb_step.rationale = "Rule-based parse succeeded."
                fb_step.end()
                return parsed, trace
            except Exception as e:
                fb_step.status = "error"
                fb_step.rationale = f"Rule parser failed too: {e}"
                fb_step.end()

        # Ultimate fallback: free text
        free = self._build_free_parsed(query, lang)
        return free, trace

    # Refinement intent signals — words that meaningfully indicate the user
    # is iterating on their prior query rather than starting a new search.
    # Phase 32: short standalone queries like "肺" must NOT be auto-treated
    # as refinements; that bug let "How many breast cancer samples?" leak
    # a phantom `disease='breast cancer'` filter into the next query.
    _REFINEMENT_HINT = re.compile(
        r"\b(?:these|those|the\s+ones?|the\s+above|same|"
        r"now|then|also|further|narrow|refine|only|just|"
        r"add|drop|remove|exclude|change|switch|replace)\b"
        r"|"
        r"(?:这些|这个|那些|那个|其中|上面|上述|只看|只要|"
        r"另外|改为|换成|加上|去掉|排除|减去)",
        re.IGNORECASE,
    )

    @classmethod
    def _query_looks_like_refinement(cls, query: str) -> bool:
        """True when the user's current text signals a refinement intent.

        Without one of the trigger words, treat the query as standalone
        and ignore any inherited SessionContext.active_filters — even if
        the LLM later claims `is_refinement=true`.
        """
        if not query:
            return False
        return bool(cls._REFINEMENT_HINT.search(query))

    # ── LLM call ─────────────────────────────────────────────────
    async def _call_llm(
        self, query: str, schema_text: str, context: SessionContext | None,
    ) -> dict:
        prior = ""
        # Only inject PRIOR_FILTERS when the user's current text actually
        # signals a refinement. A bare-tissue query like "肺" must NOT
        # inherit the previous turn's disease filter.
        if (
            context
            and context.active_filters
            and self._query_looks_like_refinement(query)
        ):
            af = context.active_filters
            prior_dict = {
                "tissues": af.tissues, "diseases": af.diseases,
                "organisms": af.organisms, "cell_types": af.cell_types,
                "source_databases": af.source_databases,
                "published_after": af.published_after,
                "published_before": af.published_before,
            }
            prior_dict = {k: v for k, v in prior_dict.items() if v not in (None, [])}
            if prior_dict:
                prior = (
                    "\nPRIOR_FILTERS (carry over unless user replaces): "
                    + json.dumps(prior_dict, ensure_ascii=False)
                )
        # Phase 14: also surface the persistent schema scope so the LLM
        # remembers which subtree we've been working in across turns.
        scope_hint = ""
        if context and getattr(context, "active_schema_fields", None):
            scope_hint = (
                "\nACTIVE_SCHEMA_SCOPE (fields touched in this session): "
                + ", ".join(context.active_schema_fields)
            )

        prompt = (
            PROMPT_SYSTEM
            + "\n\n"
            + ("SCHEMA:\n" + schema_text + "\n\n" if schema_text else "")
            + PROMPT_INSTRUCTIONS
            + prior
            + scope_hint
            + f"\n\nUser query: {query}\n"
        )
        # Kimi sometimes returns finish="length" with empty content when
        # max_tokens is exhausted by hidden CoT. We bump the cap and request
        # JSON output via system prompt; if still empty, retry once with a
        # tighter prompt.
        for attempt in (1, 2):
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                max_tokens=4096,
            )
            content = response.content if hasattr(response, "content") else str(response)
            if content.strip():
                try:
                    return _extract_json(content)
                except ValueError:
                    if attempt == 2:
                        raise
            # Retry with stricter "JSON ONLY" preamble
            prompt = (
                "OUTPUT ONLY THE JSON OBJECT. NO EXPLANATION. NO MARKDOWN.\n"
                + prompt
            )
        raise ValueError("empty LLM response after retry")

    # ── Assembly ─────────────────────────────────────────────────
    def _assemble(
        self, query: str, lang: str, data: dict,
        context: SessionContext | None,
    ) -> ParsedQuery:
        intent_str = (data.get("intent") or "SEARCH").upper()
        intent = QueryIntent[intent_str] if intent_str in QueryIntent.__members__ else QueryIntent.SEARCH

        entities: list[BioEntity] = []
        for raw in data.get("entities", []) or []:
            if not isinstance(raw, dict):
                continue
            entities.append(BioEntity(
                text=str(raw.get("text", "")),
                entity_type=str(raw.get("type", "")),
                normalized_value=raw.get("value"),
            ))

        filt = data.get("filters") or {}
        neg = data.get("negation") or {}
        temp = data.get("temporal") or {}
        plan = data.get("plan") or {}

        # Filters
        # Phase 32 F17: drop tissue tokens that are subsumed by a
        # cancer-flavoured disease (e.g. tissues=['lung'] when
        # diseases=['lung cancer'] is already present).
        _raw_tissues = list(filt.get("tissues") or [])
        _raw_diseases = list(filt.get("diseases") or [])
        _cleaned_tissues = _drop_redundant_cancer_tissue(
            _raw_tissues, _raw_diseases,
        )
        new_filters = QueryFilters(
            organisms=list(filt.get("organisms") or []),
            tissues=_cleaned_tissues,
            diseases=_raw_diseases,
            cell_types=list(filt.get("cell_types") or []),
            assays=_clean_generic_assay_tokens(filt.get("assays") or []),
            source_databases=list(filt.get("source_databases") or []),
            sample_types=list(filt.get("sample_types") or []),
            disease_categories=list(filt.get("disease_categories") or []),
            tissue_systems=list(filt.get("tissue_systems") or []),
            sex=filt.get("sex"),
            min_cells=filt.get("min_cells"),
            has_h5ad=filt.get("has_h5ad"),
            require_pmid=filt.get("require_pmid"),
            require_doi=filt.get("require_doi"),
            require_h5ad=filt.get("require_h5ad"),
            age_range=_extract_age_range(filt),
            free_text=filt.get("free_text"),
            exclude_tissues=list(neg.get("exclude_tissues") or []),
            exclude_diseases=list(neg.get("exclude_diseases") or []),
            exclude_organisms=list(neg.get("exclude_organisms") or []),
            exclude_source_databases=list(neg.get("exclude_source_databases") or []),
            exclude_sample_types=list(neg.get("exclude_sample_types") or []),
            published_after=temp.get("published_after"),
            published_before=temp.get("published_before"),
        )

        # Phase 32: require BOTH the LLM and the query text to agree on
        # refinement intent. Otherwise the LLM's `is_refinement=true` on a
        # bare standalone query (e.g. "肺") would silently inherit the
        # prior turn's disease filter via _merge_for_refinement.
        llm_says_refine = bool(data.get("is_refinement"))
        text_signals_refine = self._query_looks_like_refinement(query)
        is_refinement = llm_says_refine and text_signals_refine
        if is_refinement and context and context.active_filters:
            merged = self._merge_for_refinement(context.active_filters, new_filters)
        else:
            merged = new_filters

        agg = None
        agg_data = plan.get("aggregation")
        if isinstance(agg_data, dict) and agg_data.get("group_by"):
            agg = AggregationSpec(
                group_by=list(agg_data.get("group_by", [])),
                metric=str(agg_data.get("metric", "count")),
            )
        # scalar aggregation (e.g. "count") without group_by is a *filter*
        # query that returns a single number — skip AggregationSpec so the
        # SQL engine's regular filter path runs.
        ordering = None
        ord_data = plan.get("ordering")
        if isinstance(ord_data, dict) and ord_data.get("field"):
            ordering = OrderingSpec(
                field=str(ord_data.get("field")),
                direction=str(ord_data.get("direction", "desc")),
            )

        confidence = float(data.get("confidence", 0.85))
        target_level = data.get("target", "sample")

        return ParsedQuery(
            intent=intent,
            sub_intent="refinement" if is_refinement else "",
            complexity=QueryComplexity.MODERATE,
            entities=entities,
            filters=merged,
            target_level=target_level,
            aggregation=agg,
            ordering=ordering,
            limit=int(plan.get("limit", 100) or 100),
            original_text=query,
            language=lang,
            confidence=confidence,
            parse_method="reasoning_cot",
            strict_mode=bool(data.get("strict_mode", False)),
        )

    # ── Refinement merge (keeps in sync with parser._build_refinement_query) ──
    @staticmethod
    def _merge_for_refinement(prev: QueryFilters, new: QueryFilters) -> QueryFilters:
        def m(p, n):
            return list(n) if n else list(p) if p else []
        return QueryFilters(
            organisms=m(prev.organisms, new.organisms),
            tissues=m(prev.tissues, new.tissues),
            diseases=m(prev.diseases, new.diseases),
            cell_types=m(prev.cell_types, new.cell_types),
            assays=m(prev.assays, new.assays),
            source_databases=m(prev.source_databases, new.source_databases),
            sample_types=m(prev.sample_types, new.sample_types),
            disease_categories=m(prev.disease_categories, new.disease_categories),
            tissue_systems=m(prev.tissue_systems, new.tissue_systems),
            sex=new.sex if new.sex else prev.sex,
            exclude_tissues=list({*prev.exclude_tissues, *new.exclude_tissues}),
            exclude_diseases=list({*prev.exclude_diseases, *new.exclude_diseases}),
            exclude_organisms=list({*prev.exclude_organisms, *new.exclude_organisms}),
            exclude_source_databases=list({
                *prev.exclude_source_databases, *new.exclude_source_databases}),
            exclude_sample_types=list({*prev.exclude_sample_types,
                                        *new.exclude_sample_types}),
            min_cells=new.min_cells if new.min_cells is not None else prev.min_cells,
            min_citation_count=(
                new.min_citation_count if new.min_citation_count is not None
                else prev.min_citation_count
            ),
            has_h5ad=new.has_h5ad if new.has_h5ad is not None else prev.has_h5ad,
            published_after=new.published_after or prev.published_after,
            published_before=new.published_before or prev.published_before,
            project_ids=prev.project_ids,
            sample_ids=prev.sample_ids,
            pmids=prev.pmids,
            dois=prev.dois,
        )

    # ── Helpers ──────────────────────────────────────────────────
    @staticmethod
    def _extract_ids(text: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for kind, pat in _ID_RE.items():
            m = pat.findall(text)
            if m:
                out[kind] = [str(x).upper() if kind != "doi" else str(x) for x in m]
        return out

    @staticmethod
    def _build_id_parsed(query: str, ids: dict[str, list[str]], lang: str) -> ParsedQuery:
        f = QueryFilters()
        if "geo_project" in ids:
            f.project_ids.extend(ids["geo_project"])
        if "sra_project" in ids:
            f.project_ids.extend(ids["sra_project"])
        if "sra_study" in ids:
            f.project_ids.extend(ids["sra_study"])
        if "geo_sample" in ids:
            f.sample_ids.extend(ids["geo_sample"])
        if "sra_sample" in ids:
            f.sample_ids.extend(ids["sra_sample"])
        if "biosample" in ids:
            f.sample_ids.extend(ids["biosample"])
        if "pmid" in ids:
            f.pmids.extend(ids["pmid"])
        if "doi" in ids:
            f.dois.extend(ids["doi"])
        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=f,
            target_level="sample" if (f.sample_ids or f.pmids or f.dois) else "project",
            original_text=query,
            language=lang,
            confidence=0.99,
            parse_method="reasoning_id_fasttrack",
        )

    @staticmethod
    def _build_free_parsed(query: str, lang: str) -> ParsedQuery:
        return ParsedQuery(
            intent=QueryIntent.SEARCH,
            filters=QueryFilters(free_text=query),
            target_level="sample",
            original_text=query,
            language=lang,
            confidence=0.30,
            parse_method="reasoning_free",
        )


__all__ = ["ReasoningParser"]
