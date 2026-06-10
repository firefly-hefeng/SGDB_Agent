"""Intent parser: converts natural language to structured QueryIntent."""

import json
from pathlib import Path
from typing import Any

from src.discovery.config import get_settings
from src.discovery.llm_tracing import trace_llm_call
from src.discovery.models import QueryIntent
from src.discovery.synonym_map import expand_intent_terms


def _anthropic_first_text(response: Any) -> str:
    """Pull the first ``TextBlock``'s ``.text`` from an Anthropic response.

    The SDK union now includes thinking, tool-use, and code-execution blocks
    that have no ``.text`` attribute. We only ever ask for free-form text so
    skipping non-text blocks is correct.
    """
    for block in response.content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    return ""


class IntentParser:
    """Parses natural language queries into structured intents."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "intent_parser_v1.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        # Fallback default prompt
        return (
            "You are a biomedical query parser. Extract structured fields from the user's query.\n\n"
            "Output JSON with these fields:\n"
            '- disease: list of diseases mentioned (use standard English names)\n'
            '- tissue: list of tissues/anatomical structures\n'
            '- tech: list of sequencing technologies (e.g., "scRNA-seq", "snRNA-seq", "10x Genomics")\n'
            '- species: list of species (default ["Homo sapiens"] if not specified)\n'
            '- keywords: other important keywords from original query\n'
            '- time_hint: if user mentions "recent", "latest", "2024", etc.\n\n'
            "Rules:\n"
            "- Use English for all extracted values.\n"
            "- If a field is not mentioned, return empty list [].\n"
            "- Do NOT infer beyond what the user said.\n\n"
            "User query: {query}\n\n"
            "Output JSON only, no markdown formatting."
        )

    def _parse_with_llm(self, query: str) -> dict:
        """Call LLM to parse intent. Fallback to local rule-based parser."""
        # Try LLM if API key is available
        if self.settings.anthropic_api_key and self.settings.llm_provider == "anthropic":
            try:
                return self._parse_with_anthropic(query)
            except Exception:
                pass

        if self.settings.openai_api_key and self.settings.llm_provider == "openai":
            try:
                return self._parse_with_openai(query)
            except Exception:
                pass

        # Fallback: simple keyword extraction
        return self._fallback_parse(query)

    def _parse_with_anthropic(self, query: str) -> dict:
        import anthropic

        client_kwargs = {
            "api_key": self.settings.anthropic_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = anthropic.Anthropic(**client_kwargs)
        prompt = self._prompt.format(query=query)

        with trace_llm_call(
            "anthropic", self.settings.llm_model, "intent_parse"
        ) as stats:
            response = client.messages.create(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                temperature=self.settings.llm_temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "input_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "output_tokens", 0) or 0

        content = _anthropic_first_text(response)
        # Extract JSON from response
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())

    def _parse_with_openai(self, query: str) -> dict:
        from openai import OpenAI

        client_kwargs = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = OpenAI(**client_kwargs)
        prompt = self._prompt.format(query=query)
        model = self.settings.llm_model

        with trace_llm_call("openai", model, "intent_parse") as stats:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                response_format={"type": "json_object"},
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "completion_tokens", 0) or 0

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _fallback_parse(self, query: str) -> dict[str, Any]:
        """Simple rule-based fallback parser when LLM is unavailable.

        Handles both English and Chinese keywords. Chinese maps map to the
        same canonical English values used downstream by the adapters
        (e.g. ``"阿尔茨海默病"`` → ``"Alzheimer disease"``), so the
        adapter term builders don't need to know about Chinese at all.
        """
        q_lower = query.lower()

        # English keyword tables.
        disease_map_en = {
            "alzheimer": "Alzheimer disease",
            "parkinson": "Parkinson disease",
            "cancer": "cancer",
            "tumor": "tumor",
            "diabetes": "diabetes",
            "covid": "COVID-19",
            "ibd": "inflammatory bowel disease",
            "multiple sclerosis": "multiple sclerosis",
            "glioblastoma": "glioblastoma",
            "melanoma": "melanoma",
        }
        tissue_map_en = {
            "brain": "brain",
            "hippocampus": "hippocampus",
            "cortex": "cerebral cortex",
            "prefrontal": "prefrontal cortex",
            "liver": "liver",
            "lung": "lung",
            "heart": "heart",
            "blood": "blood",
            "kidney": "kidney",
            "pancreas": "pancreas",
            "skin": "skin",
            "intestine": "intestine",
            "colon": "colon",
            "retina": "retina",
            "muscle": "muscle",
            "bone marrow": "bone marrow",
        }
        tech_map_en = {
            "scrna-seq": "scRNA-seq",
            "sc-rna": "scRNA-seq",
            "single cell rna": "scRNA-seq",
            "snrna-seq": "snRNA-seq",
            "sn-rna": "snRNA-seq",
            "single nucleus rna": "snRNA-seq",
            "10x": "10x Genomics",
            "smart-seq": "Smart-seq",
            "smart-seq2": "Smart-seq2",
            "cite-seq": "CITE-seq",
            "atac-seq": "ATAC-seq",
        }

        # Chinese keyword tables. Match against the *raw* query (not lower)
        # because lower() is a no-op for CJK and gives slightly clearer code.
        disease_map_zh = {
            "阿尔茨海默": "Alzheimer disease",
            "阿茲海默": "Alzheimer disease",  # Traditional / Taiwan variant
            "帕金森": "Parkinson disease",
            "癌症": "cancer",
            "肿瘤": "tumor",
            "腫瘤": "tumor",
            "糖尿病": "diabetes",
            "新冠": "COVID-19",
            "新型冠状": "COVID-19",
            "covid": "COVID-19",  # very common bilingual mix
            "炎症性肠病": "inflammatory bowel disease",
            "多发性硬化": "multiple sclerosis",
            "胶质母细胞瘤": "glioblastoma",
            "黑色素瘤": "melanoma",
            "乳腺癌": "breast cancer",
        }
        tissue_map_zh = {
            "大脑": "brain",
            "脑": "brain",
            "海马": "hippocampus",
            "皮层": "cerebral cortex",
            "皮質": "cerebral cortex",
            "前额叶": "prefrontal cortex",
            "前額葉": "prefrontal cortex",
            "肝": "liver",
            "肝脏": "liver",
            "肺": "lung",
            "心脏": "heart",
            "心臟": "heart",
            "血液": "blood",
            "肾": "kidney",
            "腎": "kidney",
            "胰腺": "pancreas",
            "胰島": "pancreatic islet",
            "胰岛": "pancreatic islet",
            "皮肤": "skin",
            "皮膚": "skin",
            "肠": "intestine",
            "腸": "intestine",
            "结肠": "colon",
            "結腸": "colon",
            "视网膜": "retina",
            "視網膜": "retina",
            "肌肉": "muscle",
            "骨髓": "bone marrow",
            "外周血": "peripheral blood",
            "支气管": "bronchoalveolar lavage",
        }
        tech_map_zh = {
            "单细胞": "scRNA-seq",
            "單細胞": "scRNA-seq",
            "单核": "snRNA-seq",
            "單核": "snRNA-seq",
            "测序": "RNA-seq",
            "測序": "RNA-seq",
        }

        disease: list[str] = []
        tissue: list[str] = []
        tech: list[str] = []
        species: list[str] = ["Homo sapiens"]
        time_hint: str | None = None

        for key, value in disease_map_en.items():
            if key in q_lower and value not in disease:
                disease.append(value)
        for key, value in disease_map_zh.items():
            if key in query and value not in disease:
                disease.append(value)

        for key, value in tissue_map_en.items():
            if key in q_lower and value not in tissue:
                tissue.append(value)
        for key, value in tissue_map_zh.items():
            if key in query and value not in tissue:
                tissue.append(value)

        for key, value in tech_map_en.items():
            if key in q_lower and value not in tech:
                tech.append(value)
        for key, value in tech_map_zh.items():
            if key in query and value not in tech:
                tech.append(value)

        # Species (EN + ZH)
        if "mouse" in q_lower or "mus musculus" in q_lower or "小鼠" in query or "鼠" in query:
            species = ["Mus musculus"]
        elif "human" in q_lower or "homo sapiens" in q_lower or "人类" in query or "人類" in query:
            species = ["Homo sapiens"]
        if "zebrafish" in q_lower or "斑马鱼" in query or "斑馬魚" in query:
            species = ["Danio rerio"]

        # Time hint (EN + ZH)
        if any(t in q_lower for t in ("recent", "latest", "new")) or any(
            t in query for t in ("最新", "最近", "新")
        ):
            time_hint = "recent"

        return {
            "disease": disease,
            "tissue": tissue,
            "tech": tech,
            "species": species,
            # Preserve the raw query as a single keyword — this is the
            # convention `geo._build_term` uses for the relevance term.
            "keywords": [query],
            "time_hint": time_hint,
            "restrict_sources": _detect_source_restriction(query),
            "negative_terms": _detect_negation(query),
        }

    def parse(self, query: str) -> QueryIntent:
        """Parse a natural language query into structured intent.

        Args:
            query: User's natural language query.

        Returns:
            QueryIntent with extracted fields, optionally expanded by the
            UBERON/MONDO-lite synonym map (controlled by the
            ``SYNONYM_EXPANSION_ENABLED`` setting; default true).
        """
        raw = self._parse_with_llm(query)
        # Source-restriction: trust the LLM if it returned a list, otherwise
        # always pattern-match the original query as a backstop. The pattern
        # matcher is conservative (only fires on explicit source names) so
        # adding it as a fallback does not introduce false positives.
        restrict = _as_str_list(raw.get("restrict_sources")) or _detect_source_restriction(query)
        # Negative terms: trust the LLM if present; otherwise fall back to the
        # conservative regex pattern matcher (catches "NOT X" / "excluding Y").
        negative = _as_str_list(raw.get("negative_terms")) or _detect_negation(query)
        intent = QueryIntent(
            disease=_as_str_list(raw.get("disease")),
            tissue=_as_str_list(raw.get("tissue")),
            tech=_sanitize_tech(_as_str_list(raw.get("tech"))),
            species=_as_str_list(raw.get("species")) or ["Homo sapiens"],
            keywords=_as_str_list(raw.get("keywords")),
            time_hint=_as_optional_str(raw.get("time_hint")),
            restrict_sources=restrict if restrict else None,
            negative_terms=negative,
        )
        if self.settings.synonym_expansion_enabled:
            intent = expand_intent_terms(intent)
        return intent


# Descriptive nouns that the LLM sometimes lists as ``tech`` (e.g.
# Kimi puts "single cell atlas" into ``tech`` for rs-019). These describe
# a dataset *kind*, not an assay, so AND-joining them into the GEO search
# term kills recall (rs-019 returned 0/350 zebrafish brain GSE entries
# because the GEO term required ``AND ("single cell atlas")``). The
# sanitiser strips them and infers ``scRNA-seq`` when "atlas" was present,
# matching the prompt rule added in EXP-20260513-03.
_TECH_DESCRIPTOR_TOKENS = frozenset(
    {
        "atlas",
        "single cell atlas",
        "single-cell atlas",
        "scrna atlas",
        "single cell",
        "single-cell",
        "dataset",
        "datasets",
        "data",
    }
)


def _sanitize_tech(tech: list[str]) -> list[str]:
    """Strip descriptive nouns from the LLM-parsed tech list.

    Adds ``scRNA-seq`` as a fallback if the user said "atlas" and the
    sanitiser would otherwise leave tech empty.
    """
    saw_atlas = False
    cleaned: list[str] = []
    for t in tech:
        low = t.strip().lower()
        if low in _TECH_DESCRIPTOR_TOKENS:
            if "atlas" in low:
                saw_atlas = True
            continue
        cleaned.append(t)
    if saw_atlas and not cleaned:
        cleaned.append("scRNA-seq")
    return cleaned


def _as_str_list(value: Any) -> list[str]:
    """Coerce an LLM-returned field into ``list[str]``.

    LLMs occasionally return ``None``, a bare string, or nested lists where a
    list of strings was promised. Be defensive: drop empty / non-string entries
    rather than failing schema validation downstream.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item:
                out.append(item)
            elif item is not None:
                out.append(str(item))
        return out
    return [str(value)]


