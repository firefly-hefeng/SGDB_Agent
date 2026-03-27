"""
Evaluation metrics for SCeQTL-Agent V2

Computes 4-dimension metrics:
1. Query Accuracy — intent correctness, result count, field coverage
2. Cross-DB Fusion — multi-source coverage, dedup effectiveness
3. User Experience — response time, suggestion quality, zero-result rate
4. Cost Efficiency — SQL method distribution, LLM usage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionResult:
    """Result of evaluating a single benchmark question."""
    question_id: str
    query: str
    category: str

    # Response data
    total_count: int = 0
    displayed_count: int = 0
    execution_time_ms: float = 0.0
    sql_method: str = ""
    data_sources: list[str] = field(default_factory=list)
    intent_parsed: str = ""
    ontology_expansions: list[dict] = field(default_factory=list)
    suggestions_count: int = 0
    charts_count: int = 0
    error: str | None = None
    fusion_stats: dict = field(default_factory=dict)

    # Evaluation flags
    count_pass: bool = False
    intent_pass: bool = False
    ontology_pass: bool = False
    multi_source_pass: bool = False
    no_error: bool = True


@dataclass
class CategoryMetrics:
    """Aggregated metrics for a benchmark category."""
    category: str
    total_questions: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0

    # Accuracy
    count_pass_rate: float = 0.0
    intent_accuracy: float = 0.0
    ontology_trigger_rate: float = 0.0

    # Performance
    avg_time_ms: float = 0.0
    p50_time_ms: float = 0.0
    p95_time_ms: float = 0.0
    max_time_ms: float = 0.0

    # Method distribution
    rule_pct: float = 0.0
    template_pct: float = 0.0
    llm_pct: float = 0.0

    # Fusion
    avg_source_count: float = 0.0
    multi_source_pct: float = 0.0
    avg_dedup_rate: float = 0.0

    # Details
    failures: list[dict] = field(default_factory=list)


@dataclass
class OverallMetrics:
    """Overall evaluation metrics across all categories."""
    total_questions: int = 0
    total_passed: int = 0
    total_failed: int = 0
    total_errors: int = 0
    pass_rate: float = 0.0

    # Dimension 1: Query Accuracy
    count_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    zero_result_appropriate: float = 0.0

    # Dimension 2: Cross-DB Fusion
    multi_source_coverage: float = 0.0
    avg_dedup_rate: float = 0.0
    avg_sources_per_query: float = 0.0

    # Dimension 3: User Experience
    avg_response_time_ms: float = 0.0
    p95_response_time_ms: float = 0.0
    suggestion_generation_rate: float = 0.0
    zero_result_rate: float = 0.0

    # Dimension 4: Cost Efficiency
    rule_resolution_rate: float = 0.0
    template_resolution_rate: float = 0.0
    llm_resolution_rate: float = 0.0
    error_rate: float = 0.0

    # Language support
    chinese_pass_rate: float = 0.0
    english_pass_rate: float = 0.0

    # Per-category breakdown
    categories: dict[str, CategoryMetrics] = field(default_factory=dict)


def evaluate_question(
    question: dict,
    response: dict | None,
    category: str,
) -> QuestionResult:
    """Evaluate a single question against its expected results."""
    qid = question["id"]
    query = question["query"]

    result = QuestionResult(question_id=qid, query=query, category=category)

    if response is None:
        result.error = "No response"
        result.no_error = False
        return result

    if response.get("error"):
        result.error = response["error"]
        result.no_error = False

    result.total_count = response.get("total_count", 0)
    result.displayed_count = response.get("displayed_count", 0)
    result.execution_time_ms = response.get("provenance", {}).get("execution_time_ms", 0)
    result.sql_method = response.get("provenance", {}).get("sql_method", "")
    result.data_sources = response.get("provenance", {}).get("data_sources", [])
    result.intent_parsed = response.get("provenance", {}).get("parsed_intent", "")
    result.ontology_expansions = response.get("provenance", {}).get("ontology_expansions", [])
    result.suggestions_count = len(response.get("suggestions", []))
    result.charts_count = len(response.get("charts", []))
    result.fusion_stats = response.get("provenance", {}).get("fusion_stats", {})

    # Check count — if total_count equals the default limit (20), treat as "at least 20"
    # because the agent uses LIMIT and doesn't do a separate COUNT(*)
    expected_min = question.get("expected_count_min", 0)
    if result.total_count >= expected_min:
        result.count_pass = True
    elif result.total_count == 20 and expected_min > 20:
        # Agent hit the LIMIT, likely has more results than shown
        result.count_pass = True
    else:
        result.count_pass = False

    # Check intent
    expected_intent = question.get("expected_intent")
    if expected_intent:
        result.intent_pass = result.intent_parsed == expected_intent
    else:
        result.intent_pass = True  # No expectation

    # Check ontology
    if question.get("expected_expansion"):
        result.ontology_pass = len(result.ontology_expansions) > 0
    else:
        result.ontology_pass = True

    # Check multi-source
    if question.get("check_multi_source") or question.get("expected_multi_source"):
        result.multi_source_pass = len(result.data_sources) > 1
    else:
        result.multi_source_pass = True

    return result


def compute_category_metrics(
    results: list[QuestionResult],
    category: str,
) -> CategoryMetrics:
    """Compute aggregated metrics for a category."""
    m = CategoryMetrics(category=category, total_questions=len(results))

    if not results:
        return m

    times = [r.execution_time_ms for r in results if r.execution_time_ms > 0]
    methods = [r.sql_method for r in results if r.sql_method]

    # Pass/fail
    for r in results:
        passed = r.count_pass and r.intent_pass and r.ontology_pass and r.no_error
        if passed:
            m.passed += 1
        elif r.error:
            m.errors += 1
            m.failures.append({"id": r.question_id, "error": r.error})
        else:
            m.failed += 1
            issues = []
            if not r.count_pass:
                issues.append(f"count={r.total_count}")
            if not r.intent_pass:
                issues.append(f"intent={r.intent_parsed}")
            if not r.ontology_pass:
                issues.append("no ontology")
            m.failures.append({"id": r.question_id, "issues": ", ".join(issues)})

    n = len(results)
    m.count_pass_rate = sum(1 for r in results if r.count_pass) / n * 100
    m.intent_accuracy = sum(1 for r in results if r.intent_pass) / n * 100
    m.ontology_trigger_rate = sum(1 for r in results if r.ontology_expansions) / n * 100

    # Performance
    if times:
        times_sorted = sorted(times)
        m.avg_time_ms = sum(times) / len(times)
        m.p50_time_ms = times_sorted[len(times_sorted) // 2]
        m.p95_time_ms = times_sorted[int(len(times_sorted) * 0.95)]
        m.max_time_ms = times_sorted[-1]

    # Method distribution
    if methods:
        m.rule_pct = sum(1 for m_ in methods if m_ == "rule") / len(methods) * 100
        m.template_pct = sum(1 for m_ in methods if m_ == "template") / len(methods) * 100
        m.llm_pct = sum(1 for m_ in methods if m_ == "llm") / len(methods) * 100

    # Fusion
    source_counts = [len(r.data_sources) for r in results if r.data_sources]
    if source_counts:
        m.avg_source_count = sum(source_counts) / len(source_counts)
        m.multi_source_pct = sum(1 for c in source_counts if c > 1) / len(source_counts) * 100

    dedup_rates = [
        r.fusion_stats.get("dedup_rate", 0)
        for r in results
        if r.fusion_stats.get("raw_count", 0) > 0
    ]
    if dedup_rates:
        m.avg_dedup_rate = sum(dedup_rates) / len(dedup_rates)

    return m


def compute_overall_metrics(
    all_results: list[QuestionResult],
    category_metrics: dict[str, CategoryMetrics],
) -> OverallMetrics:
    """Compute overall evaluation metrics."""
    m = OverallMetrics()
    m.total_questions = len(all_results)
    m.categories = category_metrics

    if not all_results:
        return m

    for r in all_results:
        passed = r.count_pass and r.intent_pass and r.ontology_pass and r.no_error
        if passed:
            m.total_passed += 1
        elif r.error:
            m.total_errors += 1
        else:
            m.total_failed += 1

    n = len(all_results)
    m.pass_rate = m.total_passed / n * 100

    # Dim 1: Accuracy
    m.count_accuracy = sum(1 for r in all_results if r.count_pass) / n * 100
    m.intent_accuracy = sum(1 for r in all_results if r.intent_pass) / n * 100

    # Dim 2: Fusion
    with_sources = [r for r in all_results if r.data_sources]
    if with_sources:
        m.avg_sources_per_query = sum(len(r.data_sources) for r in with_sources) / len(with_sources)
        m.multi_source_coverage = sum(1 for r in with_sources if len(r.data_sources) > 1) / len(with_sources) * 100

    dedup_rates = [r.fusion_stats.get("dedup_rate", 0) for r in all_results if r.fusion_stats.get("raw_count", 0) > 0]
    if dedup_rates:
        m.avg_dedup_rate = sum(dedup_rates) / len(dedup_rates)

    # Dim 3: UX
    times = [r.execution_time_ms for r in all_results if r.execution_time_ms > 0]
    if times:
        m.avg_response_time_ms = sum(times) / len(times)
        m.p95_response_time_ms = sorted(times)[int(len(times) * 0.95)]

    m.suggestion_generation_rate = sum(1 for r in all_results if r.suggestions_count > 0) / n * 100
    m.zero_result_rate = sum(1 for r in all_results if r.total_count == 0) / n * 100

    # Dim 4: Cost
    methods = [r.sql_method for r in all_results if r.sql_method]
    if methods:
        m.rule_resolution_rate = sum(1 for m_ in methods if m_ == "rule") / len(methods) * 100
        m.template_resolution_rate = sum(1 for m_ in methods if m_ == "template") / len(methods) * 100
        m.llm_resolution_rate = sum(1 for m_ in methods if m_ == "llm") / len(methods) * 100

    m.error_rate = m.total_errors / n * 100

    # Language
    zh_results = [r for r in all_results if any(ord(c) > 0x4e00 for c in r.query)]
    en_results = [r for r in all_results if not any(ord(c) > 0x4e00 for c in r.query)]
    if zh_results:
        m.chinese_pass_rate = sum(1 for r in zh_results if r.count_pass and r.no_error) / len(zh_results) * 100
    if en_results:
        m.english_pass_rate = sum(1 for r in en_results if r.count_pass and r.no_error) / len(en_results) * 100

    return m
