"""
Debug & Knowledge Layer API routes

提供知识层监控、统计缓存管理、字段统计查询等调试接口。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.deps import get_coordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI/debug", tags=["debug"])


@router.get("/knowledge-stats")
async def get_knowledge_stats():
    """获取动态知识层统计信息"""
    coordinator = get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Agent not available")

    stats_analyzer = getattr(coordinator, "stats_analyzer", None)
    feedback_loop = getattr(coordinator, "feedback_loop", None)

    result = {
        "knowledge_layer_enabled": stats_analyzer is not None,
        "cache": {
            "memory_cache_size": len(stats_analyzer._memory_cache) if stats_analyzer else 0,
            "cache_hit_rate": None,
        },
        "feedback": {
            "enabled": feedback_loop is not None,
            "total_records": feedback_loop.get_record_count() if feedback_loop else 0,
            "slow_queries_last_7d": (
                len(feedback_loop.get_slow_queries(threshold_ms=1000))
                if feedback_loop else 0
            ),
        },
    }

    return result


@router.get("/field-stats/{table}/{field}")
async def get_field_stats(table: str, field: str):
    """获取特定字段的统计信息"""
    coordinator = get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Agent not available")

    stats_analyzer = getattr(coordinator, "stats_analyzer", None)
    if not stats_analyzer:
        raise HTTPException(status_code=503, detail="Knowledge layer not enabled")

    stats = await stats_analyzer.get_field_stats(table, field)
    if not stats:
        raise HTTPException(status_code=404, detail=f"No stats for {table}.{field}")

    return {
        "table": stats.table_name,
        "field": stats.field_name,
        "data_type": stats.data_type,
        "semantic_type": stats.semantic_type,
        "total_count": stats.total_count,
        "non_null_count": stats.non_null_count,
        "null_pct": stats.null_pct,
        "distinct_count": stats.distinct_count,
        "selectivity": round(stats.selectivity, 6),
        "histogram": [
            {"value": v, "count": c} for v, c in stats.histogram
        ],
    }


@router.post("/invalidate-cache")
async def invalidate_cache(table: str | None = None):
    """手动使统计缓存失效"""
    coordinator = get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Agent not available")

    stats_analyzer = getattr(coordinator, "stats_analyzer", None)
    if not stats_analyzer:
        raise HTTPException(status_code=503, detail="Knowledge layer not enabled")

    before = len(stats_analyzer._memory_cache)
    await stats_analyzer.invalidate_cache(table)
    after = len(stats_analyzer._memory_cache)

    return {
        "success": True,
        "affected_entries": before - after,
        "scope": table or "all",
    }


@router.get("/feedback/slow-queries")
async def get_slow_queries(threshold_ms: float = 1000.0, limit: int = 10):
    """获取慢查询列表"""
    coordinator = get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Agent not available")

    feedback_loop = getattr(coordinator, "feedback_loop", None)
    if not feedback_loop:
        raise HTTPException(status_code=503, detail="Feedback loop not enabled")

    return {
        "slow_queries": feedback_loop.get_slow_queries(threshold_ms, limit),
        "threshold_ms": threshold_ms,
    }


@router.post("/query/analyze")
async def analyze_query(query: str, session_id: str = "debug"):
    """分析查询但不执行，返回解析结果和估计信息"""
    coordinator = get_coordinator()
    if not coordinator:
        raise HTTPException(status_code=503, detail="Agent not available")

    from src.core.models import SessionContext

    context = SessionContext(session_id=session_id)

    # Parse
    parsed = await coordinator.parser.parse(query, context)

    # Estimate
    estimation = None
    cardinality_est = getattr(coordinator, "cardinality_est", None)
    if cardinality_est:
        try:
            from src.sql.contextual_engine import ContextualSQLGenerator
            filters_dict = ContextualSQLGenerator._filters_to_dict(parsed.filters)
            estimated_rows = await cardinality_est.estimate_result_size(
                "unified_samples", filters_dict,
            )
            suggested_limit = await cardinality_est.suggest_limit(
                "unified_samples", filters_dict, parsed.limit,
            )
            estimation = {
                "estimated_rows": estimated_rows,
                "suggested_limit": suggested_limit,
            }
        except Exception as e:
            estimation = {"error": str(e)}

    return {
        "parsed": {
            "intent": parsed.intent.name,
            "complexity": parsed.complexity.name,
            "filters": {
                "tissues": parsed.filters.tissues,
                "diseases": parsed.filters.diseases,
                "cell_types": parsed.filters.cell_types,
                "organisms": parsed.filters.organisms,
                "source_databases": parsed.filters.source_databases,
            },
            "target_level": parsed.target_level,
            "confidence": parsed.confidence,
            "parse_method": parsed.parse_method,
        },
        "estimation": estimation,
    }
