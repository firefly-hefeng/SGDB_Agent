"""
Core query route: POST /scdbAPI/query
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import (
    QueryRequest,
    QueryResponse,
    ResultRecord,
    ProvenanceOut,
    QualityOut,
    SuggestionOut,
    ChartOut,
)
from api.deps import get_coordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """
    Natural language query endpoint.

    Accepts a user query and returns structured results with:
    - Natural language summary
    - Fused results from multiple databases
    - Data provenance and quality report
    - Follow-up suggestions
    - Chart specifications
    """
    coordinator = get_coordinator()
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        resp = await coordinator.query(
            user_input=req.query,
            session_id=req.session_id,
            user_id=req.user_id,
        )
    except Exception as e:
        logger.error("Query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query processing error: {e}")

    return QueryResponse(
        summary=resp.summary,
        results=[
            ResultRecord(
                data=r.data,
                sources=r.sources,
                source_count=r.source_count,
                quality_score=r.quality_score,
            )
            for r in resp.results
        ],
        total_count=resp.total_count,
        displayed_count=resp.displayed_count,
        provenance=ProvenanceOut(
            original_query=resp.provenance.original_query,
            parsed_intent=resp.provenance.parsed_intent,
            ontology_expansions=resp.provenance.ontology_expansions,
            sql_executed=resp.provenance.sql_executed,
            sql_method=resp.provenance.sql_method,
            strategy_level=resp.provenance.strategy_level,
            fusion_stats=resp.provenance.fusion_stats,
            data_sources=resp.provenance.data_sources,
            execution_time_ms=resp.provenance.execution_time_ms,
        ),
        quality_report=QualityOut(
            field_completeness=resp.quality_report.field_completeness,
            cross_validation_score=resp.quality_report.cross_validation_score,
            source_coverage=resp.quality_report.source_coverage,
        ),
        suggestions=[
            SuggestionOut(
                type=s.type,
                text=s.text,
                action_query=s.action_query,
                reason=s.reason,
            )
            for s in resp.suggestions
        ],
        charts=[
            ChartOut(type=c.type, title=c.title, data=c.data)
            for c in resp.charts
        ],
        error=resp.error,
    )
