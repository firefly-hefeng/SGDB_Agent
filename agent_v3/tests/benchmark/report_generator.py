"""
Report generator for benchmark evaluation results.

Produces a publication-quality markdown report.
"""

from __future__ import annotations

from datetime import datetime

from tests.benchmark.metrics import OverallMetrics, CategoryMetrics


def generate_report(
    overall: OverallMetrics,
    categories: dict[str, CategoryMetrics],
    total_time: float,
) -> str:
    """Generate a comprehensive markdown evaluation report."""
    lines = []

    lines.append("# SCeQTL-Agent V2 — Benchmark Evaluation Report")
    lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Total evaluation time: {total_time:.1f}s")
    lines.append("")

    # ── Executive Summary ──
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Questions | {overall.total_questions} |")
    lines.append(f"| **Pass Rate** | **{overall.pass_rate:.1f}%** ({overall.total_passed}/{overall.total_questions}) |")
    lines.append(f"| Failed | {overall.total_failed} |")
    lines.append(f"| Errors | {overall.total_errors} |")
    lines.append(f"| Avg Response Time | {overall.avg_response_time_ms:.0f}ms |")
    lines.append(f"| P95 Response Time | {overall.p95_response_time_ms:.0f}ms |")
    lines.append(f"| Rule Resolution Rate | {overall.rule_resolution_rate:.1f}% |")
    lines.append(f"| Chinese Query Pass Rate | {overall.chinese_pass_rate:.1f}% |")
    lines.append(f"| English Query Pass Rate | {overall.english_pass_rate:.1f}% |")
    lines.append("")

    # ── 4 Dimensions ──
    lines.append("## Evaluation Dimensions")
    lines.append("")

    # Dim 1: Accuracy
    lines.append("### Dimension 1: Query Accuracy")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Count Accuracy (results >= expected) | {overall.count_accuracy:.1f}% |")
    lines.append(f"| Intent Recognition Accuracy | {overall.intent_accuracy:.1f}% |")
    lines.append(f"| Zero-Result Rate | {overall.zero_result_rate:.1f}% |")
    lines.append("")

    # Dim 2: Fusion
    lines.append("### Dimension 2: Cross-DB Fusion Quality")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Multi-Source Coverage | {overall.multi_source_coverage:.1f}% |")
    lines.append(f"| Avg Sources per Query | {overall.avg_sources_per_query:.2f} |")
    lines.append(f"| Avg Dedup Rate | {overall.avg_dedup_rate:.1f}% |")
    lines.append("")

    # Dim 3: UX
    lines.append("### Dimension 3: User Experience")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Avg Response Time | {overall.avg_response_time_ms:.0f}ms |")
    lines.append(f"| P95 Response Time | {overall.p95_response_time_ms:.0f}ms |")
    lines.append(f"| Suggestion Generation Rate | {overall.suggestion_generation_rate:.1f}% |")
    lines.append("")

    # Dim 4: Cost
    lines.append("### Dimension 4: Cost Efficiency")
    lines.append("")
    lines.append(f"| Method | Rate |")
    lines.append(f"|--------|------|")
    lines.append(f"| Rule-based | {overall.rule_resolution_rate:.1f}% |")
    lines.append(f"| Template-based | {overall.template_resolution_rate:.1f}% |")
    lines.append(f"| LLM-based | {overall.llm_resolution_rate:.1f}% |")
    lines.append(f"| Error Rate | {overall.error_rate:.1f}% |")
    lines.append("")

    # ── Per-Category Breakdown ──
    lines.append("## Per-Category Results")
    lines.append("")

    lines.append("| Category | Total | Passed | Failed | Errors | Pass Rate | Avg Time | P95 Time | Rule % |")
    lines.append("|----------|-------|--------|--------|--------|-----------|----------|----------|--------|")
    for cat_name, cm in categories.items():
        pass_rate = (cm.passed / cm.total_questions * 100) if cm.total_questions > 0 else 0
        lines.append(
            f"| {cat_name} | {cm.total_questions} | {cm.passed} | {cm.failed} | {cm.errors} | "
            f"{pass_rate:.0f}% | {cm.avg_time_ms:.0f}ms | {cm.p95_time_ms:.0f}ms | {cm.rule_pct:.0f}% |"
        )
    lines.append("")

    # ── Category Details ──
    for cat_name, cm in categories.items():
        lines.append(f"### {cat_name}")
        lines.append("")
        lines.append(f"- **Questions**: {cm.total_questions}")
        lines.append(f"- **Pass rate**: {cm.passed}/{cm.total_questions}")
        lines.append(f"- **Count accuracy**: {cm.count_pass_rate:.1f}%")
        lines.append(f"- **Intent accuracy**: {cm.intent_accuracy:.1f}%")
        if cm.ontology_trigger_rate > 0:
            lines.append(f"- **Ontology trigger rate**: {cm.ontology_trigger_rate:.1f}%")
        if cm.multi_source_pct > 0:
            lines.append(f"- **Multi-source rate**: {cm.multi_source_pct:.1f}%")
        lines.append(f"- **Performance**: avg={cm.avg_time_ms:.0f}ms, p50={cm.p50_time_ms:.0f}ms, p95={cm.p95_time_ms:.0f}ms")
        lines.append(f"- **Methods**: rule={cm.rule_pct:.0f}%, template={cm.template_pct:.0f}%")

        if cm.failures:
            lines.append("")
            lines.append("**Failures:**")
            for f in cm.failures[:10]:
                detail = f.get("error") or f.get("issues", "unknown")
                lines.append(f"- `{f['id']}`: {detail}")

        lines.append("")

    # ── System Configuration ──
    lines.append("## System Configuration")
    lines.append("")
    lines.append("- **Database**: unified_metadata.db (756,579 samples, 23,123 projects)")
    lines.append("- **Data Sources**: 12 databases (GEO, NCBI, EBI, CellXGene, HTAN, HCA, PsychAD, ...)")
    lines.append("- **Ontology**: UBERON + MONDO + CL + EFO (113K terms)")
    lines.append("- **Memory**: 3-layer (Working + Episodic + Semantic)")
    lines.append("- **LLM**: None (pure rule-based evaluation)")
    lines.append("- **SQL Method**: 3-candidate (template + rule + LLM) with parallel execution")
    lines.append("")

    return "\n".join(lines)
