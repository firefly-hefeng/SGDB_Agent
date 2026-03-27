#!/usr/bin/env python3
"""
SCeQTL-Agent V2 — Benchmark Evaluation Pipeline

Runs 150 benchmark questions against the agent and generates a comprehensive report.

Usage:
    python run_benchmark.py [--categories simple_search,ontology_expansion] [--output results/]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.dal.database import DatabaseAbstractionLayer
from src.agent.coordinator import CoordinatorAgent
from tests.benchmark.metrics import (
    QuestionResult,
    evaluate_question,
    compute_category_metrics,
    compute_overall_metrics,
)
from tests.benchmark.report_generator import generate_report

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def load_benchmark(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


async def run_single_query(
    agent: CoordinatorAgent,
    query: str,
    session_id: str = "default",
) -> dict | None:
    """Run a single query and return serialized response."""
    try:
        resp = await agent.query(query, session_id=session_id)
        return {
            "summary": resp.summary,
            "total_count": resp.total_count,
            "displayed_count": resp.displayed_count,
            "provenance": {
                "original_query": resp.provenance.original_query,
                "parsed_intent": resp.provenance.parsed_intent,
                "sql_executed": resp.provenance.sql_executed,
                "sql_method": resp.provenance.sql_method,
                "execution_time_ms": resp.provenance.execution_time_ms,
                "data_sources": resp.provenance.data_sources,
                "ontology_expansions": resp.provenance.ontology_expansions,
                "fusion_stats": resp.provenance.fusion_stats,
            },
            "suggestions": [
                {"type": s.type, "text": s.text} for s in resp.suggestions
            ],
            "charts": [{"type": c.type, "title": c.title} for c in resp.charts],
            "error": resp.error,
        }
    except Exception as e:
        return {"error": str(e), "total_count": 0, "displayed_count": 0,
                "provenance": {}, "suggestions": [], "charts": []}


async def run_benchmark(
    agent: CoordinatorAgent,
    suite: dict,
    categories: list[str] | None = None,
) -> tuple[list[QuestionResult], dict]:
    """Run the full benchmark suite."""
    all_results: list[QuestionResult] = []
    raw_responses: dict[str, dict] = {}

    cat_data = suite["categories"]
    if categories:
        cat_data = {k: v for k, v in cat_data.items() if k in categories}

    total_questions = 0
    for cat_name, cat_info in cat_data.items():
        if cat_name == "multi_turn":
            for session in cat_info.get("sessions", []):
                total_questions += len(session["turns"])
        else:
            total_questions += len(cat_info.get("questions", []))

    logger.info("Running benchmark: %d questions across %d categories",
                total_questions, len(cat_data))

    question_num = 0

    for cat_name, cat_info in cat_data.items():
        if cat_name == "multi_turn":
            # Multi-turn sessions
            for session in cat_info.get("sessions", []):
                session_id = f"bench_{session['id']}"
                for turn_idx, turn in enumerate(session["turns"]):
                    question_num += 1
                    qid = f"{session['id']}_T{turn_idx + 1}"
                    query = turn["query"]

                    print(f"  [{question_num}/{total_questions}] {qid}: {query[:50]}...", end="", flush=True)
                    response = await run_single_query(agent, query, session_id=session_id)
                    raw_responses[qid] = response

                    q_spec = {
                        "id": qid,
                        "query": query,
                        "expected_count_min": turn.get("expected_count_min", 0),
                    }
                    result = evaluate_question(q_spec, response, "multi_turn")
                    all_results.append(result)

                    status = "PASS" if (result.count_pass and result.no_error) else "FAIL"
                    print(f" → {result.total_count} results, {result.execution_time_ms:.0f}ms [{status}]")
        else:
            # Regular questions
            for question in cat_info.get("questions", []):
                question_num += 1
                qid = question["id"]
                query = question["query"]

                if not query:  # Skip empty queries
                    result = QuestionResult(
                        question_id=qid, query=query, category=cat_name,
                        error="empty_query", no_error=False, count_pass=True,
                    )
                    all_results.append(result)
                    print(f"  [{question_num}/{total_questions}] {qid}: (empty) → SKIP")
                    continue

                print(f"  [{question_num}/{total_questions}] {qid}: {query[:50]}...", end="", flush=True)
                response = await run_single_query(agent, query)
                raw_responses[qid] = response

                result = evaluate_question(question, response, cat_name)
                all_results.append(result)

                passed = result.count_pass and result.intent_pass and result.ontology_pass and result.no_error
                status = "PASS" if passed else "FAIL"
                print(f" → {result.total_count} results, {result.execution_time_ms:.0f}ms [{status}]")

    return all_results, raw_responses


async def main():
    parser = argparse.ArgumentParser(description="SCeQTL-Agent V2 Benchmark")
    parser.add_argument("--categories", type=str, default=None,
                        help="Comma-separated category names to run")
    parser.add_argument("--output", type=str, default="tests/benchmark/results",
                        help="Output directory for results")
    parser.add_argument("--suite", type=str,
                        default="tests/benchmark/benchmark_suite.json",
                        help="Path to benchmark suite JSON")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)

    # Load benchmark
    suite = load_benchmark(args.suite)
    categories = args.categories.split(",") if args.categories else None

    # Initialize agent
    db_path = str(project_root.parent / "database_development" / "unified_db" / "unified_metadata.db")
    if not Path(db_path).exists():
        print(f"ERROR: Database not found at {db_path}")
        return 1

    print("=" * 70)
    print("  SCeQTL-Agent V2 — Benchmark Evaluation")
    print("=" * 70)

    dal = DatabaseAbstractionLayer(db_path)

    onto_path = project_root / "data" / "ontologies" / "ontology_cache.db"
    mem_path = str(project_root / "data" / "memory")

    agent = CoordinatorAgent.create(
        dal=dal,
        llm=None,
        ontology_cache_path=str(onto_path) if onto_path.exists() else None,
        memory_db_path=mem_path,
    )

    print(f"\n  Agent: ontology={'YES' if agent.ontology else 'NO'}, "
          f"memory={'YES' if agent.episodic else 'NO'}")
    print(f"  Suite: {suite['description']}")
    print()

    # Run benchmark
    t0 = time.perf_counter()
    all_results, raw_responses = await run_benchmark(agent, suite, categories)
    total_time = time.perf_counter() - t0

    # Compute metrics
    category_metrics = {}
    for cat_name in suite["categories"]:
        cat_results = [r for r in all_results if r.category == cat_name]
        if cat_results:
            category_metrics[cat_name] = compute_category_metrics(cat_results, cat_name)

    overall = compute_overall_metrics(all_results, category_metrics)

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save raw responses
    with open(output_dir / "raw_responses.json", "w") as f:
        json.dump(raw_responses, f, ensure_ascii=False, indent=2, default=str)

    # Save metrics
    metrics_data = {
        "overall": {
            "total_questions": overall.total_questions,
            "passed": overall.total_passed,
            "failed": overall.total_failed,
            "errors": overall.total_errors,
            "pass_rate": round(overall.pass_rate, 1),
            "count_accuracy": round(overall.count_accuracy, 1),
            "intent_accuracy": round(overall.intent_accuracy, 1),
            "avg_response_time_ms": round(overall.avg_response_time_ms, 0),
            "p95_response_time_ms": round(overall.p95_response_time_ms, 0),
            "rule_resolution_rate": round(overall.rule_resolution_rate, 1),
            "template_resolution_rate": round(overall.template_resolution_rate, 1),
            "llm_resolution_rate": round(overall.llm_resolution_rate, 1),
            "multi_source_coverage": round(overall.multi_source_coverage, 1),
            "avg_dedup_rate": round(overall.avg_dedup_rate, 1),
            "suggestion_generation_rate": round(overall.suggestion_generation_rate, 1),
            "zero_result_rate": round(overall.zero_result_rate, 1),
            "error_rate": round(overall.error_rate, 1),
            "chinese_pass_rate": round(overall.chinese_pass_rate, 1),
            "english_pass_rate": round(overall.english_pass_rate, 1),
        },
        "categories": {},
        "total_time_seconds": round(total_time, 1),
    }
    for cat_name, cm in category_metrics.items():
        metrics_data["categories"][cat_name] = {
            "total": cm.total_questions,
            "passed": cm.passed,
            "failed": cm.failed,
            "errors": cm.errors,
            "count_pass_rate": round(cm.count_pass_rate, 1),
            "intent_accuracy": round(cm.intent_accuracy, 1),
            "ontology_trigger_rate": round(cm.ontology_trigger_rate, 1),
            "avg_time_ms": round(cm.avg_time_ms, 0),
            "p50_time_ms": round(cm.p50_time_ms, 0),
            "p95_time_ms": round(cm.p95_time_ms, 0),
            "rule_pct": round(cm.rule_pct, 1),
            "template_pct": round(cm.template_pct, 1),
            "multi_source_pct": round(cm.multi_source_pct, 1),
            "avg_dedup_rate": round(cm.avg_dedup_rate, 1),
            "failures": cm.failures,
        }

    with open(output_dir / "metrics.json", "w") as f:
        json.dump(metrics_data, f, ensure_ascii=False, indent=2)

    # Generate report
    report = generate_report(overall, category_metrics, total_time)
    with open(output_dir / "BENCHMARK_REPORT.md", "w") as f:
        f.write(report)

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"  BENCHMARK COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Total: {overall.total_questions} questions in {total_time:.1f}s")
    print(f"  Passed: {overall.total_passed}/{overall.total_questions} ({overall.pass_rate:.1f}%)")
    print(f"  Failed: {overall.total_failed}, Errors: {overall.total_errors}")
    print(f"  Avg time: {overall.avg_response_time_ms:.0f}ms, P95: {overall.p95_response_time_ms:.0f}ms")
    print(f"  Rule resolution: {overall.rule_resolution_rate:.0f}%")
    print(f"  Results saved to: {output_dir}/")
    print(f"{'=' * 70}")

    return 0 if overall.pass_rate >= 70 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
