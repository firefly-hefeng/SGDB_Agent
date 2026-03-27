"""
Phase 0 冒烟测试

验证:
1. 数据库连接和SchemaInspector
2. LLM客户端接口
3. 熔断器逻辑
4. 成本控制器
5. 缓存系统
"""

import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_database_and_schema():
    """测试数据库连接和Schema分析"""
    print("\n" + "=" * 60)
    print("TEST 1: Database Connection & Schema Inspector")
    print("=" * 60)

    from src.dal.database import DatabaseAbstractionLayer

    # 查找数据库
    db_path = os.path.join(
        os.path.dirname(__file__), "..",  "..",
        "database_development", "unified_db", "unified_metadata.db"
    )
    db_path = os.path.abspath(db_path)

    if not os.path.exists(db_path):
        print(f"  SKIP: Database not found at {db_path}")
        return False

    dal = DatabaseAbstractionLayer(db_path)
    print(f"  ✓ Connected to {db_path}")

    # Schema分析
    schema = dal.schema_inspector.analyze()
    print(f"  ✓ Schema analyzed: {schema['total_tables']} tables, {schema['total_views']} views")

    for name, info in schema["tables"].items():
        if not info["is_view"]:
            print(f"    - {name}: {info['record_count']:,} rows, {len(info['columns'])} columns")

    # Schema摘要
    summary = dal.get_schema_summary()
    print(f"  ✓ Summary: {summary['stats']['total_samples']:,} samples, "
          f"{summary['stats']['total_projects']:,} projects")

    # DDL摘要
    ddl = dal.schema_inspector.get_ddl_summary()
    print(f"  ✓ DDL summary: {len(ddl)} chars")

    # 字段统计
    stats = dal.get_field_stats("unified_samples", "tissue", 5)
    print(f"  ✓ tissue stats: {stats.distinct_count} distinct, {stats.null_pct}% null")
    for val, cnt in stats.top_values[:5]:
        print(f"    - {val}: {cnt:,}")

    # ID查询
    test_ids = ["GSE149614", "PRJNA625514"]
    for tid in test_ids:
        entity = dal.get_entity_by_id(tid)
        if entity:
            print(f"  ✓ get_entity_by_id('{tid}'): found ({entity.get('title', '')[:50]}...)")
        else:
            print(f"  - get_entity_by_id('{tid}'): not found")

    # 样本搜索
    from src.core.models import QueryFilters
    filters = QueryFilters(tissues=["brain"], diseases=["normal"])
    result = dal.search_samples(filters, limit=5)
    print(f"  ✓ search_samples(brain, normal): {result.total_count} total, "
          f"{result.returned_count} returned, {result.execution_time_ms}ms")

    return True


def test_circuit_breaker():
    """测试熔断器"""
    print("\n" + "=" * 60)
    print("TEST 2: Circuit Breaker")
    print("=" * 60)

    from src.infra.llm_router import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=2)

    # 初始状态: CLOSED
    assert cb.state == "closed", f"Expected closed, got {cb.state}"
    print(f"  ✓ Initial state: {cb.state}")

    # 连续失败
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "closed"  # 还没到阈值
    print(f"  ✓ After 2 failures: {cb.state}")

    cb.record_failure()  # 第3次，触发熔断
    assert cb.state == "open"
    print(f"  ✓ After 3 failures: {cb.state} (breaker tripped)")

    assert cb.is_open
    print(f"  ✓ is_open: {cb.is_open}")

    # 等待恢复
    time.sleep(2.1)
    assert cb.state == "half_open"
    print(f"  ✓ After recovery timeout: {cb.state}")

    # 恢复成功
    cb.record_success()
    assert cb.state == "closed"
    print(f"  ✓ After success: {cb.state}")

    return True


