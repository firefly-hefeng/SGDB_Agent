"""
Faceted explore route — 高性能版本

关键优化：
1. 利用 idx_samples_n_cells_covering 覆盖索引
2. 无过滤查询直接走预计算 facets
3. 简化查询结构，避免不必要的子查询

更新 (2026-04-10):
- 新增标准化字段: tissue_system, disease_category, sample_type
- 数据源 badge (curated catalog, 8 sources): geo, ega, ncbi, ebi, cellxgene, psychad, htan, hca
- 使用 organism_common 代替 organism 作为默认显示
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_dal
from api.services.fts5_util import safe_fts5_query

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
    # New standardized filters
    tissue_systems: list[str] = []
    disease_categories: list[str] = []
    sample_types: list[str] = []
    # R2-4: a featured-collection slug applies that collection's exact curated
    # filter (resolved server-side), so clicking a collection card lands on the
    # same subset it advertises rather than an unfiltered Explore.
    collection: str | None = None
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
    # New standardized fields
    tissue_standard: str | None = None
    tissue_system: str | None = None
    disease_standard: str | None = None
    disease_category: str | None = None
    organism_common: str | None = None
    sex_normalized: str | None = None
    sample_type: str | None = None
    n_cell_types: int | None = None


class ExploreResponse(BaseModel):
    results: list[ExploreRecord] = []
    total_count: int = 0
    offset: int = 0
    limit: int = 25
    facets: dict[str, list[FacetBucket]] = {}


ALLOWED_SORT = {
    "n_cells", "tissue", "disease", "assay", "organism",
    "source_database", "project_title", "sample_id", "sex",
    "tissue_standard", "disease_standard", "sample_type",
    "tissue_system", "disease_category", "organism_common",
}

# Phase 33 (R2-5a): the "tissue"/"disease" browse facets read the *cleaned*
# `*_standard` columns, not the raw ones. Raw `tissue` has 18,116 distinct
# values and raw `disease` 5,357 (with dupes like breast_cancer / breast cancer
# / Breast Cancer); the standardized columns collapse these to 627 / 721 clean,
# better-covered values. The filter `_build_where` matches the same columns so
# selecting a facet value actually filters the set it was counted from.
FACET_FIELDS = {
    "tissue": ("s", "tissue_standard"),
    "disease": ("s", "disease_standard"),
    "organism": ("s", "organism"),
    "source_database": ("s", "source_database"),
    "sex": ("s", "sex"),
    "cell_type": ("s", "cell_type_standard"),
    "assay": ("sr", "assay"),
    # New standardized facets
    "tissue_system": ("s", "tissue_system"),
    "disease_category": ("s", "disease_category"),
    "sample_type": ("s", "sample_type"),
}

# Phase 33 (R2-5b): facets used to be hard-capped at 30 values, so the sidebar
# (which has its own search + "show all" + scroll) could never reach the long
# tail. 800 shows every standardized tissue/disease value in full and a deep
# slice of the high-cardinality ones; the response is cached for the unfiltered
# case and gzipped.
FACET_TOP_N = 800

# Phase 32 — Fields whose raw column needs case-folding + label cleanup.
# Without normalization, the facet returns blood/Blood/BLOOD as three
# separate buckets and leaks raw ontology IDs (EFO_0001234) as labels.
# We GROUP BY LOWER(TRIM(...)) and pick the most-common-case spelling
# (typically "blood" or "PBMC") as the display value.
#
# Phase 34: tissue/disease moved OUT of here. They now point at the curated
# tissue_standard / disease_standard columns (see FACET_FIELDS /
# PRECOMPUTED_FACETS), which are *already* case-folded and ontology-ID-free, so
# a plain GROUP BY is both correct and ~50x cheaper. Running the case-fold
# window-function CTE over them at TOP_N=800 was the cause of a ~40s cold-start
# on the first filtered /explore after a restart. Only cell_type (still a raw
# column) needs folding.
CASE_FOLDED_FACETS = frozenset()

# Facets backed by a curated *_standard column: clean values, plain GROUP BY.
# cell_type joined them in Phase 34 — its raw case-fold over 6.5K distinct
# values was ~11s (the bulk of the ~40s cold-start); cell_type_standard has 336
# clean values and groups in ~28ms.
STANDARD_FACETS = frozenset({"tissue", "disease", "cell_type"})

# Raw ontology IDs that should never appear as a label.
ONTOLOGY_ID_GLOB = "*[A-Z]*_[0-9]*"

PRECOMPUTED_FACETS = {
    "tissue": ("stats_by_tissue", "tissue_standard", "sample_count"),
    "disease": ("stats_by_disease", "disease_standard", "sample_count"),
    "organism": ("stats_by_organism", "organism", "sample_count"),
    "source_database": ("stats_by_source", "source_database", "sample_count"),
    "sex": ("stats_by_sex", "sex", "sample_count"),
    "assay": ("stats_by_assay", "assay", "sample_count"),
    "cell_type": ("stats_by_cell_type", "cell_type_standard", "sample_count"),
    # New standardized facets
    "tissue_system": ("stats_by_tissue_system", "tissue_system", "sample_count"),
    "disease_category": ("stats_by_disease_category", "disease_category", "sample_count"),
    "sample_type": ("stats_by_sample_type", "sample_type", "sample_count"),
}

# 启动时预加载的缓存
_unfiltered_facets: dict[str, list[FacetBucket]] | None = None
_unfiltered_total: int = 0

# Cache for the unfiltered top-N (the default landing on /explore).
# Keyed by (sort_col, sort_dir, limit, offset). The unfiltered query
# scans 943k rows + sorts; without this cache the first user waits 30 s.
import threading as _threading
_unfiltered_top_cache: dict[tuple, Any] = {}
_unfiltered_top_lock = _threading.Lock()

# Phase 34: cache filtered facets + total_count keyed by the FILTER signature
# only (not sort/limit/offset). Facets and the count depend solely on the WHERE
# clause, so paginating, re-sorting, or re-applying a recent filter reuses the
# ~2s facet sweep instead of recomputing it. Bounded + short TTL so a static DB
# stays correct without unbounded growth.
_filtered_facet_cache: "dict[tuple, tuple[float, dict, int]]" = {}
_filtered_facet_lock = _threading.Lock()
_FILTERED_FACET_TTL = 120.0
_FILTERED_FACET_MAX = 256

# Phase 34: lowercase→canonical map per standard facet field, derived from the
# (already-loaded) unfiltered facets. Lets _build_where resolve a requested
# value to its exact stored spelling and emit an index-friendly equality match
# (`tissue_standard IN (...)`, ~8ms) instead of `LOWER(TRIM(...)) IN (...)`,
# which can't use the index and scans (~300ms). Safe because these columns have
# zero case-variant duplicates (verified: distinct == distinct-lower).
_std_canon_cache: "dict[str, dict[str, str]]" = {}


def _canon_map(field_name: str) -> "dict[str, str]":
    """{lowercased value: canonical stored value} for a standard facet field."""
    m = _std_canon_cache.get(field_name)
    if m is None:
        if not _unfiltered_facets:
            return {}
        m = {
            b.value.strip().lower(): b.value
            for b in _unfiltered_facets.get(field_name, [])
            if b.value
        }
        _std_canon_cache[field_name] = m
    return m


def prewarm_explore_unfiltered() -> None:
    """Pre-warm the unfiltered top-50 result the frontend loads first."""
    try:
        # Frontend default: sort_by=n_cells, sort_dir=desc, limit=50, offset=0.
        # The two common pages are 0 and 50.
        for offset in (0, 50):
            req = ExploreRequest(limit=50, offset=offset, sort_by="n_cells", sort_dir="desc")
            import asyncio
            asyncio.run(explore(req))
    except Exception as e:
        logger.warning("explore prewarm failed: %s", e)


def _is_empty_filter(req: ExploreRequest) -> bool:
    return (
        not req.tissues and not req.diseases and not req.organisms
        and not req.assays and not req.cell_types and not req.source_databases
        and not req.sex and req.min_cells is None
        and not req.has_h5ad and not req.text_search and not req.nl_query
        and not req.tissue_systems and not req.disease_categories
        and not req.sample_types and not req.collection
    )


def _build_where(req: ExploreRequest) -> tuple[list[str], list[Any]]:
    """Build WHERE clauses for unified_samples table."""
    clauses: list[str] = []
    params: list[Any] = []

    def _in_clause(field: str, values: list[str], alias: str = "s"):
        if not values:
            return
        placeholders = ",".join("?" for _ in values)
        clauses.append(f"{alias}.{field} IN ({placeholders})")
        params.extend(values)

    def _in_clause_ci(field: str, values: list[str], alias: str = "s"):
        # Case-insensitive IN — matches values regardless of BLOOD/Blood/blood
        # spelling. Lowercases both sides; trims to defang stray whitespace.
        if not values:
            return
        placeholders = ",".join("?" for _ in values)
        clauses.append(
            f"LOWER(TRIM({alias}.{field})) IN ({placeholders})"
        )
        params.extend([v.strip().lower() for v in values])

    def _in_clause_std(field_name: str, col: str, values: list[str]):
        # Standard facet field: resolve each value to its canonical stored
        # spelling and emit an index-friendly equality match. If any value is
        # unknown (not in the facet vocabulary), fall back to the case-folded
        # scan so correctness never depends on the resolver being warm.
        if not values:
            return
        cmap = _canon_map(field_name)
        canon = [cmap.get(v.strip().lower()) for v in values]
        if cmap and all(c is not None for c in canon):
            placeholders = ",".join("?" for _ in canon)
            clauses.append(f"s.{col} IN ({placeholders})")
            params.extend(canon)
        else:
            _in_clause_ci(col, values)

    # Match the cleaned columns the facets are built from (R2-5a) so selecting
    # a facet value filters exactly the rows it was counted over.
    _in_clause_std("tissue", "tissue_standard", req.tissues)
    _in_clause_std("disease", "disease_standard", req.diseases)
    _in_clause("organism", req.organisms)
    _in_clause_std("cell_type", "cell_type_standard", req.cell_types)
    _in_clause("source_database", req.source_databases)

    # New standardized filters
    _in_clause("tissue_system", req.tissue_systems)
    _in_clause("disease_category", req.disease_categories)
    _in_clause("sample_type", req.sample_types)

    if req.sex:
        clauses.append("s.sex = ?")
        params.append(req.sex)

    if req.min_cells is not None:
        clauses.append("s.n_cells >= ?")
        params.append(req.min_cells)

    if req.assays:
        # Assay is on series table — use subquery for performance
        placeholders = ",".join("?" for _ in req.assays)
        clauses.append(
            f"s.series_pk IN (SELECT pk FROM unified_series WHERE assay IN ({placeholders}))"
        )
        params.extend(req.assays)

    # Audit F5 (Phase 36): the has_h5ad filter was declared + counted as a real
    # filter but never applied here (lost in the explore rewrite — the archived
    # explore_original.py had it), so true/false/unset all returned the whole DB.
    # has_h5ad lives on unified_series; subquery for index-friendliness.
    if req.has_h5ad is True:
        clauses.append(
            "s.series_pk IN (SELECT pk FROM unified_series WHERE has_h5ad = 1)"
        )
    elif req.has_h5ad is False:
        clauses.append(
            "s.series_pk IN (SELECT pk FROM unified_series "
            "WHERE has_h5ad IS NULL OR has_h5ad = 0)"
        )

    if req.text_search:
        safe_q = safe_fts5_query(req.text_search)
        if safe_q:
            clauses.append("s.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)")
            params.append(safe_q)

    # R2-4: apply a featured collection's exact curated filter.
    if req.collection:
        from api.routes.collections import resolve_collection_filter
        resolved = resolve_collection_filter(req.collection)
        if resolved is not None:
            where_sql, where_params, _title = resolved
            if where_sql and where_sql != "1=1":
                clauses.append(f"({where_sql})")
                params.extend(where_params)

    return clauses, params


def _load_precomputed_facets(dal):
    """Load all facets from precomputed stats tables (runs once at startup).

    Tissue / disease / cell_type get the case-folded treatment instead —
    raw stats tables in the DB still contain BLOOD/Blood/blood as three
    rows and leak raw EFO_xxx labels, so we recompute those three on the
    fly with most-common-case display picking.
    """
    facets: dict[str, list[FacetBucket]] = {}

    for field_name, (table, col, count_col) in PRECOMPUTED_FACETS.items():
        if field_name in STANDARD_FACETS:
            # Plain GROUP BY on the curated column (the precomputed stats_by_*
            # tables only carry the RAW column, so we read unified_samples).
            try:
                result = dal.execute(
                    f"SELECT {col} as value, COUNT(*) as count FROM unified_samples "
                    f"WHERE {col} IS NOT NULL AND {col} != '' "
                    f"GROUP BY {col} ORDER BY count DESC LIMIT {FACET_TOP_N}"
                )
                facets[field_name] = [
                    FacetBucket(value=r["value"], count=r["count"])
                    for r in result.rows if r["value"]
                ]
            except Exception as e:
                logger.warning("Standard facet %s failed: %s", field_name, e)
                facets[field_name] = []
            continue
        if field_name in CASE_FOLDED_FACETS:
            facets[field_name] = _compute_case_folded_facet(dal, col, top_n=FACET_TOP_N)
            continue
        try:
            result = dal.execute(
                f"SELECT {col} as value, {count_col} as count FROM {table} "
                f"WHERE {col} IS NOT NULL ORDER BY {count_col} DESC LIMIT {FACET_TOP_N}"
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


def _compute_case_folded_facet(
    dal,
    col: str,
    top_n: int = 30,
    extra_where: str | None = None,
    extra_params: list | None = None,
    from_clause: str | None = None,
) -> list[FacetBucket]:
    """Compute a facet that folds case (blood/Blood/BLOOD → "blood") and
    rejects raw ontology IDs (EFO_0009375 etc.) from the label column.

    Uses a CTE that picks the most-common-case spelling as the display
    value, so "PBMC" remains "PBMC" rather than getting lowercased to
    "pbmc". Summing across all case variants gives accurate counts.
    """
    table = from_clause or "unified_samples s"
    where_parts: list[str] = [
        f"s.{col} IS NOT NULL",
        f"s.{col} != ''",
        f"s.{col} NOT GLOB '{ONTOLOGY_ID_GLOB}'",
    ]
    if extra_where:
        where_parts.append(extra_where)
    where_sql = " AND ".join(where_parts)
    params = list(extra_params or [])

    sql = f"""
        WITH raw_counts AS (
            SELECT s.{col} AS raw, LOWER(TRIM(s.{col})) AS norm, COUNT(*) AS cnt
            FROM {table}
            WHERE {where_sql}
            GROUP BY s.{col}
        ),
        ranked AS (
            SELECT norm, raw, cnt,
                ROW_NUMBER() OVER (PARTITION BY norm ORDER BY cnt DESC) AS rn
            FROM raw_counts
        )
        SELECT
            (SELECT raw FROM ranked r2 WHERE r2.norm = rc.norm AND r2.rn = 1) AS display,
            SUM(rc.cnt) AS total
        FROM raw_counts rc
        GROUP BY rc.norm
        ORDER BY total DESC
        LIMIT ?
    """
    try:
        result = dal.execute(sql, params + [top_n])
        return [
            FacetBucket(value=r["display"], count=r["total"])
            for r in result.rows
            if r["display"]
        ]
    except Exception as e:
        logger.warning("Case-folded facet %s failed: %s", col, e)
        return []


def _ensure_facets_loaded(dal):
    """Ensure facets are loaded (lazy initialization)."""
    global _unfiltered_facets, _unfiltered_total
    if _unfiltered_facets is None:
        import time as _time
        t0 = _time.time()
        _unfiltered_facets, _unfiltered_total = _load_precomputed_facets(dal)
        t1 = _time.time()
        logger.info(f"Facets loaded in {(t1-t0)*1000:.0f}ms")


# Facet field_name -> the ExploreRequest attribute holding its selected value(s).
# Used so a facet's OWN selection is excluded from its OWN counts (see below).
_FACET_REQ_ATTR = {
    "tissue": "tissues", "disease": "diseases", "organism": "organisms",
    "cell_type": "cell_types", "source_database": "source_databases",
    "assay": "assays", "sex": "sex",
    "tissue_system": "tissue_systems", "disease_category": "disease_categories",
    "sample_type": "sample_types",
}


def _build_where_excluding(req: "ExploreRequest", field_name: str) -> tuple[list[str], list[Any]]:
    """WHERE for a facet's own counts: every active filter EXCEPT that facet's
    own selection. Without this, picking one value collapses the facet to just
    that value, so the user cannot add a second one — the reported multi-select
    bug. Excluding the field's own filter keeps the other values visible to OR in."""
    attr = _FACET_REQ_ATTR.get(field_name)
    if not attr:
        return _build_where(req)
    data = req.model_dump()
    data[attr] = None if attr == "sex" else []
    return _build_where(ExploreRequest(**data))