_SOURCE_ALIASES: dict[str, list[str]] = {
    # Canonical adapter name → user-facing aliases (lowercase).
    # Match the longest alias first so "cellxgene" wins over "cell" tokens.
    "cellxgene": ["cellxgene", "cell × gene", "cell x gene", "czi cellxgene", "czi"],
    "geo": ["geo", "ncbi geo", "gene expression omnibus"],
    "ebi": ["ebi", "biostudies", "ebi biostudies", "arrayexpress"],
    "scea": ["scea", "single cell expression atlas", "expression atlas"],
    "hca": ["hca", "human cell atlas"],
}


import re as _re


# Conservative negation pattern: catches "NOT X", "not X", "without X",
# "excluding X", "non-X" — each up to the next clause boundary or end of
# query. We extract the *negated phrase* (a short noun phrase) and pass
# it to the downstream consumer; we do NOT recurse into nested negation.
_NEGATION_PATTERNS: list[tuple[_re.Pattern[str], int]] = [
    (_re.compile(r"\b(?:NOT|not)\s+([\w\-' ]+?)(?=$|[,.;!?]|\b(?:and|or|with)\b)", _re.IGNORECASE), 1),
    (_re.compile(r"\b(?:without|excluding|except)\s+([\w\-' ]+?)(?=$|[,.;!?]|\b(?:and|or|with)\b)", _re.IGNORECASE), 1),
]


