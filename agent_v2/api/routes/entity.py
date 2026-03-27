"""
Entity + cross-links routes
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import EntityLinksResponse
from api.deps import get_dal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["entity"])


@router.get("/entity/{id_value}", response_model=EntityLinksResponse)
async def get_entity(id_value: str):
    """Get entity by ID with cross-database links."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    entity = dal.get_entity_by_id(id_value)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{id_value}' not found")

    # Determine entity type from the data
    entity_type = ""
    pk = None
    if "project_id" in entity:
        entity_type = "project"
        pk = entity.get("pk")
    elif "series_id" in entity:
        entity_type = "series"
        pk = entity.get("pk")
    elif "sample_id" in entity:
        entity_type = "sample"
        pk = entity.get("pk")

    # Get cross-links
    cross_links = []
    if pk and entity_type:
        cross_links = dal.get_cross_db_links(pk, entity_type)

    return EntityLinksResponse(
        entity_id=id_value,
        entity_type=entity_type,
        entity_data=entity,
        cross_links=cross_links,
    )
