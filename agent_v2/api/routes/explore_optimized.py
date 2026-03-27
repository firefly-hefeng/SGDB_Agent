"""
Faceted explore route — 优化版本

关键优化：
1. 主查询使用子查询避免大表 JOIN 后的排序
2. 延迟加载：先查询样本ID，再按需 JOIN
3. 使用覆盖索引避免回表
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


ALLOWED_SORT = {
    "n_cells", "tissue", "disease", "assay", "organism",
    "source_database", "project_title", "sample_id", "sex",
}


# ── 优化后的主查询：使用子查询避免大表 JOIN 后排序 ──

OPTIMIZED_SELECT = """
SELECT 
    s.pk as sample_pk, s.sample_id, s.tissue, s.disease, s.cell_type,
    s.organism, s.sex, s.n_cells, s.source_database,
    sr.series_id, sr.title as series_title, sr.assay, sr.has_h5ad,
    p.project_id, p.title as project_title, p.pmid
FROM (
    -- 子查询：先过滤+排序+分页，只取需要的 sample_pk
    SELECT pk 
    FROM unified_samples s
    {where_sql}
    ORDER BY s.{sort_col} {sort_dir} NULLS LAST
    LIMIT ? OFFSET ?
) filtered
JOIN unified_samples s ON s.pk = filtered.pk
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
ORDER BY s.{sort_col} {sort_dir} NULLS LAST
"""


def _build_where(
    req: ExploreRequest,
    table_alias: str = "s"
) -> tuple[list[str], list[Any]]:
    """Build WHERE clauses + params from request filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if req.tissues:
        placeholders = ",".join("?" for _ in req.tissues)
        clauses.append(f"{table_alias}.tissue IN ({placeholders})")
        params.extend(req.tissues)

    if req.diseases:
        placeholders = ",".join("?" for _ in req.diseases)
        clauses.append(f"{table_alias}.disease IN ({placeholders})")
        params.extend(req.diseases)

    if req.organisms:
        placeholders = ",".join("?" for _ in req.organisms)
        clauses.append(f"{table_alias}.organism IN ({placeholders})")
        params.extend(req.organisms)

    if req.cell_types:
        placeholders = ",".join("?" for _ in req.cell_types)
        clauses.append(f"{table_alias}.cell_type IN ({placeholders})")
        params.extend(req.cell_types)

    if req.source_databases:
        placeholders = ",".join("?" for _ in req.source_databases)
        clauses.append(f"{table_alias}.source_database IN ({placeholders})")
        params.extend(req.source_databases)

    if req.sex:
        clauses.append(f"{table_alias}.sex = ?")
        params.append(req.sex)

    if req.min_cells is not None:
        clauses.append(f"{table_alias}.n_cells >= ?")
        params.append(req.min_cells)

    if req.text_search:
        clauses.append(f"{table_alias}.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)")
        params.append(req.text_search)

    return clauses, params


@router.post("/explore", response_model=ExploreResponse)
async def explore(req: ExploreRequest):
    """
    Faceted search with structured filters, pagination.
    
    优化策略：
    1. 先对 samples 表过滤+排序+分页（利用覆盖索引）
    2. 仅对结果集 JOIN series/projects（避免大表 JOIN）
    """
    import time
    t0 = time.perf_counter()
    
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    # Build WHERE
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    # Sort column validation
    sort_col = req.sort_by if req.sort_by in ALLOWED_SORT else "n_cells"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"
    
    # 优化后的主查询：子查询先分页，再 JOIN
    main_sql = OPTIMIZED_SELECT.format(
        where_sql=where_sql,
        sort_col=sort_col,
        sort_dir=sort_dir
    )
    main_params = where_params + [req.limit, req.offset]
    
    result = dal.execute(main_sql, main_params)
    
    # COUNT - 使用快速路径
    if where_clauses:
        count_sql = f"SELECT COUNT(*) as cnt FROM unified_samples s {where_sql}"
        count_result = dal.execute(count_sql, where_params)
    else:
        # 无过滤时从预计算表读取
        count_result = dal.execute(
            "SELECT value as cnt FROM stats_overall WHERE metric = 'total_samples'"
        )
    total_count = count_result.rows[0]["cnt"] if count_result.rows else 0
    
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
    logger.info(f"Explore query: {elapsed:.0f}ms, returned {len(records)} rows")

    return ExploreResponse(
        results=records,
        total_count=total_count,
        offset=req.offset,
        limit=req.limit,
    )
