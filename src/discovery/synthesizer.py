"""Result synthesizer: generates human-readable summary from discovery results."""

import json
import re
from pathlib import Path

from src.discovery.config import get_settings
from src.discovery.intent_parser import _anthropic_first_text
from src.discovery.llm_tracing import trace_llm_call
from src.discovery.models import DiscoveryResponse, DiscoveryResult, QueryIntent


_YEAR_RE = re.compile(r"(19|20)\d{2}")


def _parse_year_hint(hint: str | None) -> tuple[int, int] | None:
    """Return ``(lo, hi)`` for strict-year hints, else ``None``.

    Mirrors ``DiscoveryRouter._apply_year_filter`` but returned as a tuple
    so we can pre-compute per-source year-match counts for the synthesizer.
    """
    h = (hint or "").strip().lower()
    if not h:
        return None
    m_single = re.match(r"^(\d{4})$", h)
    if m_single:
        y = int(m_single.group(1))
        return (y, y)
    m_range = re.match(r"^(\d{4})\s*-\s*(\d{4})$", h)
    if m_range:
        return (int(m_range.group(1)), int(m_range.group(2)))
    m_plus = re.match(r"^(\d{4})\s*\+$", h)
    if m_plus:
        return (int(m_plus.group(1)), 9999)
    return None


def _build_constraint_check(
    intent: QueryIntent, src: DiscoveryResult
) -> dict | None:
    """Pre-compute year/species match counts for the synthesizer.

    Closes the rs-016 hallucination mode: Kimi mis-applied the
    "no year match" rule even when every retrieved row was in-year. By
    handing the LLM an unambiguous ``in_year_count`` / ``out_of_year_count``
    pair we make the constraint check mechanical instead of inferential.
    """
    if not src.results or src.error:
        return None

    out: dict = {}
    year_range = _parse_year_hint(intent.time_hint)
    if year_range is not None:
        lo, hi = year_range
        in_year = 0
        out_year = 0
        unknown = 0
        for r in src.results:
            if not r.date:
                unknown += 1
                continue
            m = _YEAR_RE.search(str(r.date))
            if not m:
                unknown += 1
                continue
            y = int(m.group(0))
            if lo <= y <= hi:
                in_year += 1
            else:
                out_year += 1
        out["requested_year"] = (
            f"{lo}" if lo == hi else f"{lo}-{hi if hi != 9999 else 'present'}"
        )
        out["in_year_count"] = in_year
        out["out_of_year_count"] = out_year
        out["unknown_year_count"] = unknown

    if intent.species and intent.species != ["Homo sapiens"]:
        wanted = {s.lower() for s in intent.species}
        match = 0
        mismatch = 0
        unknown_org = 0
        for r in src.results:
            org = (r.organism or "").lower()
            if not org:
                unknown_org += 1
                continue
            if any(w in org or org in w for w in wanted):
                match += 1
            else:
                mismatch += 1
        out["requested_species"] = list(intent.species)
        out["species_match_count"] = match
        out["species_mismatch_count"] = mismatch
        out["unknown_species_count"] = unknown_org

    return out or None


