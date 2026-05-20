"""
Faceted explore route — structured filtering, pagination, facet counts.

Performance optimizations:
- Unfiltered requests use precomputed stats tables (<10ms vs 29s)
- COUNT queries skip JOINs when filters are sample-only columns
- Facet queries avoid unnecessary JOINs
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_dal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["explore"])


# ── Request / Response models ──

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


# ── Allowed sort columns (whitelist to prevent SQL injection) ──

ALLOWED_SORT = {
    "n_cells", "tissue", "disease", "assay", "organism",
    "source_database", "project_title", "sample_id", "sex",
}

FACET_FIELDS = {
    "tissue": ("s", "tissue", False),        # (alias, col, needs_join)
    "disease": ("s", "disease", False),
    "organism": ("s", "organism", False),
    "source_database": ("s", "source_database", False),
    "sex": ("s", "sex", False),
    "cell_type": ("s", "cell_type", False),
    "assay": ("sr", "assay", True),
}

# Precomputed stats table mapping for unfiltered facets
PRECOMPUTED_FACETS = {
    "tissue": ("stats_by_tissue", "tissue", "sample_count"),
    "disease": ("stats_by_disease", "disease", "sample_count"),
    "organism": ("stats_by_organism", "organism", "sample_count"),
    "source_database": ("stats_by_source", "source_database", "sample_count"),
    "sex": ("stats_by_sex", "sex", "sample_count"),
    "assay": ("stats_by_assay", "assay", "sample_count"),
    "cell_type": ("stats_by_cell_type", "cell_type", "sample_count"),
}

# Module-level cache for unfiltered facets
_unfiltered_facets: dict[str, list[FacetBucket]] | None = None
_unfiltered_total: int = 0


# ── Helpers ──

def _is_empty_filter(req: ExploreRequest) -> bool:
    """Check if the request has no active filters."""
    return (
        not req.tissues and not req.diseases and not req.organisms
        and not req.assays and not req.cell_types and not req.source_databases
        and not req.sex and req.min_cells is None
        and not req.has_h5ad and not req.text_search and not req.nl_query
    )


def _needs_series_join(req: ExploreRequest) -> bool:
    """Check if the request filters require a JOIN to unified_series."""
    return bool(req.assays) or req.has_h5ad is True


def _load_precomputed_facets(dal) -> tuple[dict[str, list[FacetBucket]], int]:
    """Load facet data from precomputed stats tables for the unfiltered state."""
    facets: dict[str, list[FacetBucket]] = {}

    for field_name, (table, col, count_col) in PRECOMPUTED_FACETS.items():
        try:
            result = dal.execute(
                f"SELECT {col} as value, {count_col} as count "
                f"FROM {table} WHERE {col} IS NOT NULL "
                f"ORDER BY {count_col} DESC LIMIT 30"
            )
            facets[field_name] = [
                FacetBucket(value=r["value"], count=r["count"])
                for r in result.rows if r["value"]
            ]
        except Exception as e:
            logger.warning("Precomputed facet %s failed: %s", field_name, e)
            facets[field_name] = []

    # Total count from stats_overall
    total = 0
    try:
        result = dal.execute("SELECT value FROM stats_overall WHERE metric = 'total_samples'")
        total = result.rows[0]["value"] if result.rows else 0
    except Exception:
        pass

    return facets, total


# ── WHERE builder ──

def _build_where(
    req: ExploreRequest,
    exclude_field: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Build WHERE clauses + params from request filters.

    If exclude_field is set, that filter is skipped (used for facet counts).
    """
    clauses: list[str] = []
    params: list[Any] = []

    if req.tissues and exclude_field != "tissue":
        placeholders = ",".join("?" for _ in req.tissues)
        clauses.append(f"s.tissue IN ({placeholders})")
        params.extend(req.tissues)

    if req.diseases and exclude_field != "disease":
        placeholders = ",".join("?" for _ in req.diseases)
        clauses.append(f"s.disease IN ({placeholders})")
        params.extend(req.diseases)

    if req.organisms and exclude_field != "organism":
        placeholders = ",".join("?" for _ in req.organisms)
        clauses.append(f"s.organism IN ({placeholders})")
        params.extend(req.organisms)

    if req.assays and exclude_field != "assay":
        placeholders = ",".join("?" for _ in req.assays)
        clauses.append(f"sr.assay IN ({placeholders})")
        params.extend(req.assays)

    if req.cell_types and exclude_field != "cell_type":
        placeholders = ",".join("?" for _ in req.cell_types)
        clauses.append(f"s.cell_type IN ({placeholders})")
        params.extend(req.cell_types)

    if req.source_databases and exclude_field != "source_database":
        placeholders = ",".join("?" for _ in req.source_databases)
        clauses.append(f"s.source_database IN ({placeholders})")
        params.extend(req.source_databases)

    if req.sex and exclude_field != "sex":
        clauses.append("s.sex = ?")
        params.append(req.sex)

    if req.min_cells is not None:
        clauses.append("s.n_cells >= ?")
        params.append(req.min_cells)

    if req.has_h5ad is True:
        clauses.append("sr.has_h5ad = 1")

    if req.text_search:
        clauses.append(
            "s.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)"
        )
        params.append(req.text_search)

    return clauses, params


