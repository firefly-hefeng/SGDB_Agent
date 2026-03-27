"""
WebSocket streaming endpoint for real-time query results.

Protocol:
  Client sends: {"query": "...", "session_id": "..."}
  Server sends sequence of:
    {"type": "status", "data": {"stage": "parsing"}}
    {"type": "status", "data": {"stage": "ontology", "expansions": [...]}}
    {"type": "status", "data": {"stage": "executing"}}
    {"type": "result", "data": {<QueryResponse>}}
    {"type": "done"}
  On error:
    {"type": "error", "data": {"message": "..."}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.deps import get_coordinator
from api.schemas import QueryResponse, ResultRecord, ProvenanceOut, QualityOut, SuggestionOut, ChartOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/scdbAPI/query/stream")
async def query_stream(ws: WebSocket):
    """WebSocket endpoint for streaming query results."""
    await ws.accept()
    logger.info("WebSocket connected")

    try:
        while True:
            # Receive query
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, "error", {"message": "Invalid JSON"})
                continue

            query = msg.get("query", "").strip()
            if not query:
                await _send(ws, "error", {"message": "Empty query"})
                continue

            session_id = msg.get("session_id", "default")
            user_id = msg.get("user_id", "anonymous")

            coordinator = get_coordinator()
            if coordinator is None:
                await _send(ws, "error", {"message": "Agent not initialized"})
                continue

            # Stream the pipeline stages
            t0 = time.perf_counter()

            try:
                # Stage 1: Parsing
                await _send(ws, "status", {"stage": "parsing", "message": "Analyzing query..."})

                from src.core.models import SessionContext
                context = coordinator._sessions.get(
                    session_id,
                    SessionContext(session_id=session_id)
                )
                wmem = coordinator._get_working_memory(session_id)
                if wmem:
                    context = wmem.get_context()

                parsed = await coordinator.parser.parse(query, context)
                await _send(ws, "status", {
                    "stage": "parsed",
                    "message": f"Intent: {parsed.intent.name}, {len(parsed.entities)} entities",
                    "intent": parsed.intent.name,
                    "entities": [{"text": e.text, "type": e.entity_type} for e in parsed.entities],
                })

                # Stage 2: Ontology
                resolved_entities = None
                ontology_expansions = []
                if coordinator.ontology and parsed.entities:
                    await _send(ws, "status", {"stage": "ontology", "message": "Resolving ontology..."})
                    resolved_entities = coordinator.ontology.resolve_all(parsed.entities)
                    for re_ in resolved_entities:
                        if re_.ontology_term:
                            ontology_expansions.append({
                                "original": re_.original.text,
                                "ontology_id": re_.ontology_term.ontology_id,
                                "label": re_.ontology_term.label,
                                "db_values_count": len(re_.db_values),
                                "total_samples": re_.total_sample_count,
                            })
                    if ontology_expansions:
                        await _send(ws, "status", {
                            "stage": "ontology_done",
                            "message": f"Resolved {len(ontology_expansions)} ontology terms",
                            "expansions": ontology_expansions,
                        })

                # Stage 3: SQL generation
                await _send(ws, "status", {"stage": "generating_sql", "message": "Generating SQL..."})
                candidates = await coordinator.sql_gen.generate(parsed, resolved_entities)
                await _send(ws, "status", {
                    "stage": "sql_ready",
                    "message": f"{len(candidates)} SQL candidates",
                })

                # Stage 4: Execution
                await _send(ws, "status", {"stage": "executing", "message": "Querying databases..."})
                exec_result = await coordinator.sql_exec.execute(candidates)
                await _send(ws, "status", {
                    "stage": "executed",
                    "message": f"Found {exec_result.row_count} raw results ({exec_result.exec_time_ms:.0f}ms)",
                })

                # Stage 5: Fusion
                await _send(ws, "status", {"stage": "fusing", "message": "Cross-database fusion..."})
                fused = coordinator.fusion.fuse(exec_result.rows)

                # Stage 6: Synthesis
                elapsed_ms = (time.perf_counter() - t0) * 1000
                response = coordinator._synthesize(
                    parsed, fused, exec_result, elapsed_ms, ontology_expansions
                )

                # Update memories
                coordinator._update_memories(
                    session_id, user_id, parsed, fused, exec_result, elapsed_ms, wmem
                )

                # Send full result
                result = QueryResponse(
                    summary=response.summary,
                    results=[
                        ResultRecord(
                            data=r.data, sources=r.sources,
                            source_count=r.source_count, quality_score=r.quality_score,
                        )
                        for r in response.results
                    ],
                    total_count=response.total_count,
                    displayed_count=response.displayed_count,
                    provenance=ProvenanceOut(
                        original_query=response.provenance.original_query,
                        parsed_intent=response.provenance.parsed_intent,
                        ontology_expansions=response.provenance.ontology_expansions,
                        sql_executed=response.provenance.sql_executed,
                        sql_method=response.provenance.sql_method,
                        fusion_stats=response.provenance.fusion_stats,
                        data_sources=response.provenance.data_sources,
                        execution_time_ms=response.provenance.execution_time_ms,
                    ),
                    quality_report=QualityOut(
                        field_completeness=response.quality_report.field_completeness,
                        cross_validation_score=response.quality_report.cross_validation_score,
                        source_coverage=response.quality_report.source_coverage,
                    ),
                    suggestions=[
                        SuggestionOut(
                            type=s.type, text=s.text,
                            action_query=s.action_query, reason=s.reason,
                        )
                        for s in response.suggestions
                    ],
                    charts=[
                        ChartOut(type=c.type, title=c.title, data=c.data)
                        for c in response.charts
                    ],
                    error=response.error,
                )

                await _send(ws, "result", result.model_dump())
                await _send(ws, "done", {})

            except Exception as e:
                logger.error("WebSocket query error: %s", e, exc_info=True)
                await _send(ws, "error", {"message": str(e)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)


async def _send(ws: WebSocket, msg_type: str, data: dict):
    """Send a typed message through WebSocket."""
    await ws.send_json({"type": msg_type, "data": data})
