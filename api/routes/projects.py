"""
Project-level search route — Phase 15B.

Counterpart to /scdbAPI/explore (which is sample-level). Searches the
unified_projects + unified_series tables — the right surface for
"project-only" sources that may carry project/series metadata without
per-sample rows. In the current curated catalog these tables hold 16,376
projects from 5 sources (NCBI, GEO, EGA, EBI, CellxGene) and 14,110
series from 3 sources (NCBI, GEO, CellxGene).

Endpoints:
    POST /scdbAPI/projects/search   FTS5 + facets over unified_projects
    POST /scdbAPI/series/search     FTS5 + facets over unified_series

Both accept the same shape (text_search + structured filters) so the
frontend can switch target_level without re-shaping its state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_dal
from api.services.fts5_util import safe_fts5_query
from api._text import fix_mojibake

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["project-search"])

# Process-wide cache for the unfiltered project / series landing page.
# Same rationale as the explore cache: ~3-5 s SQL → ~3 ms cache hit.
_PROJECT_CACHE: dict[tuple, Any] = {}
_PROJECT_LOCK = threading.Lock()
_SERIES_CACHE: dict[tuple, Any] = {}
_SERIES_LOCK = threading.Lock()


# ── Request / response models ──

class ProjectSearchRequest(BaseModel):
    text_search: str | None = Field(default=None, description="FTS5 query (title/description/organism)")
    source_databases: list[str] = []
    organisms: list[str] = []
    data_availability: str | None = None  # 'open' | 'controlled'
    years: list[str] = []  # publication years, e.g. ["2024","2025"]
    has_pmid: bool | None = None
    has_doi: bool | None = None
    published_after: str | None = None  # YYYY-MM-DD
    published_before: str | None = None
    min_sample_count: int | None = None
    min_total_cells: int | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)
    sort_by: str = "publication_date"
    sort_dir: str = "desc"


class ProjectRecord(BaseModel):
    project_pk: int
    project_id: str
    project_id_type: str | None = None
    source_database: str
    title: str | None = None
    description: str | None = None
    organism: str | None = None
    pmid: str | None = None
    doi: str | None = None
    journal: str | None = None
    publication_date: str | None = None
    citation_count: int | None = None
    sample_count: int | None = None
    total_cells: int | None = None
    access_url: str | None = None
    data_availability: str | None = None


class FacetBucket(BaseModel):
    value: str
    count: int


class ProjectSearchResponse(BaseModel):
    results: list[ProjectRecord] = []
    total_count: int = 0
    offset: int = 0
    limit: int = 25
    facets: dict[str, list[FacetBucket]] = {}
    elapsed_ms: float = 0.0


class SeriesSearchRequest(BaseModel):
    text_search: str | None = None
    source_databases: list[str] = []
    organisms: list[str] = []
    assays: list[str] = []
    assay_modalities: list[str] = []
    has_h5ad: bool | None = None
    has_rds: bool | None = None
    min_cell_count: int | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)
    sort_by: str = "cell_count"
    sort_dir: str = "desc"


class SeriesRecord(BaseModel):
    series_pk: int
    series_id: str
    source_database: str
    project_id: str | None = None
    title: str | None = None
    organism: str | None = None
    assay: str | None = None
    platform: str | None = None
    cell_count: int | None = None
    sample_count: int | None = None
    has_h5ad: bool = False
    has_rds: bool = False
    asset_h5ad_url: str | None = None
    asset_rds_url: str | None = None
    citation_count: int | None = None
    published_at: str | None = None


class SeriesSearchResponse(BaseModel):
    results: list[SeriesRecord] = []
    total_count: int = 0
    offset: int = 0
    limit: int = 25
    facets: dict[str, list[FacetBucket]] = {}
    elapsed_ms: float = 0.0


# ── Allowed sort columns ──

PROJECT_SORT_COLS = {
    "publication_date", "submission_date", "citation_count",
    "sample_count", "total_cells", "title",
}
SERIES_SORT_COLS = {
    "published_at", "cell_count", "sample_count", "citation_count",
    "title", "assay",
}


# ── Project search helpers ──

def _build_project_where(req: ProjectSearchRequest) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if req.text_search:
        safe_q = safe_fts5_query(req.text_search)
        if safe_q:
            clauses.append("p.pk IN (SELECT rowid FROM fts_projects WHERE fts_projects MATCH ?)")
            params.append(safe_q)

    if req.source_databases:
        ph = ",".join("?" * len(req.source_databases))
        clauses.append(f"p.source_database IN ({ph})")
        params.extend(req.source_databases)

    if req.organisms:
        # Phase 32 F20: filter on primary_organism (clean) instead of
        # raw `organism` (list-literal corruption affects ~5k rows).
        ph = ",".join("?" * len(req.organisms))
        clauses.append(f"p.primary_organism IN ({ph})")
        params.extend(req.organisms)

    if req.data_availability:
        clauses.append("p.data_availability = ?")
        params.append(req.data_availability)

    if req.years:
        ph = ",".join("?" * len(req.years))
        clauses.append(f"substr(p.publication_date,1,4) IN ({ph})")
        params.extend(req.years)

    if req.has_pmid is True:
        clauses.append("p.pmid IS NOT NULL AND p.pmid != ''")
    elif req.has_pmid is False:
        clauses.append("(p.pmid IS NULL OR p.pmid = '')")

    if req.has_doi is True:
        clauses.append("p.doi IS NOT NULL AND p.doi != ''")
    elif req.has_doi is False:
        clauses.append("(p.doi IS NULL OR p.doi = '')")

    if req.published_after:
        clauses.append("p.publication_date >= ?")
        params.append(req.published_after)
    if req.published_before:
        clauses.append("p.publication_date <= ?")
        params.append(req.published_before)

    if req.min_sample_count is not None:
        clauses.append("p.sample_count >= ?")
        params.append(req.min_sample_count)
    if req.min_total_cells is not None:
        clauses.append("p.total_cells >= ?")
        params.append(req.min_total_cells)

    return clauses, params


def _project_facets(dal, where_clauses: list[str], where_params: list) -> dict[str, list[FacetBucket]]:
    """Compute facets over the filtered project set."""
    base_where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    facets: dict[str, list[FacetBucket]] = {}

    # Phase 32 F20: `unified_projects.organism` is corrupted in ~5,389 rows
    # (stores Python list literal "['Homo sapiens', 'Mus musculus']" verbatim
    # because some upstream ETL paths serialised a list with str()). The clean
    # column is `primary_organism` (always one species). Use that for facets
    # so the sidebar no longer shows entries like "['Pan troglodytes', 'Homo
    # sapiens']" with count=6.
    # Phase 40 O2-A: project tier was under-faceted (only 3) despite rich
    # columns. Add publication `year` (76% coverage — surface as a discovery
    # dimension; remaining 24% have no publication_date) and `data_availability`
    # (open vs controlled access) so the UI/agent can filter on them.
    facet_cols = [
        ("source_database", "p.source_database", "DESC"),
        ("organism", "p.primary_organism", "DESC"),
        ("journal", "p.journal", "DESC"),
        ("data_availability", "p.data_availability", "DESC"),
        ("year", "substr(p.publication_date,1,4)", "VALUE"),  # newest year first
    ]
    for name, col, order in facet_cols:
        order_sql = "value DESC" if order == "VALUE" else "cnt DESC"
        try:
            result = dal.execute(
                f"SELECT {col} as value, COUNT(*) as cnt "
                f"FROM unified_projects p {base_where} "
                f"{('AND ' if base_where else 'WHERE ')}{col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY {order_sql} LIMIT 30",
                where_params,
            )
            facets[name] = [
                FacetBucket(value=str(r["value"]), count=r["cnt"])
                for r in result.rows
            ]
        except Exception as e:
            logger.warning("Project facet %s failed: %s", name, e)
            facets[name] = []

    return facets


def _is_empty_project_req(req: ProjectSearchRequest) -> bool:
    return (
        not req.text_search and not req.source_databases and not req.organisms
        and not req.data_availability and not req.years
        and req.has_pmid is None and req.has_doi is None
        and not req.published_after and not req.published_before
        and req.min_sample_count is None and req.min_total_cells is None
    )


@router.post("/projects/search", response_model=ProjectSearchResponse)
async def search_projects(req: ProjectSearchRequest):
    """FTS5 + structured search over unified_projects (16,376 projects from 5 sources: NCBI, GEO, EGA, EBI, CellxGene)."""
    t0 = time.perf_counter()
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_project_req(req)
    if is_unfiltered:
        key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _PROJECT_LOCK:
            cached = _PROJECT_CACHE.get(key)
        if cached is not None:
            return cached

    where_clauses, where_params = _build_project_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Count
    count_result = dal.execute(
        f"SELECT COUNT(*) as cnt FROM unified_projects p {where_sql}",
        where_params,
    )
    total = count_result.rows[0]["cnt"] if count_result.rows else 0

    sort_col = req.sort_by if req.sort_by in PROJECT_SORT_COLS else "publication_date"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"

    # Phase 32 F20: SELECT primary_organism (clean) as `organism`. The
    # row-shape stays the same so the frontend code is unchanged; the
    # value just becomes "Homo sapiens" / "Mus musculus" instead of the
    # raw list-literal "['Homo sapiens', 'Mus musculus']".
    main_sql = f"""
