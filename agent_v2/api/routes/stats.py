"""
System statistics route — uses precomputed stats tables for performance.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from api.schemas import StatsResponse
from api.deps import get_dal

if TYPE_CHECKING:
    from src.dal.database import DatabaseAbstractionLayer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["stats"])

# Dashboard cache (refreshes every 5 minutes)
_dashboard_cache: dict | None = None
_dashboard_cache_time: float = 0.0
DASHBOARD_CACHE_TTL = 300.0  # 5 minutes


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get database statistics overview using precomputed stats tables."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # 1. Totals from stats_overall (<1ms)
    totals: dict[str, int] = {}
    try:
        result = dal.execute("SELECT metric, value FROM stats_overall")
        totals = {r["metric"]: r["value"] for r in result.rows}
    except Exception as e:
        logger.warning("Failed to read stats_overall: %s", e)

    # 2. Source distribution from stats_by_source (<1ms)
    source_dbs = []
    try:
        result = dal.execute(
            "SELECT source_database, project_count, sample_count "
            "FROM stats_by_source ORDER BY sample_count DESC"
        )
        source_dbs = [
            {"name": r["source_database"], "project_count": r["project_count"],
             "sample_count": r["sample_count"]}
            for r in result.rows
        ]
    except Exception as e:
        logger.warning("Failed to get source stats: %s", e)

    # 3. Top tissues from stats_by_tissue (<1ms)
    top_tissues = []
    try:
        result = dal.execute(
            "SELECT tissue, sample_count FROM stats_by_tissue "
            "ORDER BY sample_count DESC LIMIT 15"
        )
        top_tissues = [{"value": r["tissue"], "count": r["sample_count"]}
                       for r in result.rows]
    except Exception as e:
        logger.warning("Failed to get tissue stats: %s", e)

    # 4. Top diseases from stats_by_disease (<1ms)
    top_diseases = []
    try:
        result = dal.execute(
            "SELECT disease, sample_count FROM stats_by_disease "
            "WHERE disease != 'normal' "
            "ORDER BY sample_count DESC LIMIT 15"
        )
        top_diseases = [{"value": r["disease"], "count": r["sample_count"]}
                        for r in result.rows]
    except Exception as e:
        logger.warning("Failed to get disease stats: %s", e)

    return StatsResponse(
        total_projects=totals.get("total_projects", 0),
        total_series=totals.get("total_series", 0),
        total_samples=totals.get("total_samples", 0),
        total_celltypes=totals.get("total_celltypes", 0),
        total_entity_links=totals.get("total_entity_links", 0),
        source_databases=source_dbs,
        top_tissues=top_tissues,
        top_diseases=top_diseases,
    )


@router.get("/stats/dashboard")
async def get_dashboard_stats():
    """Comprehensive statistics using precomputed stats tables."""
    global _dashboard_cache, _dashboard_cache_time

    # Return cached data if fresh
    if _dashboard_cache and (time.time() - _dashboard_cache_time) < DASHBOARD_CACHE_TTL:
        return _dashboard_cache

    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    data = _build_dashboard_data(dal)

    # Cache the result
    _dashboard_cache = data
    _dashboard_cache_time = time.time()

    return data


def _build_dashboard_data(dal: "DatabaseAbstractionLayer") -> dict:
    """Build dashboard data dict from precomputed stats tables."""
    # 1. Totals from stats_overall (<1ms)
    totals: dict[str, int] = {}
    try:
        result = dal.execute("SELECT metric, value FROM stats_overall")
        totals = {r["metric"]: r["value"] for r in result.rows}
    except Exception:
        pass

    data: dict = {
        "total_projects": totals.get("total_projects", 0),
        "total_series": totals.get("total_series", 0),
        "total_samples": totals.get("total_samples", 0),
        "total_celltypes": totals.get("total_celltypes", 0),
        "total_cross_links": totals.get("total_entity_links", 0),
    }

    # 2. By source — from stats_by_source (<1ms)
    try:
        result = dal.execute(
            "SELECT source_database as name, project_count as projects, "
            "series_count as series, sample_count as samples "
            "FROM stats_by_source ORDER BY samples DESC"
        )
        data["by_source"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_source"] = []

    # 3. By tissue — from stats_by_tissue (<1ms)
    try:
        result = dal.execute(
            "SELECT tissue as value, sample_count as count "
            "FROM stats_by_tissue ORDER BY sample_count DESC LIMIT 30"
        )
        data["by_tissue"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_tissue"] = []

    # 4. By disease — from stats_by_disease (<1ms)
    try:
        result = dal.execute(
            "SELECT disease as value, sample_count as count "
            "FROM stats_by_disease WHERE disease != 'normal' "
            "ORDER BY sample_count DESC LIMIT 30"
        )
        data["by_disease"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_disease"] = []

    # 5. By assay — from stats_by_assay (<1ms, no JOIN needed!)
    try:
        result = dal.execute(
            "SELECT assay as value, sample_count as count "
            "FROM stats_by_assay ORDER BY sample_count DESC LIMIT 20"
        )
        data["by_assay"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_assay"] = []

    # 6. By organism — from stats_by_organism (<1ms)
    try:
        result = dal.execute(
            "SELECT organism as value, sample_count as count "
            "FROM stats_by_organism ORDER BY sample_count DESC LIMIT 10"
        )
        data["by_organism"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_organism"] = []

    # 7. By sex — from stats_by_sex (<1ms)
    try:
        result = dal.execute(
            "SELECT sex as value, sample_count as count "
            "FROM stats_by_sex ORDER BY sample_count DESC"
        )
        data["by_sex"] = [dict(r) for r in result.rows]
    except Exception:
        data["by_sex"] = []

    # 8. Submissions by year — from stats_by_year (<1ms)
    try:
        result = dal.execute(
            "SELECT year, project_count as count "
            "FROM stats_by_year ORDER BY year"
        )
        data["submissions_by_year"] = [dict(r) for r in result.rows if r.get("year")]
    except Exception:
        data["submissions_by_year"] = []

    # 9. Data availability — from stats_overall (<1ms)
    data["h5ad_available"] = totals.get("h5ad_available", 0)
    data["rds_available"] = totals.get("rds_available", 0)
    data["with_pmid"] = totals.get("with_pmid", 0)
    data["with_doi"] = totals.get("with_doi", 0)

    return data


def prewarm_dashboard_cache(dal: "DatabaseAbstractionLayer"):
    """Pre-populate dashboard cache at startup (called from lifespan)."""
    global _dashboard_cache, _dashboard_cache_time
    t0 = time.perf_counter()
    _dashboard_cache = _build_dashboard_data(dal)
    _dashboard_cache_time = time.time()
    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("Dashboard cache pre-warmed in %.0fms", elapsed)
