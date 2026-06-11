"""Per-source result re-ranking.

The first live baseline (BASELINE_v1.md) showed that NCBI's default ranking
keeps canonical seed datasets at p>10 for most queries. This module re-orders
each source's top-K candidates by query relevance before they reach the user.

Backends:

- ``LexicalReranker`` — token-overlap with a small phrase / title bonus.
  Free, fast, deterministic. Found to *regress* MRR in EXP-20260511-11
  (over-weights raw token overlap, demotes broader-relevance hits); kept
  for the ablation but no longer the default.
- ``IntentFeatureReranker`` — structured-intent-aware scorer:
  field-coverage > species-match > co-occurrence > recency > keyword
  overlap > mirror confirmation. Free, fast, deterministic. Designed to
  beat the no-rerank baseline (A4) by promoting results that satisfy
  *more* of the intent simultaneously rather than results that simply
  contain many query tokens.
- ``LLMReranker`` — asks the LLM for a re-scored ordering. Better for
  semantic matches ("PFC" ≈ "prefrontal cortex") but costs a call per
  query. Opt-in via settings.

The router applies the configured reranker after every adapter returns;
sources are reranked independently to preserve multi-source diversity.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from abc import ABC, abstractmethod

from src.discovery.config import get_settings
from src.discovery.llm_tracing import trace_llm_call
from src.discovery.models import DatasetResult, QueryIntent

log = logging.getLogger("api_routing.reranker")

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\-]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1}


def _phrases(values: list[str]) -> list[str]:
    """Return non-empty lower-case phrases. Used for substring matching of
    multi-word intent terms (e.g. ``"prefrontal cortex"``).
    """
    return [v.lower().strip() for v in values if v and v.strip()]


# Generic head-noun tokens that are not specific enough to count as a
# match on their own. ``disease`` / ``syndrome`` / ``cancer`` etc. are
# common across many titles; matching on them alone produces false hits.
_GENERIC_HEAD_NOUNS = frozenset(
    {
        "disease", "syndrome", "disorder", "deficiency", "atlas",
        "type", "cell", "cells", "tissue", "tissues", "system",
        "sequencing", "seq", "rna", "dna", "single", "nucleus",
    }
)


def _any_phrase_in(phrases: list[str], text: str) -> bool:
    """Return True when *any* phrase matches the text in either of two ways:

    1. The full lower-cased phrase appears as a substring (covers
       multi-word terms like ``"prefrontal cortex"``).
    2. Any of the phrase's *specific* tokens — length ≥ 3 and not in
       ``_GENERIC_HEAD_NOUNS`` — appears as a word in the text.

    The second pass is what lets ``"Alzheimer disease"`` match a title
    containing just ``"Alzheimer"`` (the head noun ``disease`` is
    generic, but ``alzheimer`` is specific). Without it the substring
    pass would miss apostrophe variants, comma-separated forms, etc.,
    and the synonym map would have to enumerate every surface form.
    """
    if not phrases or not text:
        return False
    t = text.lower()
    text_tokens = set(_TOKEN_RE.findall(t))
    for p in phrases:
        if p in t:
            return True
        # Phrase-token fallback. Skip phrases that are themselves just a
        # head noun (e.g. ``"cell"``) so they never match alone.
        for tok in _TOKEN_RE.findall(p):
            if (
                len(tok) >= 3
                and tok not in _GENERIC_HEAD_NOUNS
                and tok in text_tokens
            ):
                return True
    return False


def _parse_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"(19|20)\d{2}", str(date_str))
    if not m:
        return None
    try:
        y = int(m.group(0))
    except ValueError:
        return None
    return y if 1900 <= y <= 2100 else None


class Reranker(ABC):
    """Reorders a list of results in place; returns the new list."""

    @abstractmethod
    def rerank(
        self, query: str, intent: QueryIntent, results: list[DatasetResult]
    ) -> list[DatasetResult]:
        ...


class NoopReranker(Reranker):
    def rerank(self, query, intent, results):
        return results


class LexicalReranker(Reranker):
    """Score each result by token overlap with the query and category fields.

    Rationale: NCBI scoring + the species filter already gets candidates into
    the door; the agent just has to nudge canonical hits into the top-10.
    Title matches weigh 3×, description matches 1×; intent-category matches
    add small bonuses. No external state, deterministic, ~10 µs per result.
    """

    TITLE_WEIGHT = 3.0
    DESCRIPTION_WEIGHT = 1.0
    INTENT_BONUS = 0.5

    def _score(
        self, query_tokens: set[str], intent: QueryIntent, r: DatasetResult
    ) -> float:
        title_tokens = _tokens(r.title)
        desc_tokens = _tokens(r.description or "")

        score = 0.0
        score += self.TITLE_WEIGHT * len(query_tokens & title_tokens)
        score += self.DESCRIPTION_WEIGHT * len(query_tokens & desc_tokens)

        # Bonus for hitting structured intent categories (each counts once).
        for group in (intent.disease, intent.tissue, intent.tech):
            for term in group:
                term_tokens = _tokens(term)
                if term_tokens and term_tokens.issubset(title_tokens | desc_tokens):
                    score += self.INTENT_BONUS

        # Tiebreaker: longer, more informative titles slightly preferred.
        score += min(len(title_tokens), 20) * 0.001
        return score

    def rerank(self, query, intent, results):
        if len(results) <= 1:
            return results
        q_tokens = _tokens(query)
        if not q_tokens:
            return results
        scored = [(self._score(q_tokens, intent, r), i, r) for i, r in enumerate(results)]
        # Stable: ties keep original adapter order via the index tiebreaker.
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [r for _, _, r in scored]


class IntentFeatureReranker(Reranker):
    """Structured-intent-aware feature scorer.

    Designed to beat ``A4 (no rerank)`` on v2 by promoting results that
    cover *more* of the intent simultaneously rather than results that
    simply contain many query tokens (the trap that the lexical reranker
    fell into). Each result earns a weighted sum over six features:

    1. **field-coverage** (`w_cov = 1.5`): number of intent fields
       (disease / tissue / tech) with at least one synonym hit in the
       title or description. Strongest signal — a result that mentions
       *both* disease and tissue is almost always more relevant than one
       that mentions only one.
    2. **co-occurrence** (`w_co = 1.0`): bonus when ≥2 fields are hit in
       the *same* title (specificity signal — the result is *about* the
       intersection, not coincidentally adjacent to it).
    3. **species match** (`w_species = 0.8`): +1 / 0 / −1 for
       match / unknown / mismatch when both intent.species and
       result.organism are set. Strong negative — a "human PFC" query
       does not want a mouse cortex result.
    4. **recency** (`w_recency = 0.5`): when ``intent.time_hint`` is set
       (``recent`` or year-bounded), parses the result's date field and
       gives 0 → 1 linearly within the requested window, 0 outside.
    5. **keyword overlap** (`w_kw = 0.3`): Jaccard-style overlap of
       query / intent.keywords tokens with title. Backstops the
       structured fields when the intent parser missed something.
    6. **mirror bonus** (`w_mirror = 0.2`): ``sqrt(mirrors_count)`` —
       cross-source duplicates are usually canonical datasets.

    All weights and thresholds are deliberately conservative. The
    reranker is stable: ties keep adapter order via an index tiebreaker.
    """

    W_COVERAGE = 2.0
    W_CO_OCCURRENCE = 1.0
    W_SPECIES = 0.6
    W_RECENCY = 0.5
    W_KEYWORD = 0.3
    W_MIRROR = 0.2

    # Words common in queries that carry no specificity — never count
    # toward keyword overlap because they appear in nearly every title.
    _STOP = frozenset(
        {
            "single", "cell", "cells", "rna", "seq", "sequencing", "dna",
            "data", "dataset", "datasets", "study", "studies", "atlas",
            "analysis", "the", "and", "of", "in", "for", "with", "from",
            "by", "to", "a", "an", "is", "show", "me", "find", "i", "want",
            "human", "mouse", "homo", "sapiens", "mus", "musculus",
        }
    )

    def _coverage(
        self,
        title: str,
        desc: str,
        intent: QueryIntent,
    ) -> tuple[int, bool, bool, bool]:
        """Return ``(n_fields_hit, disease_hit, tissue_hit, tech_hit)``.

        A field is considered "hit" if any of its synonyms (after
        synonym-map expansion) appears as a substring in either the
        title or description. We use substring rather than token-set so
        multi-word terms like ``"prefrontal cortex"`` are honoured.
        """
        text = f"{title} {desc}".lower()

        disease_hit = _any_phrase_in(_phrases(intent.disease), text)
        tissue_hit = _any_phrase_in(_phrases(intent.tissue), text)
        tech_hit = _any_phrase_in(_phrases(intent.tech), text)

        n = int(disease_hit) + int(tissue_hit) + int(tech_hit)
        return n, disease_hit, tissue_hit, tech_hit

    def _species_signal(self, intent: QueryIntent, r: DatasetResult) -> int:
        if not intent.species or not r.organism:
            return 0
        want = {s.lower() for s in intent.species}
        got = r.organism.lower()
        return 1 if any(w in got or got in w for w in want) else -1

    def _recency_signal(self, intent: QueryIntent, r: DatasetResult) -> float:
        if not intent.time_hint:
            return 0.0
        year = _parse_year(r.date)
        if year is None:
            return 0.0
        hint = intent.time_hint.strip().lower()
        now = _dt.datetime.now(_dt.timezone.utc).year
        if hint in {"recent", "latest", "new"}:
            # Linear: this year = 1.0, two years ago = 0.0
            return max(0.0, 1.0 - (now - year) / 2.0)
        # Year-range hints from the prompt grammar.
        m = re.match(r"^(\d{4})$", hint)
        if m:
            target = int(m.group(1))
            return 1.0 if year == target else max(0.0, 1.0 - abs(year - target) / 2.0)
        m = re.match(r"^(\d{4})\s*\+\s*$", hint)
        if m:
            lo = int(m.group(1))
            return 1.0 if year >= lo else 0.0
        m = re.match(r"^(\d{4})\s*[-–]\s*(\d{4})$", hint)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            return 1.0 if lo <= year <= hi else 0.0
        return 0.0

    def _keyword_overlap(self, query: str, intent: QueryIntent, title: str) -> float:
        """Jaccard-style overlap between (query + intent.keywords) and title.

        Returns 0..1. Stopwords are dropped so generic terms like
        ``"single cell"`` don't dominate. Hyphenated tokens are kept
        whole — ``"scrna-seq"`` is one token, not three.
        """
        bag = _tokens(query) | _tokens(" ".join(intent.keywords or []))
        bag -= self._STOP
        if not bag:
            return 0.0
        ttl = _tokens(title) - self._STOP
        if not ttl:
            return 0.0
        return len(bag & ttl) / len(bag | ttl)

    def _mirror_bonus(self, r: DatasetResult) -> float:
        n = len(r.mirrors or [])
        if n <= 0:
            return 0.0
        # sqrt growth so 1 mirror gives 1.0, 4 mirrors gives 2.0.
        return n ** 0.5

    def _score(self, query: str, intent: QueryIntent, r: DatasetResult) -> float:
        title = r.title or ""
        desc = r.description or ""

        n_fields, d_hit, t_hit, tech_hit = self._coverage(title, desc, intent)
        cov = self.W_COVERAGE * n_fields

        # Co-occurrence: ≥2 fields satisfied *in the title* (not just desc)
        # is a stronger signal because titles are curated. We check the
        # title separately for the co-occurrence bonus.
        title_l = title.lower()
        in_title = (
            int(_any_phrase_in(_phrases(intent.disease), title_l))
            + int(_any_phrase_in(_phrases(intent.tissue), title_l))
            + int(_any_phrase_in(_phrases(intent.tech), title_l))
        )
        co = self.W_CO_OCCURRENCE if in_title >= 2 else 0.0

        species = self.W_SPECIES * self._species_signal(intent, r)
        recency = self.W_RECENCY * self._recency_signal(intent, r)
        keyword = self.W_KEYWORD * self._keyword_overlap(query, intent, title)
        mirror = self.W_MIRROR * self._mirror_bonus(r)

        return cov + co + species + recency + keyword + mirror

    def rerank(self, query, intent, results):
        if len(results) <= 1:
            return results
        scored = [
            (self._score(query, intent, r), i, r) for i, r in enumerate(results)
        ]
        # Stable: ties keep original adapter order via the index tiebreaker.
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [r for _, _, r in scored]


class LLMReranker(Reranker):
    """Single-shot LLM re-ranker. Asks the LLM to return a permutation
    of candidate IDs ordered by relevance to the query.

    Falls back to ``LexicalReranker`` on any error so the response always
    succeeds.
    """

    MAX_CANDIDATES = 30

    def __init__(self) -> None:
        self.settings = get_settings()
        self._fallback = LexicalReranker()

    def rerank(self, query, intent, results):
        if len(results) <= 1:
            return results
        candidates = results[: self.MAX_CANDIDATES]

        if (
            not self.settings.anthropic_api_key
            and not self.settings.openai_api_key
        ):
            return self._fallback.rerank(query, intent, results)

        try:
            order = self._ask_llm(query, candidates)
        except Exception as exc:  # noqa: BLE001 — fail open
            log.warning("rerank_llm_failed", extra={"event": "rerank", "llm_error": str(exc)[:200]})
            return self._fallback.rerank(query, intent, results)

        # Apply the returned ordering, dropping unknown IDs and appending
        # any IDs the LLM omitted in their original order.
        by_id = {r.id: r for r in candidates}
        seen: set[str] = set()
        out: list[DatasetResult] = []
        for rid in order:
            r = by_id.get(rid)
            if r is not None and rid not in seen:
                out.append(r)
                seen.add(rid)
        for r in candidates:
            if r.id not in seen:
                out.append(r)
        # Keep any rows we truncated above MAX_CANDIDATES at the tail.
        out.extend(results[self.MAX_CANDIDATES :])
        return out

    def _ask_llm(self, query: str, candidates: list[DatasetResult]) -> list[str]:
        rows = [
            {
                "id": r.id,
                "title": r.title[:140],
                "organism": r.organism or "",
            }
            for r in candidates
        ]
        prompt = (
            "Re-rank these single-cell dataset candidates by relevance to the user's query.\n"
            "Return ONLY a JSON array of dataset IDs, most relevant first.\n\n"
            f"Query: {query}\n\nCandidates:\n{json.dumps(rows, ensure_ascii=False)}\n"
        )

        provider = self.settings.llm_provider
        model = self.settings.llm_model

        if provider == "anthropic" and self.settings.anthropic_api_key:
            text = self._call_anthropic(prompt, model)
        else:
            text = self._call_openai(prompt)

        # Be lenient: extract the first JSON array we can find.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("no JSON array in LLM response")
        order = json.loads(match.group(0))
        return [str(x) for x in order]

    def _call_anthropic(self, prompt: str, model: str) -> str:
        import anthropic

        from .intent_parser import _anthropic_first_text

        client_kwargs: dict = {
            "api_key": self.settings.anthropic_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = anthropic.Anthropic(**client_kwargs)
        with trace_llm_call("anthropic", model, "rerank") as stats:
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "input_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "output_tokens", 0) or 0
        return _anthropic_first_text(resp)

    def _call_openai(self, prompt: str) -> str:
        from openai import OpenAI

        client_kwargs: dict = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = OpenAI(**client_kwargs)
        # Use the configured model (was hard-coded to gpt-4o-mini, which the
        # Kimi/Moonshot key cannot reach). Thinking models (kimi-k2.*) require
        # temperature=1; the fast moonshot default is fine at the configured temp.
        model = self.settings.llm_model
        temperature = 1.0 if model.startswith("kimi-k2") else self.settings.llm_temperature
        with trace_llm_call("openai", model, "rerank") as stats:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=1024,
            )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        return resp.choices[0].message.content or ""


def get_reranker() -> Reranker:
    """Construct the configured reranker from settings.

    Backend strings: ``"intent_feature"`` (default, intent-aware feature scorer),
    ``"none"`` / ``"off"`` (no rerank), ``"lexical"`` (legacy, kept for the
    ablation only — known to regress MRR), ``"llm"`` (Kimi/Claude rerank).
    """
    s = get_settings()
    backend = (s.rerank_backend or "").lower()
    if backend == "llm":
        return LLMReranker()
    if backend in {"none", "off"}:
        return NoopReranker()
    if backend == "lexical":
        return LexicalReranker()
    return IntentFeatureReranker()