SELECT
    p.pk as project_pk, p.project_id, p.project_id_type, p.source_database,
    p.title, p.description,
    COALESCE(p.primary_organism, p.organism) as organism,
    p.organism_list,
    p.pmid, p.doi, p.journal,
    p.publication_date, p.citation_count, p.sample_count, p.total_cells,
    p.access_url, p.data_availability
FROM unified_projects p
{where_sql}
ORDER BY p.{sort_col} {sort_dir} NULLS LAST
LIMIT ? OFFSET ?
"""
    main_result = dal.execute(main_sql, where_params + [req.limit, req.offset])

    records = [
        ProjectRecord(
            project_pk=r["project_pk"],
            project_id=r["project_id"],
            project_id_type=r.get("project_id_type"),
            source_database=r["source_database"],
            title=fix_mojibake(r.get("title")),
            description=fix_mojibake((r.get("description") or "")[:600] or None),
            organism=r.get("organism"),
            pmid=r.get("pmid"),
            doi=r.get("doi"),
            journal=r.get("journal"),
            publication_date=r.get("publication_date"),
            citation_count=r.get("citation_count"),
            sample_count=r.get("sample_count"),
            total_cells=r.get("total_cells"),
            access_url=r.get("access_url"),
            data_availability=r.get("data_availability"),
        )
        for r in main_result.rows
    ]

    facets = _project_facets(dal, where_clauses, where_params)

    elapsed = (time.perf_counter() - t0) * 1000
    resp = ProjectSearchResponse(
        results=records,
        total_count=total,
        offset=req.offset,
        limit=req.limit,
        facets=facets,
        elapsed_ms=round(elapsed, 1),
    )

    if is_unfiltered:
        key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _PROJECT_LOCK:
            _PROJECT_CACHE[key] = resp

    return resp


# ── Series search ──

def _build_series_where(req: SeriesSearchRequest) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if req.text_search:
        safe_q = safe_fts5_query(req.text_search)
        if safe_q:
            clauses.append("sr.pk IN (SELECT rowid FROM fts_series WHERE fts_series MATCH ?)")
            params.append(safe_q)

    if req.source_databases:
        ph = ",".join("?" * len(req.source_databases))
        clauses.append(f"sr.source_database IN ({ph})")
        params.extend(req.source_databases)

    if req.organisms:
        # Phase 32 F20: use clean primary_organism for filtering.
        ph = ",".join("?" * len(req.organisms))
        clauses.append(f"sr.primary_organism IN ({ph})")
        params.extend(req.organisms)

    if req.assays:
        ph = ",".join("?" * len(req.assays))
        clauses.append(f"sr.assay IN ({ph})")
        params.extend(req.assays)

    if req.assay_modalities:
        ph = ",".join("?" * len(req.assay_modalities))
        clauses.append(f"sr.assay_modality IN ({ph})")
        params.extend(req.assay_modalities)

    if req.has_h5ad is True:
        clauses.append("sr.has_h5ad = 1")
    elif req.has_h5ad is False:
        clauses.append("(sr.has_h5ad IS NULL OR sr.has_h5ad = 0)")

    if req.has_rds is True:
        clauses.append("sr.has_rds = 1")

    if req.min_cell_count is not None:
        clauses.append("sr.cell_count >= ?")
        params.append(req.min_cell_count)

    return clauses, params


def _series_facets(dal, where_clauses: list[str], where_params: list) -> dict[str, list[FacetBucket]]:
    base_where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    facets: dict[str, list[FacetBucket]] = {}

    # Phase 32 F20: same fix as for projects — sr.organism has the same
    # list-literal corruption (5,389 rows). Use the clean primary_organism.
    # Phase 40 O2-A: add assay_modality (curated single-cell modality — low
    # coverage, populated mainly for CellxGene-derived series) as a discovery
    # dimension alongside the existing source/organism/assay/platform.
    facet_cols = [
        ("source_database", "sr.source_database"),
        ("organism", "sr.primary_organism"),
        ("assay", "sr.assay"),
        ("assay_modality", "sr.assay_modality"),
        ("platform", "sr.platform"),
    ]
    for name, col in facet_cols:
        try:
            result = dal.execute(
                f"SELECT {col} as value, COUNT(*) as cnt "
                f"FROM unified_series sr {base_where} "
                f"{('AND ' if base_where else 'WHERE ')}{col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY cnt DESC LIMIT 30",
                where_params,
            )
            facets[name] = [
                FacetBucket(value=str(r["value"]), count=r["cnt"])
                for r in result.rows
            ]
        except Exception as e:
            logger.warning("Series facet %s failed: %s", name, e)
            facets[name] = []

    # data_format: analysis-ready asset availability, well-defined for ALL rows
    # (lets a user filter to "series with a downloadable h5ad / rds matrix").
    try:
        result = dal.execute(
            "SELECT CASE WHEN sr.has_h5ad=1 THEN 'h5ad' WHEN sr.has_rds=1 THEN 'rds' "
            "ELSE 'raw/links only' END as value, COUNT(*) as cnt "
            f"FROM unified_series sr {base_where} "
            "GROUP BY value ORDER BY cnt DESC",
            where_params,
        )
        facets["data_format"] = [
            FacetBucket(value=str(r["value"]), count=r["cnt"]) for r in result.rows
        ]
    except Exception as e:
        logger.warning("Series facet data_format failed: %s", e)
        facets["data_format"] = []

    return facets


def _is_empty_series_req(req: SeriesSearchRequest) -> bool:
    return (
        not req.text_search and not req.source_databases and not req.organisms
        and not req.assays and not req.assay_modalities
        and req.has_h5ad is None and req.has_rds is None
        and req.min_cell_count is None
    )


@router.post("/series/search", response_model=SeriesSearchResponse)
async def search_series(req: SeriesSearchRequest):
    """FTS5 + structured search over unified_series."""
    t0 = time.perf_counter()
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_series_req(req)
    if is_unfiltered:
        key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _SERIES_LOCK:
            cached = _SERIES_CACHE.get(key)
        if cached is not None:
            return cached

    where_clauses, where_params = _build_series_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_result = dal.execute(
        f"SELECT COUNT(*) as cnt FROM unified_series sr {where_sql}",
        where_params,
    )
    total = count_result.rows[0]["cnt"] if count_result.rows else 0

    sort_col = req.sort_by if req.sort_by in SERIES_SORT_COLS else "cell_count"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"

    # Phase 32 F20: prefer primary_organism over raw organism for series too.
    main_sql = f"""
