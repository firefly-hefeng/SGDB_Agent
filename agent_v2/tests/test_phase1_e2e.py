"""
Phase 1 端到端集成测试

用真实数据库测试完整 Pipeline:
用户输入 → 查询理解 → SQL生成 → 并行执行 → 跨库融合 → 答案合成
"""

import sys
import os
import asyncio
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.dal.database import DatabaseAbstractionLayer
from src.agent.coordinator import CoordinatorAgent

DB_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "database_development", "unified_db", "unified_metadata.db"
))


async def run_test(agent: CoordinatorAgent, query: str, test_name: str, expect_min: int = 0):
    """运行单个测试"""
    print(f"\n{'─' * 60}")
    print(f"  TEST: {test_name}")
    print(f"  Query: \"{query}\"")
    print(f"{'─' * 60}")

    response = await agent.query(query)

    print(f"  Summary: {response.summary}")
    print(f"  Results: {response.total_count} total, {response.displayed_count} displayed")
    print(f"  Time: {response.provenance.execution_time_ms:.0f}ms")
    print(f"  SQL Method: {response.provenance.sql_method}")
    print(f"  Sources: {response.provenance.data_sources}")

    if response.provenance.fusion_stats:
        fs = response.provenance.fusion_stats
        print(f"  Fusion: raw={fs.get('raw_count')}, fused={fs.get('fused_count')}, dedup={fs.get('dedup_rate')}%")

    if response.quality_report.field_completeness:
        print(f"  Quality: {response.quality_report.field_completeness}")

    if response.suggestions:
        print(f"  Suggestions ({len(response.suggestions)}):")
        for s in response.suggestions[:3]:
            print(f"    - [{s.type}] {s.text}")

    if response.charts:
        print(f"  Charts: {len(response.charts)}")
        for c in response.charts:
            print(f"    - {c.type}: {c.title}")
            if isinstance(c.data, dict):
                top3 = list(c.data.items())[:3]
                print(f"      Top 3: {top3}")

    if response.results:
        r = response.results[0]
        sample_fields = {k: v for k, v in list(r.data.items())[:8]
                         if k not in ('raw_metadata', 'description', 'etl_source_file')}
        print(f"  Top result (score={r.quality_score}): {sample_fields}")

    # 验证
    ok = True
    if response.error:
        print(f"  ✗ ERROR: {response.error}")
        ok = False
    elif expect_min > 0 and response.total_count < expect_min:
        print(f"  ✗ Expected >= {expect_min} results, got {response.total_count}")
        ok = False
    else:
        print(f"  ✓ PASS")

    return ok


async def main():
    print("=" * 60)
    print("  SCeQTL-Agent V2 — Phase 1 End-to-End Integration Test")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"  SKIP: Database not found at {DB_PATH}")
        return 1

    dal = DatabaseAbstractionLayer(DB_PATH)
    agent = CoordinatorAgent.create(dal=dal, llm=None)  # 无LLM, 纯规则模式

    results = {}

    # Test 1: 简单搜索 (中文)
    results["简单搜索-中文"] = await run_test(
        agent, "查找人类大脑的数据集", "简单搜索 (中文)", expect_min=10
    )

    # Test 2: 多条件搜索
    results["多条件搜索"] = await run_test(
        agent, "find liver cancer datasets with 10x", "多条件搜索 (英文)", expect_min=5
    )

    # Test 3: ID查询
    results["ID查询"] = await run_test(
        agent, "GSE149614", "ID直接查询", expect_min=1
    )

    # Test 4: 统计查询
    results["统计查询"] = await run_test(
        agent, "统计各数据库的样本数量分布", "统计查询", expect_min=3
    )

    # Test 5: 疾病搜索
    results["疾病搜索"] = await run_test(
        agent, "Alzheimer's disease brain samples", "疾病搜索", expect_min=5
    )

    # Test 6: 细胞类型搜索
    results["细胞类型"] = await run_test(
        agent, "T cell blood datasets", "细胞类型搜索", expect_min=1
    )

    # Test 7: 空结果降级
    results["空结果降级"] = await run_test(
        agent, "查找火星上的单细胞数据", "空结果降级处理", expect_min=0
    )

    # Test 8: 探索查询
    results["探索查询"] = await run_test(
        agent, "有什么数据", "探索查询", expect_min=1
    )

    # Test 9: 多轮对话 (模拟)
    results["多轮-第一轮"] = await run_test(
        agent, "查找肝脏数据集", "多轮对话-第1轮", expect_min=10
    )
    results["多轮-第二轮"] = await run_test(
        agent, "这些中有哪些是癌症的", "多轮对话-第2轮 (细化)", expect_min=1
    )

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'=' * 60}")
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}")
    print(f"{'=' * 60}")
    print(f"  Phase 1 E2E: {passed}/{total} passed")
    print(f"{'=' * 60}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
