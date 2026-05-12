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


# Cache for the standard-column top-N (Phase 34: now a cheap GROUP BY, but we
# still memoise per-process so repeat landings are sub-ms).
_TOP_N_CACHE: dict[tuple[str, int, frozenset], tuple[float, list[dict]]] = {}
_TOP_N_TTL = 300.0  # 5 minutes


def _fold_case_stats(
    dal,
    col: str,
    limit: int = 15,
    exclude_values: set[str] | None = None,
) -> list[dict]:
    """Top-N values for `col` from the curated ``{col}_standard`` column, so
    /stats agrees with the explore facets (which also use *_standard) and the
    NL→SQL aggregation path.

    Phase 34: replaced the previous on-the-fly case-fold over the raw column (a
    943k-row scan + window function, ~1.8s) with a plain GROUP BY on the
    pre-standardised column (~35ms, 50x faster) — the standardisation already
    case-folds ("Peripheral blood"→"peripheral blood") and strips ontology IDs.
    """
    std_col = f"{col}_standard"
    key = (std_col, limit, frozenset(exclude_values or set()))
    now = time.time()
    cached = _TOP_N_CACHE.get(key)
    if cached and (now - cached[0]) < _TOP_N_TTL:
        return cached[1]

    try:
        exclude_clause = ""
        params: list = []
        if exclude_values:
            placeholders = ",".join("?" for _ in exclude_values)
            exclude_clause = (
                f" AND LOWER(TRIM(s.{std_col})) NOT IN ({placeholders})"
            )
            params.extend(v.lower() for v in exclude_values)

        sql = f"""
            SELECT s.{std_col} AS display, COUNT(*) AS total
            FROM unified_samples s
            WHERE s.{std_col} IS NOT NULL AND s.{std_col} != ''
              {exclude_clause}
            GROUP BY s.{std_col}
            ORDER BY total DESC
            LIMIT ?
        """
        params.append(limit)
        result = dal.execute(sql, params)
        out = [
            {"value": r["display"], "count": r["total"]}
            for r in result.rows
            if r["display"]
        ]
        _TOP_N_CACHE[key] = (now, out)
        return out
    except Exception as e:
        logger.warning("Standard-column stats for %s failed: %s", col, e)
        return []

# Live-COUNT fallbacks for the 4 "Data availability" tiles. The upstream
# DB build pipeline is meant to insert these into stats_overall, but in
# checkouts where it hasn't run we still want non-zero numerators on the
# Stats dashboard rather than the misleading "0.0% of 16K" rendering.
# The query is cheap (single COUNT, one indexed column) and only runs
# once per 5-min cache window.
#
# Column locations (verified Phase 28 QA against the live human DB):
#   * unified_series.asset_h5ad_url   (1086/14110 non-null)
#   * unified_series.asset_rds_url    (0/14110 non-null in current build)
#   * unified_projects.pmid           (9826/16376 non-null)
#   * unified_projects.doi            (5790/16376 non-null)
_DATA_AVAILABILITY_FALLBACKS = {
    "h5ad_available": (
        "SELECT COUNT(*) AS c FROM unified_series "
        "WHERE asset_h5ad_url IS NOT NULL AND asset_h5ad_url != ''"
    ),
    "rds_available": (
        "SELECT COUNT(*) AS c FROM unified_series "
        "WHERE asset_rds_url IS NOT NULL AND asset_rds_url != ''"
    ),
    "with_pmid": (
        "SELECT COUNT(*) AS c FROM unified_projects "
        "WHERE pmid IS NOT NULL AND pmid != ''"
    ),
    "with_doi": (
        "SELECT COUNT(*) AS c FROM unified_projects "
        "WHERE doi IS NOT NULL AND doi != ''"
    ),
}