SELECT
    sr.pk as series_pk, sr.series_id, sr.source_database, sr.project_id,
    sr.title,
    COALESCE(sr.primary_organism, sr.organism) as organism,
    sr.organism_list,
    sr.assay, sr.platform,
    sr.cell_count, sr.sample_count, sr.has_h5ad, sr.has_rds,
    sr.asset_h5ad_url, sr.asset_rds_url, sr.citation_count, sr.published_at
FROM unified_series sr
{where_sql}
ORDER BY sr.{sort_col} {sort_dir} NULLS LAST
LIMIT ? OFFSET ?
"""
    main_result = dal.execute(main_sql, where_params + [req.limit, req.offset])

    records = [
        SeriesRecord(
            series_pk=r["series_pk"],
            series_id=r["series_id"],
            source_database=r["source_database"],
            project_id=r.get("project_id"),
            title=fix_mojibake(r.get("title")),
            organism=r.get("organism"),
            assay=r.get("assay"),
            platform=r.get("platform"),
            cell_count=r.get("cell_count"),
            sample_count=r.get("sample_count"),
            has_h5ad=bool(r.get("has_h5ad")),
            has_rds=bool(r.get("has_rds")),
            asset_h5ad_url=r.get("asset_h5ad_url"),
            asset_rds_url=r.get("asset_rds_url"),
            citation_count=r.get("citation_count"),
            published_at=r.get("published_at"),
        )
        for r in main_result.rows
    ]

    facets = _series_facets(dal, where_clauses, where_params)

    elapsed = (time.perf_counter() - t0) * 1000
    resp = SeriesSearchResponse(
        results=records,
        total_count=total,
        offset=req.offset,
        limit=req.limit,
        facets=facets,
        elapsed_ms=round(elapsed, 1),
    )

    if is_unfiltered:
        key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _SERIES_LOCK:
            _SERIES_CACHE[key] = resp

    return resp


def prewarm_projects_series() -> None:
    """Pre-warm the unfiltered default landing for /projects and /series.
    Frontend uses limit=25, offset=0, default sort. Hit offsets 0 + 25."""
    try:
        import asyncio
        for offset in (0, 25):
            asyncio.run(search_projects(ProjectSearchRequest(limit=25, offset=offset)))
            asyncio.run(search_series(SeriesSearchRequest(limit=25, offset=offset)))
    except Exception as e:
        logger.warning("projects/series prewarm failed: %s", e)


# ── Stats ──

@router.get("/projects/stats_by_source")
async def projects_stats_by_source():
    """Project & series counts per source — covers the curated catalog's project/series sources (sample-level + project-only)."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Project counts
    proj_result = dal.execute(
        "SELECT source_database, COUNT(*) as cnt, "
        "SUM(COALESCE(sample_count, 0)) as samples_in_proj, "
        "SUM(COALESCE(total_cells, 0)) as cells_in_proj "
        "FROM unified_projects GROUP BY source_database ORDER BY cnt DESC"
    )
    by_source: dict[str, dict] = {}
    for r in proj_result.rows:
        by_source[r["source_database"]] = {
            "source_database": r["source_database"],
            "project_count": r["cnt"],
            "samples_reported_in_projects": r["samples_in_proj"] or 0,
            "cells_reported_in_projects": r["cells_in_proj"] or 0,
            "series_count": 0,
            "sample_count": 0,
        }

    # Series counts
    try:
        sr_result = dal.execute(
            "SELECT source_database, COUNT(*) as cnt FROM unified_series GROUP BY source_database"
        )
        for r in sr_result.rows:
            src = r["source_database"]
            if src in by_source:
                by_source[src]["series_count"] = r["cnt"]
            else:
                by_source[src] = {
                    "source_database": src, "project_count": 0,
                    "series_count": r["cnt"], "sample_count": 0,
                    "samples_reported_in_projects": 0, "cells_reported_in_projects": 0,
                }
    except Exception:
        pass

    # Sample counts (from precomputed stats_by_source)
    try:
        s_result = dal.execute(
            "SELECT source_database, sample_count FROM stats_by_source"
        )
        for r in s_result.rows:
            src = r["source_database"]
            if src in by_source:
                by_source[src]["sample_count"] = r["sample_count"]
            else:
                by_source[src] = {
                    "source_database": src, "project_count": 0,
                    "series_count": 0, "sample_count": r["sample_count"],
                    "samples_reported_in_projects": 0, "cells_reported_in_projects": 0,
                }
    except Exception:
        pass

    rows = sorted(by_source.values(), key=lambda x: -x["project_count"])
    return {"sources": rows, "total_sources": len(rows)}
