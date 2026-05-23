"""
Reasoning trace primitives — Phase 14.

Captures the agent's step-by-step decision making so that:
- the frontend can visualise it (timeline + rationale + alternatives),
- evaluators can score reasoning quality (completeness, calibration,
  correction validity),
- failure modes can be diagnosed without re-running the query.

Design:
- Single ReasoningTrace per query (one trace per AgentResponse).
- Each step is one logical decision (parse intent, resolve ontology,
  generate SQL, execute, fuse, synthesize, *or* a correction step).
- Steps form a flat list with optional `correction_of` pointers — that
  keeps JSON small and lets the UI render either as timeline or DAG.

Steps must be JSON-serialisable so they can travel through HTTP/WebSocket
and be persisted in episodic memory.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


STAGES = (
    "parse",          # NL → ParsedQuery
    "reason",         # CoT step inside the parser
    "ontology",       # entity → ontology terms + db_values
    "schema",         # SchemaKnowledgeTree retrieval
    "sql_gen",        # ParsedQuery → SQL candidates
    "validate",       # syntax / safety check
    "execute",        # SQL → rows
    "correct",        # self-correction (replaces a previous step)
    "fuse",           # cross-DB dedup + interleave
    "synthesize",     # answer text + suggestions
)


@dataclass
class ReasoningStep:
    """One observable decision in the agent pipeline."""

    stage: str
    title: str
    status: str = "ok"               # ok | warn | error | corrected | skipped
    started_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    rationale: str = ""              # CoT thought / rule explanation
    alternatives: list[dict] = field(default_factory=list)
    confidence: float = 1.0
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    correction_of: str | None = None  # step_id this step replaces / amends

    def end(self) -> None:
        """Convenience: stamp duration_ms from started_at."""
        self.duration_ms = (time.time() - self.started_at) * 1000

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReasoningTrace:
    """All steps for one user query."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    steps: list[ReasoningStep] = field(default_factory=list)
    final_confidence: float = 1.0

    # ─── lifecycle ───
    def add(self, step: ReasoningStep) -> ReasoningStep:
        self.steps.append(step)
        return step

    def start(self, stage: str, title: str, **kwargs: Any) -> ReasoningStep:
        """Open a step; caller closes it via step.end() + step.output=...."""
        step = ReasoningStep(stage=stage, title=title, **kwargs)
        self.steps.append(step)
        return step

    def correction(
        self, replaces: str, title: str, rationale: str = "",
        new_output: dict | None = None,
    ) -> ReasoningStep:
        """Record a self-correction that supersedes a previous step."""
        for s in self.steps:
            if s.step_id == replaces:
                s.status = "corrected"
                break
        return self.add(
            ReasoningStep(
                stage="correct",
                title=title,
                status="ok",
                rationale=rationale,
                output=new_output or {},
                correction_of=replaces,
            )
        )

    # ─── derived ───
    @property
    def correction_count(self) -> int:
        return sum(1 for s in self.steps if s.stage == "correct")

    @property
    def fallback_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "warn")

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.steps if s.status == "error")

    @property
    def total_duration_ms(self) -> float:
        return sum(s.duration_ms for s in self.steps)

    def stages_completed(self) -> set[str]:
        return {s.stage for s in self.steps if s.status in ("ok", "corrected")}

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "steps": [s.to_dict() for s in self.steps],
            "summary": {
                "step_count": len(self.steps),
                "correction_count": self.correction_count,
                "fallback_count": self.fallback_count,
                "error_count": self.error_count,
                "total_duration_ms": round(self.total_duration_ms, 1),
                "stages_completed": sorted(self.stages_completed()),
                "final_confidence": self.final_confidence,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def empty_trace() -> ReasoningTrace:
    return ReasoningTrace()
