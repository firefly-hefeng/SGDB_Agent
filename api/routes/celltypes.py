"""Cell-type browse / query routes (Phase 39 W2.2).

The portal advertises four entity tiers — sample / project / series / **cell
type** — but until Phase 39 there was no way to browse or query cell types as
first-class entities (they existed only as a sample-membership filter). This
router exposes the standardized cell-type catalogue with honest coverage
disclosure.

Two complementary cell-type views exist in the DB and we are explicit about
which one backs each number:

* **Dominant label** — ``unified_samples.cell_type_standard`` (336 standardized
  types, CL-aligned). One dominant label per sample, present for 225,811 /
  943,732 samples (23.9%) across all curated sources. This backs the catalogue
  list (broad coverage).
* **Fine-grained composition** — ``unified_celltypes`` (per-sample, multiple
  cell types each with a cell count). Richer but **CellxGene-only** (33,984
  samples / 378,029 annotations). This backs the per-dataset composition.

Endpoints
---------
- ``GET /scdbAPI/celltypes/search``        — paginated/searchable catalogue
- ``GET /scdbAPI/celltypes/{name}/projects`` — projects containing a cell type
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_dal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["celltypes"])

# ── Response models (typed contract — also feeds the agent-facing OpenAPI) ──


class CellTypeRow(BaseModel):
    cell_type: str = Field(..., description="Standardized cell-type name (cell_type_standard)")
    ontology_term_id: str | None = Field(None, description="Cell Ontology (CL) term id")
    n_samples: int = Field(..., description="Samples whose dominant label is this cell type")
    n_projects: int
    n_series: int
    n_sources: int


class CellTypeCoverage(BaseModel):
    basis: str
    samples_annotated: int
    samples_total: int
    annotated_pct: float
    distinct_types: int
    composition_note: str


class CellTypeSearchResponse(BaseModel):
    cell_types: list[CellTypeRow]
    total: int = Field(..., description="Distinct cell types matching the query")
    offset: int
    limit: int
    coverage: CellTypeCoverage


class CellTypeProjectRow(BaseModel):
    project_id: str
    title: str | None = None
    source_database: str | None = None
    n_samples: int


class CellTypeProjectsResponse(BaseModel):
    cell_type: str
    projects: list[CellTypeProjectRow]
    total_projects: int
    total_samples: int


# ── In-process cache of the (static) full catalogue ──

_CACHE: dict | None = None
_CACHE_LOCK = threading.Lock()


def _build_catalogue() -> dict:
    """Compute the full 336-row catalogue once (it is static, ~0.15 s)."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")
    rows = dal.execute(
        """
        SELECT cell_type_standard AS cell_type,
               MAX(cell_type_ontology_term_id) AS ontology_term_id,
               COUNT(*) AS n_samples,
               COUNT(DISTINCT project_id) AS n_projects,
               COUNT(DISTINCT series_id) AS n_series,
               COUNT(DISTINCT source_database) AS n_sources
        FROM unified_samples
        WHERE cell_type_standard IS NOT NULL AND cell_type_standard != ''
        GROUP BY cell_type_standard
        ORDER BY n_samples DESC
        """
    ).rows
    annotated = sum(r["n_samples"] for r in rows)
    total = dal.execute("SELECT COUNT(*) AS c FROM unified_samples").rows[0]["c"]
    coverage = CellTypeCoverage(
        basis="dominant cell_type_standard label per sample",
        samples_annotated=annotated,
        samples_total=total,
        annotated_pct=round(100 * annotated / total, 1) if total else 0.0,
        distinct_types=len(rows),
        composition_note=(
            "Fine-grained per-cell composition (multiple cell types per sample, "
            "with cell counts) is available for CellxGene samples only "
            "(33,984 samples / 378,029 annotations)."
        ),
    )
    return {"rows": rows, "coverage": coverage}


def _catalogue() -> dict:
    global _CACHE
    if _CACHE is None:
        with _CACHE_LOCK:
            if _CACHE is None:
                _CACHE = _build_catalogue()
    return _CACHE


