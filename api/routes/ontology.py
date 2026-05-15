"""
Ontology + autocomplete routes
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from api.schemas import OntologyResolveResponse, AutocompleteResponse
from api.deps import get_coordinator, get_dal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["ontology"])


@router.get("/ontology/resolve", response_model=OntologyResolveResponse)
async def resolve_ontology(
    term: str = Query(..., min_length=1, max_length=200),
    type: str = Query(default="tissue", pattern=r"^(tissue|disease|cell_type|assay)$"),
    expand: bool = Query(default=True),
):
    """Resolve a term to ontology ID and get DB value mappings."""
    coordinator = get_coordinator()
    if coordinator is None or coordinator.ontology is None:
        raise HTTPException(status_code=503, detail="Ontology resolver not available")

    from src.core.models import BioEntity
    entity = BioEntity(text=term, entity_type=type, normalized_value=term.lower())
    resolved = coordinator.ontology.resolve_entity(entity, expand=expand)

    return OntologyResolveResponse(
        term=term,
        field_type=type,
        ontology_id=resolved.ontology_term.ontology_id if resolved.ontology_term else None,
        label=resolved.ontology_term.label if resolved.ontology_term else None,
        synonyms=resolved.ontology_term.synonyms[:10] if resolved.ontology_term else [],
        db_values=[
            {"value": v.raw_value, "count": v.count, "match_type": v.match_type}
            for v in resolved.db_values[:50]
        ],
        children_count=len(resolved.expanded_terms),
        total_samples=resolved.total_sample_count,
    )


@router.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    field: str = Query(..., pattern=r"^(tissue|disease|cell_type|assay|organism|source_database)$"),
    prefix: str = Query(default="", max_length=100),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Field value autocomplete."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Map field to table
    field_table_map = {
        "tissue": ("unified_samples", "tissue"),
        "disease": ("unified_samples", "disease"),
        "cell_type": ("unified_celltypes", "cell_type_name"),
        "assay": ("unified_samples", "assay"),
        "organism": ("unified_samples", "organism"),
        "source_database": ("unified_samples", "source_database"),
    }

    table, col = field_table_map[field]

    if prefix:
        result = dal.execute(
            f"SELECT [{col}] as val, COUNT(*) as cnt FROM [{table}] "
            f"WHERE [{col}] LIKE ? AND [{col}] IS NOT NULL "
            f"GROUP BY [{col}] ORDER BY cnt DESC LIMIT ?",
            [f"{prefix}%", limit],
        )
    else:
        result = dal.execute(
            f"SELECT [{col}] as val, COUNT(*) as cnt FROM [{table}] "
            f"WHERE [{col}] IS NOT NULL "
            f"GROUP BY [{col}] ORDER BY cnt DESC LIMIT ?",
            [limit],
        )

    return AutocompleteResponse(
        field=field,
        prefix=prefix,
        values=[{"value": r["val"], "count": r["cnt"]} for r in result.rows],
    )