def _safe_count(dal: "DatabaseAbstractionLayer", sql: str) -> int:
    """Run a COUNT(*) query, returning 0 on any error or missing column."""
    try:
        r = dal.execute(sql)
        if r.rows:
            return int(r.rows[0].get("c") or 0)
    except Exception as e:
        logger.warning("data_availability_fallback_failed sql=%r err=%s", sql, e)
    return 0


def _safe_dict_rows(
    dal: "DatabaseAbstractionLayer",
    sql: str,
    *,
    filter_truthy_key: str | None = None,
    section: str = "?",
    fallback_sql: str | None = None,
) -> list[dict]:
    """Run a SELECT, returning rows as dicts; on failure return [] and log.

    Replaces ~10 copies of the same `try: ... ; except Exception: data[...] = []`
    block in `_build_dashboard_data`. Centralising the catch means precompute-
    table-missing failures are visible in the warning log instead of silently
    showing empty charts.

    If the primary query returns zero rows AND a ``fallback_sql`` is given,
    we run the fallback (typically a live GROUP BY against unified_*). This
    keeps the dashboard populated when the precompute pipeline hasn't been
    re-run after a DB rebuild.
    """
    def _run(q: str) -> list[dict]:
        res = dal.execute(q)
        if filter_truthy_key is None:
            return [dict(r) for r in res.rows]
        return [dict(r) for r in res.rows if r.get(filter_truthy_key)]

    try:
        rows = _run(sql)
        if rows or not fallback_sql:
            return rows
    except Exception as e:
        logger.warning(
            "dashboard_section_failed section=%s primary_err=%s", section, e
        )

    if fallback_sql:
        try:
            return _run(fallback_sql)
        except Exception as e:
            logger.warning(
                "dashboard_section_fallback_failed section=%s err=%s", section, e
            )
    return []


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

    # top_tissues / top_diseases from the curated *_standard columns so this
    # endpoint agrees with the explore facets and the NL→SQL aggregation path.
    top_tissues = _fold_case_stats(dal, "tissue", limit=15)
    top_diseases = _fold_case_stats(
        dal, "disease", limit=15, exclude_values={"normal"}
    )

    # Distinct standardized cell types (336) — NOT the annotation-row count in
    # stats_overall.total_celltypes (378k). Keep this consistent with /celltypes.
    try:
        _ct = dal.execute(
            "SELECT COUNT(DISTINCT cell_type_standard) AS n FROM unified_samples "
            "WHERE cell_type_standard IS NOT NULL AND cell_type_standard != ''"
        )
        total_celltypes = _ct.rows[0]["n"] if _ct.rows else 0
    except Exception:  # noqa: BLE001
        total_celltypes = totals.get("total_celltypes", 0)

    return StatsResponse(
        total_projects=totals.get("total_projects", 0),
        total_series=totals.get("total_series", 0),
        total_samples=totals.get("total_samples", 0),
        total_celltypes=total_celltypes,
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
    """Build dashboard data dict from precomputed stats tables.

    Every section query is wrapped in `_safe_dict_rows` (or `_safe_count`
    for the availability tiles), so a missing/renamed precompute table
    only nukes its own chart and is logged as a warning — instead of
    silently rendering empty.
    """
    # 1. Totals from stats_overall (<1ms)
    totals: dict[str, int] = {}
    try:
        result = dal.execute("SELECT metric, value FROM stats_overall")
        totals = {r["metric"]: r["value"] for r in result.rows}
    except Exception as e:
        logger.warning("dashboard_section_failed section=totals err=%s", e)

    data: dict = {
        "total_projects": totals.get("total_projects", 0),
        "total_series": totals.get("total_series", 0),
        "total_samples": totals.get("total_samples", 0),
        # NB: stats_overall.total_celltypes counts ANNOTATION rows (378k = one per
        # sample×label), NOT distinct cell types — showing it under "Cell types"
        # was misleading (the /celltypes page shows 336). Report the DISTINCT
        # standardized count here; keep the annotation volume as its own field.
        "total_celltype_annotations": totals.get("total_celltypes", 0),
        "total_cross_links": totals.get("total_entity_links", 0),
        "total_sources": totals.get("total_sources", totals.get("source_databases", 0)),
    }

    # Distinct standardized cell types — must match the /celltypes page (336),
    # computed the same way (COUNT(DISTINCT cell_type_standard)).
    try:
        r = dal.execute(
            "SELECT COUNT(DISTINCT cell_type_standard) AS n FROM unified_samples "
            "WHERE cell_type_standard IS NOT NULL AND cell_type_standard != ''"
        )
        data["total_celltypes"] = r.rows[0]["n"] if r.rows else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard_section_failed section=celltypes err=%s", e)
        data["total_celltypes"] = 0

    # Phase 41 (U1): distinct donor/individual count — the power / pseudo-
    # replication signal researchers need (and most portals omit). Live
    # COUNT(DISTINCT) (~1s) but the whole dashboard is cached, so it's paid once.
    try:
        r = dal.execute(
            "SELECT COUNT(DISTINCT individual_id_namespaced) AS n "
            "FROM unified_samples WHERE individual_id_namespaced IS NOT NULL "
            "AND individual_id_namespaced != ''"
        )
        data["total_donors"] = r.rows[0]["n"] if r.rows else 0
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard_section_failed section=donors err=%s", e)
        data["total_donors"] = 0

    data["by_source"] = _safe_dict_rows(
        dal,
        "SELECT source_database as name, project_count as projects, "
        "series_count as series, sample_count as samples "
        "FROM stats_by_source ORDER BY samples DESC",
        section="by_source",
        fallback_sql=(
            "SELECT source_database as name, "
            "COUNT(DISTINCT project_id) as projects, "
            "COUNT(DISTINCT series_pk) as series, "
            "COUNT(*) as samples "
            "FROM unified_samples WHERE source_database IS NOT NULL "
            "GROUP BY source_database ORDER BY samples DESC"
        ),
    )
    # Phase 34: group by the curated *_standard columns, not the precomputed
    # stats_by_tissue / stats_by_disease tables. Those tables stored RAW buckets
    # — "blood" and "Blood" as separate rows, bare ontology IDs (EFO_xxxx),
    # "colorectal cancer spheroid cell line" — which made the Stats dashboard
    # disagree with both the /stats top-N tiles and the explore facets.
    data["by_tissue"] = _safe_dict_rows(
        dal,
        "SELECT tissue_standard as value, COUNT(*) as count "
        "FROM unified_samples WHERE tissue_standard IS NOT NULL "
        "AND tissue_standard != '' "
        "GROUP BY tissue_standard ORDER BY count DESC LIMIT 30",
        section="by_tissue",
    )
    data["by_disease"] = _safe_dict_rows(
        dal,
        "SELECT disease_standard as value, COUNT(*) as count "
        "FROM unified_samples WHERE disease_standard IS NOT NULL "
        "AND disease_standard != '' AND disease_standard != 'normal' "
        "GROUP BY disease_standard ORDER BY count DESC LIMIT 30",
        section="by_disease",
    )
    # Audit F19: `assay` lives on unified_series, not unified_samples — the old
    # fallback queried a non-existent column and would raise (dead code). The
    # assay annotation is sparse (~3.6% of samples; CellXGene-only ETL coverage),
    # so the live fallback joins through the series to match the precompute.
    data["by_assay"] = _safe_dict_rows(
        dal,
        "SELECT assay as value, sample_count as count "
        "FROM stats_by_assay ORDER BY sample_count DESC LIMIT 20",
        section="by_assay",
        fallback_sql=(
            "SELECT sr.assay as value, COUNT(*) as count "
            "FROM unified_samples s JOIN unified_series sr ON s.series_pk = sr.pk "
            "WHERE sr.assay IS NOT NULL AND sr.assay != '' "
            "GROUP BY sr.assay ORDER BY count DESC LIMIT 20"
        ),
    )
    data["by_organism"] = _safe_dict_rows(
        dal,
        "SELECT organism as value, sample_count as count "
        "FROM stats_by_organism ORDER BY sample_count DESC LIMIT 10",
        section="by_organism",
        fallback_sql=(
            "SELECT organism as value, COUNT(*) as count FROM unified_samples "
            "WHERE organism IS NOT NULL AND organism != '' "
            "GROUP BY organism ORDER BY count DESC LIMIT 10"
        ),
    )
    data["by_sex"] = _safe_dict_rows(
        dal,
        "SELECT sex as value, sample_count as count "
        "FROM stats_by_sex ORDER BY sample_count DESC",
        section="by_sex",
        fallback_sql=(
            "SELECT sex as value, COUNT(*) as count FROM unified_samples "
            "WHERE sex IS NOT NULL AND sex != '' "
            "GROUP BY sex ORDER BY count DESC"
        ),
    )
    data["submissions_by_year"] = _safe_dict_rows(
        dal,
        # stats_by_year stores per-year project (submission) counts —
        # the column is project_count, not sample_count. Aligned with
        # the fallback which COUNT(*)s unified_projects.publication_date.
        "SELECT year, project_count as count "
        "FROM stats_by_year ORDER BY year",
        filter_truthy_key="year",
        section="submissions_by_year",
        fallback_sql=(
            # Live: bucket by publication year from project metadata.
            "SELECT substr(publication_date, 1, 4) as year, COUNT(*) as count "
            "FROM unified_projects WHERE publication_date IS NOT NULL "
            "AND length(publication_date) >= 4 "
            "GROUP BY year HAVING year >= '2000' ORDER BY year"
        ),
    )

    # Data availability — see Phase 28 bug #3 for the fallback rationale.
    for metric_key, fallback_sql in _DATA_AVAILABILITY_FALLBACKS.items():
        v = totals.get(metric_key)
        if v is None or v == 0:
            v = _safe_count(dal, fallback_sql)
        data[metric_key] = v

    # Audit F4/F8/F9 (Phase 36): these three charts were served from precompute
    # tables that drifted badly stale (e.g. by_sample_type summed to 756,579 vs
    # the live 943,732) AND whose slices deep-link to /explore — which computes
    # live from the same standardized column, so a stale chart showed a different
    # number than the page it links to. Compute them live for consistency.
    data["by_tissue_system"] = _safe_dict_rows(
        dal,
        "SELECT tissue_system as value, COUNT(*) as count FROM unified_samples "
        "WHERE tissue_system IS NOT NULL AND tissue_system != '' "
        "GROUP BY tissue_system ORDER BY count DESC",
        filter_truthy_key="value",
        section="by_tissue_system",
    )
    data["by_disease_category"] = _safe_dict_rows(
        dal,
        "SELECT disease_category as value, COUNT(*) as count FROM unified_samples "
        "WHERE disease_category IS NOT NULL AND disease_category != '' "
        "GROUP BY disease_category ORDER BY count DESC",
        filter_truthy_key="value",
        section="by_disease_category",
    )
    data["by_sample_type"] = _safe_dict_rows(
        dal,
        "SELECT sample_type as value, COUNT(*) as count FROM unified_samples "
        "WHERE sample_type IS NOT NULL AND sample_type != '' "
        "GROUP BY sample_type ORDER BY count DESC",
        filter_truthy_key="value",
        section="by_sample_type",
    )

    return data


def prewarm_dashboard_cache(dal: "DatabaseAbstractionLayer"):
    """Pre-populate dashboard cache at startup (called from lifespan)."""
    global _dashboard_cache, _dashboard_cache_time
    t0 = time.perf_counter()
    _dashboard_cache = _build_dashboard_data(dal)
    _dashboard_cache_time = time.time()
    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("Dashboard cache pre-warmed in %.0fms", elapsed)