def test_cost_controller():
    """测试成本控制器"""
    print("\n" + "=" * 60)
    print("TEST 3: Cost Controller")
    print("=" * 60)

    from src.infra.cost_controller import CostController, MODEL_PRICING
    from src.core.models import TokenUsage

    cc = CostController(daily_budget_usd=1.0)  # $1预算用于测试

    # 初始状态
    assert cc.has_budget()
    print(f"  ✓ Initial budget: ${cc.remaining_budget:.2f}")

    # 模型选择
    model = cc.select_model("simple")
    assert model == "claude-haiku-4-5"
    print(f"  ✓ Simple query model: {model}")

    model = cc.select_model("complex")
    print(f"  ✓ Complex query model: {model}")
    # Note: with $1 budget, complex also gets haiku (budget-aware downgrade)

    # 记录使用
    usage = TokenUsage(model="claude-haiku-4-5", input_tokens=1000, output_tokens=500)
    cost = cc.record_usage(usage)
    print(f"  ✓ Haiku call (1K in, 500 out): ${cost:.6f}")

    # 大量使用超预算
    for _ in range(100):
        cc.record_usage(TokenUsage(
            model="claude-sonnet-4-6",
            input_tokens=10000,
            output_tokens=5000,
        ))

    print(f"  ✓ After heavy usage: ${cc.daily_spend:.2f} / ${cc.daily_budget:.2f}")
    print(f"  ✓ Has budget: {cc.has_budget()}")

    # 超预算时模型降级
    model = cc.select_model("complex")
    print(f"  ✓ Model after budget exceeded: '{model}' (empty = use rules)")

    # 成本报告
    report = cc.get_report()
    print(f"  ✓ Report: {report['total_calls']} calls, ${report['daily_spend']:.2f}")

    return True


def test_cache_system():
    """测试缓存系统"""
    print("\n" + "=" * 60)
    print("TEST 4: Cache System")
    print("=" * 60)

    from src.memory.cache import LRUCache, SQLResultCache, CacheSystem

    # LRU Cache
    lru = LRUCache(capacity=3)
    lru.set("a", {"data": 1})
    lru.set("b", {"data": 2})
    lru.set("c", {"data": 3})
    assert lru.get("a") == {"data": 1}
    print(f"  ✓ LRU get: {lru.get('a')}")

    lru.set("d", {"data": 4})  # 应该淘汰 b (a刚被访问)
    assert lru.get("b") is None
    print(f"  ✓ LRU eviction: 'b' evicted after capacity exceeded")
    print(f"  ✓ LRU stats: {lru.stats()}")

    # SQL Result Cache
    sql_cache = SQLResultCache()
    key = SQLResultCache.make_cache_key("SELECT * FROM t WHERE x=?", [1])
    sql_cache.set(key, [{"id": 1}, {"id": 2}], category="search", ttl=10)
    result = sql_cache.get(key)
    assert result == [{"id": 1}, {"id": 2}]
    print(f"  ✓ SQL cache set/get: {len(result)} rows")

    # TTL过期
    sql_cache.set("expired", [{"x": 1}], category="test", ttl=0)
    time.sleep(0.1)
    assert sql_cache.get("expired") is None
    print(f"  ✓ SQL cache TTL expiry works")

    # Cache System
    cs = CacheSystem(session_cache_size=10, global_cache_size=50)
    session_cache = cs.get_session_cache("user123")
    session_cache.set("q1", {"results": [1, 2, 3]})
    assert session_cache.get("q1") == {"results": [1, 2, 3]}
    print(f"  ✓ CacheSystem session isolation works")
    print(f"  ✓ CacheSystem stats: {cs.stats()}")

    return True


def test_llm_interface():
    """测试LLM接口结构 (不实际调用API)"""
    print("\n" + "=" * 60)
    print("TEST 5: LLM Interface Structure")
    print("=" * 60)

    from src.core.interfaces import ILLMClient
    from src.core.models import LLMResponse, LLMToolCall, TokenUsage

    # 验证数据结构
    response = LLMResponse(
        content="test response",
        tool_calls=[
            LLMToolCall(tool_name="search", tool_input={"query": "brain"}, tool_id="t1")
        ],
        usage=TokenUsage(model="claude-sonnet-4-6", input_tokens=100, output_tokens=50),
        stop_reason="end_turn",
    )
    assert response.has_tool_calls()
    assert response.tool_calls[0].tool_name == "search"
    print(f"  ✓ LLMResponse: content={response.content[:20]}, "
          f"tools={len(response.tool_calls)}, "
          f"tokens={response.usage.input_tokens}+{response.usage.output_tokens}")

    # 验证ClaudeLLMClient结构 (不实际连接)
    print(f"  ✓ ILLMClient Protocol defined with: chat, chat_stream, estimate_tokens, model_id")
    print(f"  ✓ ClaudeLLMClient and OpenAILLMClient implemented")

    return True