def _build_where_sample_only(
    req: ExploreRequest,
    exclude_field: str | None = None,
) -> tuple[list[str], list[Any]]:
    """Build WHERE using only unified_samples columns (no JOINs needed)."""
    clauses: list[str] = []
    params: list[Any] = []

    if req.tissues and exclude_field != "tissue":
        placeholders = ",".join("?" for _ in req.tissues)
        clauses.append(f"s.tissue IN ({placeholders})")
        params.extend(req.tissues)

    if req.diseases and exclude_field != "disease":
        placeholders = ",".join("?" for _ in req.diseases)
        clauses.append(f"s.disease IN ({placeholders})")
        params.extend(req.diseases)

    if req.organisms and exclude_field != "organism":
        placeholders = ",".join("?" for _ in req.organisms)
        clauses.append(f"s.organism IN ({placeholders})")
        params.extend(req.organisms)

    if req.cell_types and exclude_field != "cell_type":
        placeholders = ",".join("?" for _ in req.cell_types)
        clauses.append(f"s.cell_type IN ({placeholders})")
        params.extend(req.cell_types)

    if req.source_databases and exclude_field != "source_database":
        placeholders = ",".join("?" for _ in req.source_databases)
        clauses.append(f"s.source_database IN ({placeholders})")
        params.extend(req.source_databases)

    if req.sex and exclude_field != "sex":
        clauses.append("s.sex = ?")
        params.append(req.sex)

    if req.min_cells is not None:
        clauses.append("s.n_cells >= ?")
        params.append(req.min_cells)

    if req.text_search:
        clauses.append("s.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)")
        params.append(req.text_search)

    return clauses, params


BASE_SELECT = """
SELECT
    s.pk as sample_pk, s.sample_id, s.tissue, s.disease, s.cell_type,
    s.organism, s.sex, s.n_cells, s.source_database,
    sr.series_id, sr.title as series_title, sr.assay, sr.has_h5ad,
    p.project_id, p.title as project_title, p.pmid
FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
"""

BASE_FROM = """
FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
"""

SAMPLE_ONLY_FROM = "FROM unified_samples s"


