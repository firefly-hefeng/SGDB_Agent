"""
Dataset detail route — full entity metadata + cross-links + download options.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_dal
from api.services.download_resolver import DownloadResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["dataset"])

_resolver = DownloadResolver()


class DownloadOptionOut(BaseModel):
    file_type: str
    label: str
    url: str | None = None
    instructions: str = ""
    source: str = ""


class CrossLinkOut(BaseModel):
    linked_id: str = ""
    linked_database: str = ""
    linked_title: str | None = None
    relationship_type: str = ""


class DatasetDetailResponse(BaseModel):
    entity_id: str
    entity_type: str = ""
    title: str | None = None
    description: str | None = None
    organism: str | None = None
    source_database: str = ""
    project: dict | None = None
    series: list[dict] = []
    samples: list[dict] = []
    sample_count: int = 0
    cross_links: list[CrossLinkOut] = []
    downloads: list[DownloadOptionOut] = []
    pmid: str | None = None
    doi: str | None = None


@router.get("/dataset/{id_value}", response_model=DatasetDetailResponse)
async def get_dataset_detail(id_value: str):
    """Get full dataset detail with metadata, samples, cross-links, and download options."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Find the entity
    entity = dal.get_entity_by_id(id_value)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {id_value} not found")

    entity_data = dict(entity)

    # Detect entity type from ID pattern or presence of key fields
    entity_type = _detect_entity_type(id_value, entity_data)

    # Determine project PK
    project_pk = entity_data.get("pk") if entity_type == "project" else entity_data.get("project_pk")
    project_data = None
    series_list = []
    samples = []
    sample_count = 0

    # Load project
    if project_pk:
        try:
            result = dal.execute(
                "SELECT * FROM unified_projects WHERE pk = ?", [project_pk]
            )
            if result.rows:
                project_data = _clean_row(result.rows[0])
        except Exception as e:
            logger.warning("Failed to load project %s: %s", project_pk, e)

    # Load series
    if project_pk:
        try:
            result = dal.execute(
                "SELECT * FROM unified_series WHERE project_pk = ? LIMIT 50", [project_pk]
            )
            series_list = [_clean_row(r) for r in result.rows]
        except Exception as e:
            logger.warning("Failed to load series: %s", e)

    # Load samples (paginated)
    if project_pk:
        try:
            cnt = dal.execute(
                "SELECT COUNT(*) as cnt FROM unified_samples WHERE project_pk = ?", [project_pk]
            )
            sample_count = cnt.rows[0]["cnt"] if cnt.rows else 0

            result = dal.execute(
                "SELECT s.sample_id, s.tissue, s.disease, s.cell_type, s.organism, s.sex, s.n_cells, "
                "s.source_database, sr.assay FROM unified_samples s "
                "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
                "WHERE s.project_pk = ? LIMIT 100",
                [project_pk],
            )
            samples = [dict(r) for r in result.rows]
        except Exception as e:
            logger.warning("Failed to load samples: %s", e)
    elif entity_type == "sample":
        samples = [entity_data]
        sample_count = 1

    # Cross-links
    cross_links: list[CrossLinkOut] = []
    entity_pk = entity_data.get("pk")
    if entity_pk and entity_type:
        try:
            result = dal.execute(
                "SELECT target_id as linked_id, target_database as linked_database, "
                "relationship_type FROM entity_links "
                "WHERE source_pk = ? AND source_entity_type = ? "
                "UNION "
                "SELECT source_id as linked_id, source_database as linked_database, "
                "relationship_type FROM entity_links "
                "WHERE target_pk = ? AND target_entity_type = ?",
                [entity_pk, entity_type, entity_pk, entity_type],
            )
            cross_links = [
                CrossLinkOut(
                    linked_id=r["linked_id"],
                    linked_database=r["linked_database"],
                    relationship_type=r["relationship_type"],
                )
                for r in result.rows
            ]
        except Exception as e:
            logger.warning("Failed to load cross-links: %s", e)

    # Download options
    download_opts = _resolver.resolve(entity_data, series_list, project_data)
    downloads = [
        DownloadOptionOut(
            file_type=d.file_type, label=d.label, url=d.url,
            instructions=d.instructions, source=d.source,
        )
        for d in download_opts
    ]

    title = (
        (project_data or {}).get("title")
        or entity_data.get("title")
        or entity_data.get("project_title")
    )

    return DatasetDetailResponse(
        entity_id=id_value,
        entity_type=entity_type,
        title=title,
        description=(project_data or entity_data).get("description"),
        organism=(project_data or entity_data).get("organism"),
        source_database=entity_data.get("source_database", ""),
        project=project_data,
        series=series_list,
        samples=samples,
        sample_count=sample_count,
        cross_links=cross_links,
        downloads=downloads,
        pmid=(project_data or {}).get("pmid") or entity_data.get("pmid"),
        doi=(project_data or {}).get("doi") or entity_data.get("doi"),
    )


def _clean_row(row: dict) -> dict:
    """Remove large internal fields from a row for API response."""
    exclude = {"raw_metadata", "raw_xml", "etl_source_file", "etl_loaded_at"}
    return {k: v for k, v in row.items() if k not in exclude}


def _detect_entity_type(id_value: str, data: dict) -> str:
    """Detect entity type from ID pattern or column presence."""
    id_upper = id_value.strip().upper()
    # ID-based detection
    if id_upper.startswith("GSE") or id_upper.startswith("PRJNA") or id_upper.startswith("E-"):
        return "project"
    if id_upper.startswith("SRP"):
        return "series"
    if id_upper.startswith("GSM") or id_upper.startswith("SRS") or id_upper.startswith("SAMN") or id_upper.startswith("SAME"):
        return "sample"
    # Column-based detection
    if "project_id" in data and "sample_id" not in data and "series_id" not in data:
        return "project"
    if "series_id" in data:
        return "series"
    if "sample_id" in data:
        return "sample"
    return "project"  # default
