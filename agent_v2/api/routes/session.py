"""
Session management routes
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from api.schemas import SessionHistoryResponse, SessionHistoryItem, FeedbackRequest
from api.deps import get_coordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["session"])


@router.get("/session/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str):
    """Get conversation history for a session."""
    coordinator = get_coordinator()
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    ctx = coordinator._sessions.get(session_id)
    if ctx is None:
        return SessionHistoryResponse(session_id=session_id, turns=[])

    return SessionHistoryResponse(
        session_id=session_id,
        turns=[
            SessionHistoryItem(
                query=t.get("input", ""),
                intent=t.get("intent", ""),
                result_count=t.get("result_count", 0),
                timestamp=t.get("timestamp", 0),
            )
            for t in ctx.turns
        ],
    )


@router.post("/session/{session_id}/feedback")
async def submit_feedback(session_id: str, req: FeedbackRequest):
    """Submit user feedback for a session query."""
    coordinator = get_coordinator()
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Store in episodic memory if available
    if coordinator.episodic:
        try:
            coordinator.episodic.record_feedback(
                session_id=session_id,
                query=req.query,
                rating=req.rating,
                comment=req.comment,
            )
        except Exception as e:
            logger.warning("Failed to record feedback: %s", e)

    return {"status": "ok", "message": "Feedback recorded"}