def _compute_filtered_facets(
    dal, req: "ExploreRequest",
    where_clauses: list[str], where_params: list,
) -> dict[str, list[FacetBucket]]:
    """Compute facet counts for the current filtered result set.

    Each facet field is counted under all OTHER active filters but NOT its own,
    so after selecting one value the remaining values stay visible and can be
    OR'd together (standard faceted-search behaviour, enabling multi-select)."""
    facets: dict[str, list[FacetBucket]] = {}

    for field_name, (alias, col) in FACET_FIELDS.items():
        try:
            # Drop this facet's own filter from its own counts (multi-select).
            attr = _FACET_REQ_ATTR.get(field_name)
            has_own = bool(getattr(req, attr, None)) if attr else False
            if has_own:
                wc, wp = _build_where_excluding(req, field_name)
            else:
                wc, wp = where_clauses, where_params
            base_where = ("WHERE " + " AND ".join(wc)) if wc else ""

            col_expr = f"{alias}.{col}"
            null_clause = f"{col_expr} IS NOT NULL"
            facet_where = f"{base_where} AND {null_clause}" if base_where else f"WHERE {null_clause}"

            # Determine if we need JOINs
            needs_join = "sr." in facet_where or "p." in facet_where or alias != "s"
            if needs_join:
                from_clause = (
                    "FROM unified_samples s "
                    "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
                    "LEFT JOIN unified_projects p ON s.project_pk = p.pk"
                )
            else:
                from_clause = "FROM unified_samples s"

            # Case-folded facets fold BLOOD/Blood/blood into one bucket and
            # reject raw EFO_xxxxxx-style ontology IDs from labels.
            if field_name in CASE_FOLDED_FACETS:
                extra_where = " AND ".join(wc) if wc else None
                facets[field_name] = _compute_case_folded_facet(
                    dal,
                    col=col,
                    top_n=FACET_TOP_N,
                    extra_where=extra_where,
                    extra_params=wp,
                    from_clause=from_clause.removeprefix("FROM "),
                )
                continue

            sql = (
                f"SELECT {col_expr} as value, COUNT(*) as count "
                f"{from_clause} {facet_where} "
                f"GROUP BY {col_expr} ORDER BY count DESC LIMIT {FACET_TOP_N}"
            )
            result = dal.execute(sql, wp)
            facets[field_name] = [
                FacetBucket(value=r["value"], count=r["count"])
                for r in result.rows if r["value"]
            ]
        except Exception as e:
            logger.warning("Filtered facet %s failed: %s", field_name, e)
            facets[field_name] = []

    return facets


