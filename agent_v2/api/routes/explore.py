"""
Faceted explore route — 高性能版本

关键优化：
1. 利用 idx_samples_n_cells_covering 覆盖索引
2. 无过滤查询直接走预计算 facets
3. 简化查询结构，避免不必要的子查询
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_dal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["explore"])


class ExploreRequest(BaseModel):
    tissues: list[str] = []
    diseases: list[str] = []
    organisms: list[str] = []
    assays: list[str] = []
    cell_types: list[str] = []
    source_databases: list[str] = []
    sex: str | None = None
    min_cells: int | None = None
    has_h5ad: bool | None = None
    text_search: str | None = None
    nl_query: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)
    sort_by: str = "n_cells"
    sort_dir: str = "desc"


class FacetBucket(BaseModel):
    value: str
    count: int


class ExploreRecord(BaseModel):
    sample_pk: int
    sample_id: str
    tissue: str | None = None
    disease: str | None = None
    cell_type: str | None = None
    organism: str | None = None
    sex: str | None = None
    n_cells: int | None = None
    assay: str | None = None
    source_database: str = ""
    series_id: str | None = None
    series_title: str | None = None
    has_h5ad: bool = False
    project_id: str | None = None
    project_title: str | None = None
    pmid: str | None = None


class ExploreResponse(BaseModel):
    results: list[ExploreRecord] = []
    total_count: int = 0
    offset: int = 0
    limit: int = 25
    facets: dict[str, list[FacetBucket]] = {}


ALLOWED_SORT = {
    "n_cells", "tissue", "disease", "assay", "organism",
    "source_database", "project_title", "sample_id", "sex",
}

FACET_FIELDS = {
    "tissue": ("s", "tissue"),
    "disease": ("s", "disease"),
    "organism": ("s", "organism"),
    "source_database": ("s", "source_database"),
    "sex": ("s", "sex"),
    "cell_type": ("s", "cell_type"),
    "assay": ("sr", "assay"),
}

PRECOMPUTED_FACETS = {
    "tissue": ("stats_by_tissue", "tissue", "sample_count"),
    "disease": ("stats_by_disease", "disease", "sample_count"),
    "organism": ("stats_by_organism", "organism", "sample_count"),
    "source_database": ("stats_by_source", "source_database", "sample_count"),
    "sex": ("stats_by_sex", "sex", "sample_count"),
    "assay": ("stats_by_assay", "assay", "sample_count"),
    "cell_type": ("stats_by_cell_type", "cell_type", "sample_count"),
}

# 启动时预加载的缓存
_unfiltered_facets: dict[str, list[FacetBucket]] | None = None
_unfiltered_total: int = 0


def _is_empty_filter(req: ExploreRequest) -> bool:
    return (
        not req.tissues and not req.diseases and not req.organisms
        and not req.assays and not req.cell_types and not req.source_databases
        and not req.sex and req.min_cells is None
        and not req.has_h5ad and not req.text_search and not req.nl_query
    )


def _build_where(req: ExploreRequest) -> tuple[list[str], list[Any]]:
    """Build WHERE clauses for unified_samples table."""
    clauses: list[str] = []
    params: list[Any] = []

    if req.tissues:
        placeholders = ",".join("?" for _ in req.tissues)
        clauses.append(f"s.tissue IN ({placeholders})")
        params.extend(req.tissues)

    if req.diseases:
        placeholders = ",".join("?" for _ in req.diseases)
        clauses.append(f"s.disease IN ({placeholders})")
        params.extend(req.diseases)

    if req.organisms:
        placeholders = ",".join("?" for _ in req.organisms)
        clauses.append(f"s.organism IN ({placeholders})")
        params.extend(req.organisms)

    if req.cell_types:
        placeholders = ",".join("?" for _ in req.cell_types)
        clauses.append(f"s.cell_type IN ({placeholders})")
        params.extend(req.cell_types)

    if req.source_databases:
        placeholders = ",".join("?" for _ in req.source_databases)
        clauses.append(f"s.source_database IN ({placeholders})")
        params.extend(req.source_databases)

    if req.sex:
        clauses.append("s.sex = ?")
        params.append(req.sex)

    if req.min_cells is not None:
        clauses.append("s.n_cells >= ?")
        params.append(req.min_cells)

    if req.text_search:
        clauses.append("s.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)")
        params.append(req.text_search)

    return clauses, params


def _load_precomputed_facets(dal):
    """Load all facets from precomputed stats tables (runs once at startup)."""
    facets: dict[str, list[FacetBucket]] = {}
    
    for field_name, (table, col, count_col) in PRECOMPUTED_FACETS.items():
        try:
            result = dal.execute(
                f"SELECT {col} as value, {count_col} as count FROM {table} "
                f"WHERE {col} IS NOT NULL ORDER BY {count_col} DESC LIMIT 30"
            )
            facets[field_name] = [
                FacetBucket(value=r["value"], count=r["count"]) 
                for r in result.rows if r["value"]
            ]
        except Exception as e:
            logger.warning("Precomputed facet %s failed: %s", field_name, e)
            facets[field_name] = []
    
    # Get total from precomputed stats
    total = 0
    try:
        result = dal.execute("SELECT value FROM stats_overall WHERE metric = 'total_samples'")
        total = result.rows[0]["value"] if result.rows else 0
    except Exception:
        pass
    
    return facets, total


def _ensure_facets_loaded(dal):
    """Ensure facets are loaded (lazy initialization)."""
    global _unfiltered_facets, _unfiltered_total
    if _unfiltered_facets is None:
        t0 = logging.time.time() if hasattr(logging, 'time') else __import__('time').time()
        _unfiltered_facets, _unfiltered_total = _load_precomputed_facets(dal)
        t1 = __import__('time').time()
        logger.info(f"Facets loaded in {(t1-t0)*1000:.0f}ms")


@router.post("/explore", response_model=ExploreResponse)
async def explore(req: ExploreRequest):
    import time
    t0 = time.perf_counter()
    
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)
    
    # Handle facets and count
    if is_unfiltered:
        _ensure_facets_loaded(dal)
        facets = _unfiltered_facets
        total_count = _unfiltered_total
    else:
        facets = {}  # Skip facets for filtered queries
        where_clauses, where_params = _build_where(req)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        # Fast count for filtered queries
        count_sql = f"SELECT COUNT(*) as cnt FROM unified_samples s {where_sql}"
        count_result = dal.execute(count_sql, where_params)
        total_count = count_result.rows[0]["cnt"] if count_result.rows else 0

    # Build main query - simplified for performance
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    sort_col = req.sort_by if req.sort_by in ALLOWED_SORT else "n_cells"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"
    
    # Simple direct query - SQLite optimizer handles this well with covering index
    main_sql = f"""