class Synthesizer:
    """Synthesizes discovery results into a markdown summary."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "synthesizer_v1.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        # Fallback default prompt
        return (
            "You are a data discovery assistant. Summarize the following search results for the user.\n\n"
            "User query: {query}\n"
            "Results by database:\n{results_json}\n\n"
            "Instructions:\n"
            "1. Write a brief 1-2 sentence summary of what was found.\n"
            "2. For each database, list up to 5 most relevant results with direct links.\n"
            "3. Do NOT analyze the data content. Just describe what datasets are available and where to find them.\n"
            "4. If a database returned no results, mention it briefly.\n"
            "5. Format with Markdown.\n"
            "6. Write in the same language as the user's query."
        )

    def synthesize(self, response: DiscoveryResponse) -> str:
        """Generate a markdown summary from discovery results.

        Args:
            response: DiscoveryResponse containing all results.

        Returns:
            Markdown formatted summary string.
        """
        # If no LLM available, generate simple markdown programmatically
        if not self.settings.anthropic_api_key and not self.settings.openai_api_key:
            return self._fallback_synthesize(response)

        try:
            return self._llm_synthesize(response)
        except Exception:
            return self._fallback_synthesize(response)

    def _llm_synthesize(self, response: DiscoveryResponse) -> str:
        """Use LLM to synthesize results."""
        if self.settings.llm_provider == "anthropic" and self.settings.anthropic_api_key:
            return self._synthesize_with_anthropic(response)
        elif self.settings.llm_provider == "openai" and self.settings.openai_api_key:
            return self._synthesize_with_openai(response)
        return self._fallback_synthesize(response)

    def _synthesize_with_anthropic(self, response: DiscoveryResponse) -> str:
        import anthropic

        client_kwargs = {
            "api_key": self.settings.anthropic_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = anthropic.Anthropic(**client_kwargs)

        # Build compact results JSON for LLM context
        results_summary = []
        for src in response.sources:
            if src.error:
                results_summary.append(
                    {
                        "source": src.source,
                        "total": src.total_found,
                        "error": src.error,
                    }
                )
            else:
                block: dict = {
                    "source": src.source,
                    "total": src.total_found,
                    "top_results": [
                        {
                            "id": r.id,
                            "title": r.title,
                            "organism": r.organism,
                            "samples": r.sample_count,
                            # ``date`` is required for the synthesizer's
                            # strict-year + recency rules — without it the
                            # LLM cannot verify whether any returned hit
                            # is in the user's requested year (rs-016
                            # failure mode).
                            "date": r.date,
                            "url": r.source_url,
                        }
                        for r in src.results[:8]
                    ],
                }
                # Pre-computed constraint-check counts close the
                # rs-016 hallucination mode where Kimi mis-applied
                # the "no year match" rule even when every retrieved
                # row was in-year. Mechanical counts replace LLM date
                # parsing.
                check = _build_constraint_check(response.intent, src)
                if check:
                    block["constraint_check"] = check
                results_summary.append(block)

        prompt = self._prompt.format(
            query=response.query,
            results_json=json.dumps(results_summary, indent=2, ensure_ascii=False),
        )

        with trace_llm_call(
            "anthropic", self.settings.llm_model, "synthesize"
        ) as stats:
            resp = client.messages.create(
                model=self.settings.llm_model,
                max_tokens=2048,
                # T=0 for run-to-run reproducibility. Round-7-vs-round-8
                # variance on rs-016 (5 → 1, no code change) showed the
                # strict-year rule fired inconsistently at T=0.3. The
                # synthesis text is still rich enough at T=0 because the
                # prompt is highly structured.
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "input_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "output_tokens", 0) or 0
        return _anthropic_first_text(resp) or self._fallback_synthesize(response)

    def _synthesize_with_openai(self, response: DiscoveryResponse) -> str:
        from openai import OpenAI

        client_kwargs = {
            "api_key": self.settings.openai_api_key,
            "timeout": self.settings.llm_timeout,
        }
        if self.settings.llm_base_url:
            client_kwargs["base_url"] = self.settings.llm_base_url
        client = OpenAI(**client_kwargs)

        results_summary = []
        for src in response.sources:
            if src.error:
                results_summary.append(
                    {
                        "source": src.source,
                        "total": src.total_found,
                        "error": src.error,
                    }
                )
            else:
                block: dict = {
                    "source": src.source,
                    "total": src.total_found,
                    "top_results": [
                        {
                            "id": r.id,
                            "title": r.title,
                            "organism": r.organism,
                            "samples": r.sample_count,
                            # ``date`` is required for the synthesizer's
                            # strict-year + recency rules — without it the
                            # LLM cannot verify whether any returned hit
                            # is in the user's requested year (rs-016
                            # failure mode).
                            "date": r.date,
                            "url": r.source_url,
                        }
                        for r in src.results[:8]
                    ],
                }
                # Pre-computed constraint-check counts close the
                # rs-016 hallucination mode where Kimi mis-applied
                # the "no year match" rule even when every retrieved
                # row was in-year. Mechanical counts replace LLM date
                # parsing.
                check = _build_constraint_check(response.intent, src)
                if check:
                    block["constraint_check"] = check
                results_summary.append(block)

        prompt = self._prompt.format(
            query=response.query,
            results_json=json.dumps(results_summary, indent=2, ensure_ascii=False),
        )

        model = self.settings.llm_model
        with trace_llm_call("openai", model, "synthesize") as stats:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                # T=0 for determinism — see comment in
                # ``_synthesize_with_anthropic``.
                temperature=0.0,
                max_tokens=2048,
            )
            usage = getattr(resp, "usage", None)
            if usage is not None:
                stats.prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                stats.completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        return resp.choices[0].message.content or self._fallback_synthesize(response)

    def _fallback_synthesize(self, response: DiscoveryResponse) -> str:
        """Generate simple markdown summary without LLM."""
        lines = [
            "## 🔍 Data Discovery Results",
            "",
            f"> Query: **{response.query}**",
            "",
            f"Found **{response.total_found}** potential matches across {len(response.sources)} database(s).",
            "",
        ]

        for src in response.sources:
            lines.append(f"### 📊 {src.source.upper()} ({src.total_found} found)")
            if src.error:
                lines.append(f"_Error: {src.error}_")
            elif not src.results:
                lines.append("_No results found._")
            else:
                lines.append("| ID | Title | Organism | Samples | Link |")
                lines.append("|----|-------|----------|---------|------|")
                for r in src.results[:8]:
                    organism = r.organism or "—"
                    samples = r.sample_count if r.sample_count is not None else "—"
                    lines.append(
                        f"| {r.id} | {r.title[:60]}{'...' if len(r.title) > 60 else ''} | {organism} | {samples} | [View]({r.source_url}) |"
                    )
            lines.append("")

        lines.append("---")
        lines.append(f"_Total latency: {response.total_latency_ms}ms_")
        return "\n".join(lines)