@router.post("/explore", response_model=ExploreResponse)
async def explore(req: ExploreRequest):
    import time
    t0 = time.perf_counter()

    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)

    # Cache hit for the unfiltered landing case (default sort, first page).
    # Subsequent pages or sort variants miss and hit the SQL path below.
    if is_unfiltered:
        cache_key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _unfiltered_top_lock:
            cached = _unfiltered_top_cache.get(cache_key)
        if cached is not None:
            return cached

    # Load facets up front so _build_where's canonical-value resolver (which
    # reads the unfiltered facet vocabulary) can emit index-friendly equality
    # matches. Cheap + idempotent after the first call / startup prewarm.
    _ensure_facets_loaded(dal)

    # _build_where once; reused for count, facets, and the main query.
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Handle facets and count
    if is_unfiltered:
        facets = _unfiltered_facets
        total_count = _unfiltered_total
    else:
        # Facets + count depend only on the filter, so key the cache on the
        # WHERE signature (not sort/limit/offset). Pagination & re-sorts reuse.
        fkey = (tuple(where_clauses), tuple(where_params))
        now = time.time()
        with _filtered_facet_lock:
            hit = _filtered_facet_cache.get(fkey)
        if hit is not None and (now - hit[0]) < _FILTERED_FACET_TTL:
            _, facets, total_count = hit
        else:
            count_sql = f"SELECT COUNT(*) as cnt FROM unified_samples s {where_sql}"
            count_result = dal.execute(count_sql, where_params)
            total_count = count_result.rows[0]["cnt"] if count_result.rows else 0
            facets = _compute_filtered_facets(dal, req, where_clauses, where_params)
            with _filtered_facet_lock:
                if len(_filtered_facet_cache) >= _FILTERED_FACET_MAX:
                    # Evict the oldest entry (FIFO is fine for a static DB).
                    oldest = min(_filtered_facet_cache,
                                 key=lambda k: _filtered_facet_cache[k][0])
                    _filtered_facet_cache.pop(oldest, None)
                _filtered_facet_cache[fkey] = (now, facets, total_count)

    sort_col = req.sort_by if req.sort_by in ALLOWED_SORT else "n_cells"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"

    # Map sort columns to their actual table.column references
    SORT_COL_MAP = {
        "assay": "sr.assay",
        "project_title": "p.title",
    }
    sort_expr = SORT_COL_MAP.get(sort_col, f"s.{sort_col}")

    # Simple direct query - SQLite optimizer handles this well with covering index
    main_sql = f"""
SELECT
    s.pk as sample_pk, s.sample_id, s.tissue, s.disease, s.cell_type,
    s.organism, s.sex, s.n_cells, s.source_database,
    s.tissue_standard, s.tissue_system,
    s.disease_standard, s.disease_category,
    s.organism_common, s.sex_normalized, s.sample_type,
    s.n_cell_types,
    sr.series_id, sr.title as series_title, sr.assay, sr.has_h5ad,
    p.project_id, p.title as project_title, p.pmid
FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
{where_sql}
ORDER BY {sort_expr} {sort_dir} NULLS LAST
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
            # New standardized fields
            tissue_standard=r.get("tissue_standard"),
            tissue_system=r.get("tissue_system"),
            disease_standard=r.get("disease_standard"),
            disease_category=r.get("disease_category"),
            organism_common=r.get("organism_common"),
            sex_normalized=r.get("sex_normalized"),
            sample_type=r.get("sample_type"),
            n_cell_types=r.get("n_cell_types"),
        )
        for r in result.rows
    ]

    elapsed = (time.perf_counter() - t0) * 1000
    if elapsed > 100:
        logger.warning(f"Slow explore query: {elapsed:.0f}ms, is_unfiltered={is_unfiltered}")
    else:
        logger.info(f"Explore query: {elapsed:.0f}ms, rows={len(records)}")

    response = ExploreResponse(
        results=records,
        total_count=total_count,
        offset=req.offset,
        limit=req.limit,
        facets=facets or {},
    )

    if is_unfiltered:
        cache_key = (req.sort_by, req.sort_dir, req.limit, req.offset)
        with _unfiltered_top_lock:
            _unfiltered_top_cache[cache_key] = response

    return response


@router.post("/explore/facets")
async def explore_facets(req: ExploreRequest):
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    is_unfiltered = _is_empty_filter(req)

    if is_unfiltered:
        _ensure_facets_loaded(dal)
        return {"total_count": _unfiltered_total, "facets": _unfiltered_facets}

    # For filtered queries, compute actual facet counts
    where_clauses, where_params = _build_where(req)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    count_sql = f"SELECT COUNT(*) as cnt FROM unified_samples s {where_sql}"
    count_result = dal.execute(count_sql, where_params)
    total = count_result.rows[0]["cnt"] if count_result.rows else 0
    facets = _compute_filtered_facets(dal, req, where_clauses, where_params)

    return {"total_count": total, "facets": facets}