@router.post("/explore", response_model=ExploreResponse)
async def explore(req: ExploreRequest):
    """Faceted search with structured filters, pagination, and facet counts."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)
    needs_join = _needs_series_join(req)

    # ── Facets + total count ──
    if is_unfiltered:
        # Fast path: use precomputed stats tables (<10ms)
        global _unfiltered_facets, _unfiltered_total
        if _unfiltered_facets is None:
            _unfiltered_facets, _unfiltered_total = _load_precomputed_facets(dal)
        facets = _unfiltered_facets
        total_count = _unfiltered_total
    else:
        # Filtered path: live queries
        # Optimize COUNT: skip JOINs when filters are sample-only
        if needs_join:
            where_clauses, where_params = _build_where(req)
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            count_sql = f"SELECT COUNT(*) as cnt {BASE_FROM} {where_sql}"
            count_result = dal.execute(count_sql, where_params)
        else:
            sample_clauses, sample_params = _build_where_sample_only(req)
            sample_where = ("WHERE " + " AND ".join(sample_clauses)) if sample_clauses else ""
            count_sql = f"SELECT COUNT(*) as cnt {SAMPLE_ONLY_FROM} {sample_where}"
            count_result = dal.execute(count_sql, sample_params)
        total_count = count_result.rows[0]["cnt"] if count_result.rows else 0

        # Facet counts
        facets = _compute_live_facets(dal, req, needs_join)

    # ── Main query (always needs JOINs for series/project columns in SELECT) ──
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sort_col = req.sort_by if req.sort_by in ALLOWED_SORT else "n_cells"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"
    sort_prefix = "s."
    if sort_col in ("assay",):
        sort_prefix = "sr."
    elif sort_col in ("project_title",):
        sort_prefix = "p."
        sort_col = "title"
    order_sql = f"ORDER BY {sort_prefix}{sort_col} {sort_dir} NULLS LAST"

    main_sql = f"{BASE_SELECT} {where_sql} {order_sql} LIMIT ? OFFSET ?"
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

    return ExploreResponse(
        results=records,
        total_count=total_count,
        offset=req.offset,
        limit=req.limit,
        facets=facets,
    )


def _compute_live_facets(
    dal, req: ExploreRequest, needs_join: bool,
) -> dict[str, list[FacetBucket]]:
    """Compute facet counts with live queries (for filtered state)."""
    facets: dict[str, list[FacetBucket]] = {}

    for field_name, (table_alias, col_name, field_needs_join) in FACET_FIELDS.items():
        try:
            # If no filters need JOINs and this facet is sample-level, use simple query
            use_simple = not needs_join and not field_needs_join
            if use_simple:
                simple_fc, simple_fp = _build_where_sample_only(req, exclude_field=field_name)
                facet_where = ("WHERE " + " AND ".join(simple_fc)) if simple_fc else ""
                null_clause = f"s.{col_name} IS NOT NULL"
                if facet_where:
                    facet_where += f" AND {null_clause}"
                else:
                    facet_where = f"WHERE {null_clause}"
                facet_sql = (
                    f"SELECT s.{col_name} as value, COUNT(*) as count "
                    f"{SAMPLE_ONLY_FROM} {facet_where} "
                    f"GROUP BY s.{col_name} ORDER BY count DESC LIMIT 30"
                )
                facet_result = dal.execute(facet_sql, simple_fp)
            else:
                fc, fp = _build_where(req, exclude_field=field_name)
                facet_where = ("WHERE " + " AND ".join(fc)) if fc else ""
                null_clause = f"{table_alias}.{col_name} IS NOT NULL"
                if facet_where:
                    facet_where += f" AND {null_clause}"
                else:
                    facet_where = f"WHERE {null_clause}"
                facet_sql = (
                    f"SELECT {table_alias}.{col_name} as value, COUNT(*) as count "
                    f"{BASE_FROM} {facet_where} "
                    f"GROUP BY {table_alias}.{col_name} ORDER BY count DESC LIMIT 30"
                )
                facet_result = dal.execute(facet_sql, fp)

            facets[field_name] = [
                FacetBucket(value=r["value"], count=r["count"])
                for r in facet_result.rows
                if r["value"]
            ]
        except Exception as e:
            logger.warning("Facet query failed for %s: %s", field_name, e)
            facets[field_name] = []

    return facets


@router.post("/explore/facets")
async def explore_facets(req: ExploreRequest):
    """Lightweight facet counts only (no result rows)."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)

    if is_unfiltered:
        global _unfiltered_facets, _unfiltered_total
        if _unfiltered_facets is None:
            _unfiltered_facets, _unfiltered_total = _load_precomputed_facets(dal)
        return {"total_count": _unfiltered_total, "facets": _unfiltered_facets}

    needs_join = _needs_series_join(req)

    # Total count — skip JOINs when possible
    if needs_join:
        where_clauses, where_params = _build_where(req)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        count_sql = f"SELECT COUNT(*) as cnt {BASE_FROM} {where_sql}"
        count_result = dal.execute(count_sql, where_params)
    else:
        sample_clauses, sample_params = _build_where_sample_only(req)
        sample_where = ("WHERE " + " AND ".join(sample_clauses)) if sample_clauses else ""
        count_sql = f"SELECT COUNT(*) as cnt {SAMPLE_ONLY_FROM} {sample_where}"
        count_result = dal.execute(count_sql, sample_params)
    total = count_result.rows[0]["cnt"] if count_result.rows else 0

    facets = _compute_live_facets(dal, req, needs_join)

    return {"total_count": total, "facets": facets}