_SORT_KEYS = {"n_samples", "n_projects", "n_series", "cell_type"}


@router.get(
    "/celltypes/search",
    response_model=CellTypeSearchResponse,
    summary="Browse / search the standardized cell-type catalogue",
    description=(
        "Paginated, searchable list of the 336 standardized cell types "
        "(CL-aligned), each with the number of samples / projects / series / "
        "sources in which it is the dominant cell type. The `coverage` block "
        "states honestly what fraction of samples are annotated and that "
        "fine-grained composition is CellxGene-only."
    ),
)
async def search_celltypes(
    q: str = Query("", description="Case-insensitive substring match on cell-type name"),
    sort: str = Query("n_samples", description="One of n_samples|n_projects|n_series|cell_type"),
    min_samples: int = Query(0, ge=0, description="Only types with at least this many samples"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CellTypeSearchResponse:
    cat = _catalogue()
    rows = cat["rows"]
    ql = q.strip().lower()
    if ql:
        rows = [r for r in rows if ql in r["cell_type"].lower()]
    if min_samples:
        rows = [r for r in rows if r["n_samples"] >= min_samples]

    sort_key = sort if sort in _SORT_KEYS else "n_samples"
    if sort_key == "cell_type":
        rows = sorted(rows, key=lambda r: r["cell_type"].lower())
    else:
        rows = sorted(rows, key=lambda r: r[sort_key], reverse=True)

    total = len(rows)
    page = rows[offset : offset + limit]
    return CellTypeSearchResponse(
        cell_types=[CellTypeRow(**r) for r in page],
        total=total,
        offset=offset,
        limit=limit,
        coverage=cat["coverage"],
    )


@router.get(
    "/celltypes/{name}/projects",
    response_model=CellTypeProjectsResponse,
    summary="Projects whose samples carry a given cell type",
    description=(
        "Drill-down: the projects that contain samples whose dominant cell "
        "type matches `name` (exact, case-insensitive), ranked by sample count."
    ),
)
async def celltype_projects(
    name: str,
    limit: int = Query(50, ge=1, le=500),
) -> CellTypeProjectsResponse:
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")
    rows = dal.execute(
        """
        SELECT s.project_id AS project_id,
               MAX(p.title) AS title,
               MAX(s.source_database) AS source_database,
               COUNT(*) AS n_samples
        FROM unified_samples s
        LEFT JOIN unified_projects p ON s.project_id = p.project_id
        WHERE LOWER(s.cell_type_standard) = LOWER(?)
          AND s.project_id IS NOT NULL AND s.project_id != ''
        GROUP BY s.project_id
        ORDER BY n_samples DESC
        LIMIT ?
        """,
        [name, limit],
    ).rows
    if not rows:
        raise HTTPException(status_code=404, detail="Cell type not found or has no projects")
    # True totals must be independent of the page `limit` (the rows above are
    # only the top-`limit` studies). Compute the real distinct-project count and
    # total sample count in one pass so the UI can show an honest "top L of N".
    totals = dal.execute(
        """
        SELECT COUNT(DISTINCT s.project_id) AS total_projects,
               COUNT(*) AS total_samples
        FROM unified_samples s
        WHERE LOWER(s.cell_type_standard) = LOWER(?)
          AND s.project_id IS NOT NULL AND s.project_id != ''
        """,
        [name],
    ).rows[0]
    return CellTypeProjectsResponse(
        cell_type=name,
        projects=[CellTypeProjectRow(**r) for r in rows],
        total_projects=totals["total_projects"],
        total_samples=totals["total_samples"],
    )


def prewarm_celltypes() -> None:
    """Build the catalogue cache at startup (cheap, ~0.15 s)."""
    try:
        _catalogue()
        logger.info("Cell-type catalogue pre-warmed")
    except Exception as e:  # noqa: BLE001
        logger.warning("Cell-type catalogue pre-warm failed: %s", e)