SELECT 
    s.pk as sample_pk, s.sample_id, s.tissue, s.disease, s.cell_type,
    s.organism, s.sex, s.n_cells, s.source_database,
    sr.series_id, sr.title as series_title, sr.assay, sr.has_h5ad,
    p.project_id, p.title as project_title, p.pmid
FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
{where_sql}
ORDER BY s.{sort_col} {sort_dir} NULLS LAST
LIMIT ? OFFSET ?
"""
    main_params = where_params + [req.limit, req.offset]
    
    result = dal.execute(main_sql, main_params)
    
    records = [
        ExploreRecord(
            sample_pk=r.get("sample_pk", 0),
            sample_id=r.get("sample_id", ""),
            tissue=r.get("tissue"),
            disease=r.get("disease"),
            cell_type=r.get("cell_type"),
            organism=r.get("organism"),
            sex=r.get("sex"),
            n_cells=r.get("n_cells"),
            assay=r.get("assay"),
            source_database=r.get("source_database", ""),
            series_id=r.get("series_id"),
            series_title=r.get("series_title"),
            has_h5ad=bool(r.get("has_h5ad")),
            project_id=r.get("project_id"),
            project_title=r.get("project_title"),
            pmid=r.get("pmid"),
        )
        for r in result.rows
    ]
    
    elapsed = (time.perf_counter() - t0) * 1000
    if elapsed > 100:
        logger.warning(f"Slow explore query: {elapsed:.0f}ms, is_unfiltered={is_unfiltered}")
    else:
        logger.info(f"Explore query: {elapsed:.0f}ms, rows={len(records)}")

    return ExploreResponse(
        results=records,
        total_count=total_count,
        offset=req.offset,
        limit=req.limit,
        facets=facets if is_unfiltered else {},
    )


@router.post("/explore/facets")
async def explore_facets(req: ExploreRequest):
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)
    
    if is_unfiltered:
        _ensure_facets_loaded(dal)
        return {"total_count": _unfiltered_total, "facets": _unfiltered_facets}
    
    # For filtered queries, return minimal facets
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    count_sql = f"SELECT COUNT(*) as cnt FROM unified_samples s {where_sql}"
    count_result = dal.execute(count_sql, where_params)
    total = count_result.rows[0]["cnt"] if count_result.rows else 0
    
    return {"total_count": total, "facets": {}}