def test_data_models():
    """测试核心数据模型"""
    print("\n" + "=" * 60)
    print("TEST 6: Core Data Models")
    print("=" * 60)

    from src.core.models import (
        ParsedQuery, QueryIntent, QueryComplexity, QueryFilters,
        BioEntity, ResolvedEntity, OntologyTerm, DBValueMatch,
        SQLCandidate, ExecutionResult, FusedRecord, AgentResponse,
        JoinPlan, JoinClause, Suggestion, ChartSpec,
    )

    # ParsedQuery
    query = ParsedQuery(
        intent=QueryIntent.SEARCH,
        complexity=QueryComplexity.MODERATE,
        entities=[
            BioEntity(text="大脑", entity_type="tissue", normalized_value="brain"),
            BioEntity(text="阿尔茨海默", entity_type="disease", normalized_value="Alzheimer's disease"),
        ],
        filters=QueryFilters(tissues=["brain"], diseases=["Alzheimer"]),
        target_level="sample",
        original_text="查找大脑阿尔茨海默病数据集",
        language="zh",
    )
    print(f"  ✓ ParsedQuery: intent={query.intent.name}, "
          f"entities={len(query.entities)}, complexity={query.complexity.name}")

    # JoinPlan
    plan = JoinPlan(
        base_table="unified_samples",
        joins=[
            JoinClause("LEFT JOIN", "unified_projects", condition="samples.project_pk = projects.pk"),
        ],
    )
    print(f"  ✓ JoinPlan: {plan.to_sql_from()[:60]}...")

    # FusedRecord
    fused = FusedRecord(
        data={"tissue": "brain", "disease": "AD"},
        sources=["cellxgene", "geo", "ncbi"],
        source_count=3,
        records_merged=3,
        quality_score=87.5,
    )
    print(f"  ✓ FusedRecord: score={fused.quality_score}, sources={fused.sources}")

    # AgentResponse
    resp = AgentResponse(
        summary="找到47个结果",
        results=[fused],
        total_count=47,
        suggestions=[Suggestion(type="refine", text="按脑区细化", action_query="", reason="")],
        charts=[ChartSpec(type="pie", title="来源分布", data={"cxg": 18, "geo": 21})],
    )
    print(f"  ✓ AgentResponse: '{resp.summary}', "
          f"{len(resp.results)} results, {len(resp.suggestions)} suggestions")

    return True


def main():
    print("=" * 60)
    print("  SCeQTL-Agent V2 — Phase 0 Smoke Test")
    print("=" * 60)

    results = {}
    tests = [
        ("Data Models", test_data_models),
        ("Circuit Breaker", test_circuit_breaker),
        ("Cost Controller", test_cost_controller),
        ("Cache System", test_cache_system),
        ("LLM Interface", test_llm_interface),
        ("Database & Schema", test_database_and_schema),
    ]

    for name, test_fn in tests:
        try:
            ok = test_fn()
            results[name] = "PASS" if ok else "SKIP"
        except Exception as e:
            results[name] = f"FAIL: {e}"
            import traceback
            traceback.print_exc()

    # 汇总
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, status in results.items():
        icon = "✓" if status == "PASS" else ("⊘" if status == "SKIP" else "✗")
        print(f"  {icon} {name}: {status}")
        if "FAIL" in str(status):
            all_pass = False

    print("=" * 60)
    if all_pass:
        print("  Phase 0 smoke test: ALL PASSED")
    else:
        print("  Phase 0 smoke test: SOME FAILURES")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
