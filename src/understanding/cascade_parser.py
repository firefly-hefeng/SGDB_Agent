"""GatedCascadeParser — the LLM-participation policy (Phase 40+).

The optimal place for the LLM in the closed loop is **selective**: the rule
parser is instant and already emits a calibrated ``confidence`` + ``complexity``;
on most queries it is as good as the LLM. So we run it first and **escalate to
the LLM only when a cheap signal predicts the LLM will change the answer for the
better** — sitting on the accuracy-vs-LLM-call-rate Pareto front (see
``docs/phases/PHASE40_LLM_PARTICIPATION.md`` and the calibration in
``tests/benchmark_v2/llm_participation/``).

This is NOT a binary rule/LLM mode switch: it is a per-query escalation policy.
On LLM failure it falls back to the rule parse (never worse than rule-only).

Gate (calibrated on the cr_target gold):
  • resolved-ID / direct-match parses (confidence ≥ HIGH_CONF) → trust rule, never escalate
  • confidence < CONF_THRESHOLD                                 → escalate
  • complexity == COMPLEX (and escalate_on_complex)             → escalate
  • else                                                        → trust rule
"""
from __future__ import annotations

import logging

from ..core.interfaces import IQueryParser
from ..core.models import ParsedQuery, QueryComplexity, SessionContext

logger = logging.getLogger(__name__)

# Calibrated knee from the offline Pareto analysis on the cr_target gold
# (kimi-k2.6, clean run): the structure-aware gate at conf<0.6 + structural
# triggers hits 92.4 cr_target @ 30% escalation — within 0.6 of the 93.0 oracle
# ceiling, vs always-rule 86.1 and always-LLM 70.7. Confidence-only gates HURT
# (they escalate the conf=0.65 single-entity cohort, which the LLM degrades);
# 0.6 escalates only sub-base-confidence (≤0.5, e.g. 0-entity) parses and lets
# the structural flags carry the rest. Override at construction to re-tune.
DEFAULT_CONF_THRESHOLD = 0.6
HIGH_CONF = 0.95  # resolved IDs / unambiguous match — rule is authoritative


class GatedCascadeParser(IQueryParser):
    """Run the rule parser first; escalate to the LLM parser only when the
    calibrated gate fires. Tracks escalation stats for evaluation."""

    def __init__(
        self,
        rule_parser: IQueryParser,
        llm_parser: IQueryParser,
        *,
        conf_threshold: float = DEFAULT_CONF_THRESHOLD,
        escalate_on_complex: bool = True,
        high_conf: float = HIGH_CONF,
    ) -> None:
        self.rule_parser = rule_parser
        self.llm_parser = llm_parser
        self.conf_threshold = conf_threshold
        self.escalate_on_complex = escalate_on_complex
        self.high_conf = high_conf
        # live telemetry (also surfaced so the portal/eval can report the rate)
        self.n_total = 0
        self.n_escalated = 0
        self.last_escalated = False
        self.last_reason = ""

    @property
    def escalation_rate(self) -> float:
        return self.n_escalated / self.n_total if self.n_total else 0.0

    @staticmethod
    def _has_negation(pq: ParsedQuery) -> bool:
        f = getattr(pq, "filters", None)
        if not f:
            return False
        return any(getattr(f, a, None) for a in (
            "exclude_tissues", "exclude_diseases", "exclude_organisms",
            "exclude_source_databases", "exclude_sample_types",
            "exclude_disease_categories", "exclude_assays", "exclude_cell_types"))

    def _decide(self, pq: ParsedQuery) -> tuple[bool, str]:
        conf = float(getattr(pq, "confidence", 1.0) or 0.0)
        cx = getattr(pq, "complexity", QueryComplexity.SIMPLE)
        # Structure-aware triggers: LLM-favorable classes the rule parser
        # self-detects. These escalate REGARDLESS of confidence — the eval
        # showed the rule arm under-serves them even when it parses confidently
        # (e.g. a high-confidence negation / strict-mode / aggregation query).
        if getattr(pq, "strict_mode", False):
            return True, "strict-mode"
        if getattr(pq, "aggregation", None) is not None:
            return True, "aggregation"
        if self._has_negation(pq):
            return True, "negation"
        if self.escalate_on_complex and cx == QueryComplexity.COMPLEX:
            return True, "complex-query"
        # Otherwise gate on the rule parser's calibrated confidence.
        if conf >= self.high_conf:
            return False, f"rule-authoritative (conf={conf:.2f}≥{self.high_conf})"
        if conf < self.conf_threshold:
            return True, f"low-confidence (conf={conf:.2f}<{self.conf_threshold})"
        return False, f"rule-sufficient (conf={conf:.2f})"

    async def parse(
        self, query: str, context: SessionContext | None = None,
    ) -> ParsedQuery:
        self.n_total += 1
        rule_pq = await self.rule_parser.parse(query, context)
        escalate, reason = self._decide(rule_pq)
        self.last_escalated = escalate
        self.last_reason = reason

        if not escalate:
            rule_pq.parse_method = "cascade:rule"
            return rule_pq

        self.n_escalated += 1
        try:
            llm_pq = await self.llm_parser.parse(query, context)
            llm_pq.parse_method = "cascade:llm"
            return llm_pq
        except Exception as e:  # noqa: BLE001 — never worse than rule-only
            logger.warning("cascade: LLM escalation failed (%s) → rule fallback", e)
            rule_pq.parse_method = "cascade:rule-fallback"
            return rule_pq

    async def escalate_for_recovery(
        self, query: str, context: SessionContext | None = None,
    ) -> ParsedQuery | None:
        """RESULT-gate: the parse-gate kept this query on the rule arm, but its
        SQL returned 0 rows — give the LLM arm a second chance (re-parse). This
        is the result-driven half of the LLM-participation policy: escalate not
        just on a hard-looking *parse*, but on a suspicious *result* (an honest-
        zero), which is where real (messy) queries most often need the LLM.
        Returns the LLM ParsedQuery, or None if the LLM arm is unavailable/fails.
        """
        try:
            self.n_escalated += 1
            self.last_escalated = True
            self.last_reason = "zero-result-recovery"
            llm_pq = await self.llm_parser.parse(query, context)
            llm_pq.parse_method = "cascade:llm-recover"
            return llm_pq
        except Exception as e:  # noqa: BLE001
            logger.warning("cascade: zero-result LLM recovery failed: %s", e)
            return None
