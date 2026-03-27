"""
Phase 2 端到端集成测试

测试完整 V2 Pipeline (含 Ontology + Memory + FTS5):
用户输入 → 查询理解 → 本体解析 → SQL生成 → 并行执行 → 跨库融合 → 答案合成
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.dal.database import DatabaseAbstractionLayer
from src.agent.coordinator import CoordinatorAgent

DB_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "database_development", "unified_db", "unified_metadata.db"
))

ONTOLOGY_CACHE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "ontologies", "ontology_cache.db"
))

MEMORY_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "data", "memory"
))


async def run_test(
    agent: CoordinatorAgent,
    query: str,
    test_name: str,
    expect_min: int = 0,
    session_id: str = "default",
    check_ontology: bool = False,
    check_method: str | None = None,
):
    """运行单个测试"""
    print(f"\n{'─' * 60}")
    print(f"  TEST: {test_name}")
    print(f"  Query: \"{query}\"")
    print(f"{'─' * 60}")

    response = await agent.query(query, session_id=session_id)

    print(f"  Summary: {response.summary}")
    print(f"  Results: {response.total_count} total, {response.displayed_count} displayed")
    print(f"  Time: {response.provenance.execution_time_ms:.0f}ms")
    print(f"  SQL Method: {response.provenance.sql_method}")
    print(f"  Sources: {response.provenance.data_sources}")

    # Ontology info
    if response.provenance.ontology_expansions:
        print(f"  Ontology expansions ({len(response.provenance.ontology_expansions)}):")
        for exp in response.provenance.ontology_expansions:
            print(f"    - {exp['original']} → {exp['ontology_id']} ({exp['label']}), "
                  f"{exp['db_values_count']} DB values, {exp['total_samples']} samples")

    if response.provenance.fusion_stats:
        fs = response.provenance.fusion_stats
        print(f"  Fusion: raw={fs.get('raw_count')}, fused={fs.get('fused_count')}, dedup={fs.get('dedup_rate')}%")

    if response.quality_report.field_completeness:
        print(f"  Quality: {response.quality_report.field_completeness}")

    if response.suggestions:
        print(f"  Suggestions ({len(response.suggestions)}):")
        for s in response.suggestions[:3]:
            print(f"    - [{s.type}] {s.text}")

    if response.results:
        r = response.results[0]
        sample_fields = {k: v for k, v in list(r.data.items())[:8]
                         if k not in ('raw_metadata', 'description', 'etl_source_file')}
        print(f"  Top result (score={r.quality_score}): {sample_fields}")

    # Verify
    ok = True
    issues = []

    if response.error:
        issues.append(f"ERROR: {response.error}")
        ok = False
    elif expect_min > 0 and response.total_count < expect_min:
        issues.append(f"Expected >= {expect_min} results, got {response.total_count}")
        ok = False

    if check_ontology and not response.provenance.ontology_expansions:
        issues.append("Expected ontology expansion but none found")
        ok = False

    if check_method and response.provenance.sql_method != check_method:
        issues.append(f"Expected method={check_method}, got {response.provenance.sql_method}")
        # Don't fail on method mismatch, just warn
        print(f"  ⚠ {issues[-1]}")

    if ok:
        print(f"  ✓ PASS")
    else:
        for issue in issues:
            print(f"  ✗ {issue}")

    return ok


async def main():
    print("=" * 60)
    print("  SCeQTL-Agent V2 — Phase 2 End-to-End Integration Test")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"  SKIP: Database not found at {DB_PATH}")
        return 1

    dal = DatabaseAbstractionLayer(DB_PATH)

    # Init with ontology + memory (optional)
    onto_path = ONTOLOGY_CACHE if os.path.exists(ONTOLOGY_CACHE) else None
    mem_path = MEMORY_DIR if True else None  # always try

    agent = CoordinatorAgent.create(
        dal=dal,
        llm=None,
        ontology_cache_path=onto_path,
        memory_db_path=mem_path,
    )

    has_ontology = agent.ontology is not None
    print(f"\n  Ontology: {'✓ loaded' if has_ontology else '✗ not available'}")
    print(f"  Memory:   {'✓ loaded' if agent.episodic else '✗ not available'}")
    print()

    results = {}

    # ─── Phase 1 regression tests ───

    results["简单搜索-中文"] = await run_test(
        agent, "查找人类大脑的数据集", "简单搜索 (中文)",
        expect_min=10, check_ontology=has_ontology, check_method="rule",
    )

    results["多条件搜索"] = await run_test(
        agent, "find liver cancer datasets with 10x", "多条件搜索 (英文)",
        expect_min=5, check_ontology=has_ontology,
    )

    results["ID查询"] = await run_test(
        agent, "GSE149614", "ID直接查询",
        expect_min=1, check_method="template",
    )

    results["统计查询"] = await run_test(
        agent, "统计各数据库的样本数量分布", "统计查询",
        expect_min=3, check_method="template",
    )

    results["疾病搜索"] = await run_test(
        agent, "Alzheimer's disease brain samples", "疾病搜索",
        expect_min=1, check_ontology=has_ontology,
    )

    results["细胞类型"] = await run_test(
        agent, "T cell blood datasets", "细胞类型搜索",
        expect_min=1, check_ontology=has_ontology,
    )

    # ─── Phase 2 new tests ───

    results["本体扩展-brain"] = await run_test(
        agent, "search brain cortex samples", "本体扩展 (brain cortex)",
        expect_min=1, check_ontology=has_ontology,
    )

    results["本体扩展-cancer"] = await run_test(
        agent, "查找肝癌相关数据", "本体扩展 (hepatocellular carcinoma)",
        expect_min=1, check_ontology=has_ontology,
    )

    # ─── Multi-turn with memory ───

    session_id = "multi_turn_test"
    results["多轮-第1轮"] = await run_test(
        agent, "查找肝脏数据集", "多轮对话-第1轮",
        expect_min=10, session_id=session_id,
    )
    results["多轮-第2轮"] = await run_test(
        agent, "这些中有哪些是癌症的", "多轮对话-第2轮 (细化)",
        expect_min=1, session_id=session_id,
    )
    results["多轮-第3轮"] = await run_test(
        agent, "统计它们的来源分布", "多轮对话-第3轮 (统计)",
        expect_min=1, session_id=session_id,
    )

    # ─── Edge cases ───

    results["空结果降级"] = await run_test(
        agent, "查找火星上的单细胞数据", "空结果降级",
        expect_min=0,
    )

    results["探索查询"] = await run_test(
        agent, "有什么数据", "探索查询",
        expect_min=1,
    )

    # ─── Summary ───
    print(f"\n{'=' * 60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'=' * 60}")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}")
    print(f"{'=' * 60}")
    print(f"  Phase 2 E2E: {passed}/{total} passed")
    if has_ontology:
        print(f"  (with ontology resolution)")
    print(f"{'=' * 60}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