def _detect_negation(query: str) -> list[str]:
    """Pattern-match conservative negation phrases out of the query.

    Returns the *list of excluded terms* as the user phrased them. The
    LLM path is preferred (richer semantics); this is a regex backstop
    so rule-only fallback handles trivial cases like ``"PD that is NOT
    Alzheimer"`` instead of returning empty positive fields.
    """
    if not query:
        return []
    found: list[str] = []
    for pat, group in _NEGATION_PATTERNS:
        for m in pat.finditer(query):
            term = m.group(group).strip()
            if term and term.lower() not in {t.lower() for t in found}:
                found.append(term)
    return found


def _detect_source_restriction(query: str) -> list[str]:
    """Detect explicit source-database mentions in a free-text query.

    Conservative: only fires when the query *names* the source. Returns
    canonical adapter names. Empty list means "no restriction".
    """
    q = query.lower()
    found: list[str] = []
    for canonical, aliases in _SOURCE_ALIASES.items():
        for alias in aliases:
            if alias in q:
                found.append(canonical)
                break
    return found


def _as_optional_str(value: Any) -> str | None:
    """Coerce an LLM-returned scalar into ``str | None``.

    Some LLMs return ``[]`` or ``{}`` when no value applies; we normalise those
    to ``None`` so the Pydantic schema (``str | None``) stays consistent.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, (list, tuple, dict)):
        return None
    return str(value)
