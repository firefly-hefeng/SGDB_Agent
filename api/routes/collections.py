"""Featured collections route — Phase 27.

Returns curated cross-source highlights derived from the **live** unified
catalog. Two flavours:

- ``GET /scdbAPI/collections/featured`` — themed cross-source bundles
  (3-5 per page). Each bundle has a slug, title, blurb, query template,
  hero counts, and 3 representative project IDs sampled live so they're
  guaranteed to exist.
- ``GET /scdbAPI/collections/trending`` — top-N projects with the highest
  cell counts, recent submission dates, or citation counts.

The frontend Landing page consumes these to surface real curated content
instead of inventing dataset titles (Phase 27 audit M4).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from fastapi import APIRouter

from api.deps import get_dal
from api._text import fix_mojibake

router = APIRouter(prefix="/scdbAPI/collections", tags=["collections"])
log = logging.getLogger(__name__)

# Process-wide cache for the featured-collections response. The themes are
# static and the underlying counts change only when the DB is rebuilt, so
# we hold the answer for 1 h and serve stale on cache miss while a
# background refresh runs.
_FEATURED_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_FEATURED_LOCK = threading.Lock()
_FEATURED_TTL_SECONDS = 3600.0

# Per-limit cache for /trending. The query orders 50k+ rows by total_cells
# DESC; without a covering index it takes ~3 s per call, so we hold each
# distinct limit for a few minutes. The whole projects table can change
# only at DB rebuild, so a short TTL is purely a safety knob.
_TRENDING_CACHE: dict[int, dict[str, Any]] = {}
_TRENDING_LOCK = threading.Lock()
_TRENDING_TTL_SECONDS = 600.0
# When the cache is empty *and* we're holding the lock, hard-cap the
# per-theme query at this many seconds so a slow DB doesn't lock up the
# first request after a restart.
_PER_THEME_DEADLINE_SECONDS = 8.0


# ── Curated theme catalogue ──
#
# Each theme is realised by a SQL query at request time so the count +
# example projects are always live. The LIKE terms below were audited
# against the canonical vocabularies in `src/discovery/intent_parser.py`
# and `src/understanding/parser.py` (Phase 28) to ensure every term
# actually matches values produced by the DB build pipeline.
#
# Edits in Phase 28:
#   - alzheimer-brain  : dropped 'cerebrum' (dead term)
#   - pancreatic-islet : honest blurb (no disease filter, so PDAC is in too)
#   - tumor-immune     : blurb widened to "solid + hematologic" (filter
#                        includes leukemia/lymphoma); added 'natural killer'
#                        + 'dendritic' to cell_type_like
#   - developing-brain : dropped redundant 'fetal brain'/'embryonic brain'
#                        tissues; kept only canonical sample_type 'fetal';
#                        blurb shrunk to what the filter can deliver
#   - covid-immune     : dropped 'sars' (over-matched SARS-CoV-1); added
#                        'nasal' tissue (NP swabs are a common COVID source)
#   - kidney-atlas     : NEW (KPMP + HCA kidney bionetwork data)
#   - heart-cardiac    : NEW (HCA heart bionetwork + cardiomyopathy)
#
# Review history: `docs/annotation/audit_round1_bugs_and_ux.md`.

THEMES = [
    {
        "slug": "alzheimer-brain",
        "title": "Alzheimer's brain",
        "blurb": "Single-cell datasets profiling Alzheimer's disease across cortex, hippocampus, and broader brain regions.",
        "tissue_like": ["brain", "hippocamp", "cortex"],
        "disease_like": ["alzheimer"],
    },
    {
        "slug": "pancreatic-islet",
        "title": "Pancreas & islet",
        "blurb": "Pancreas and islet single-cell samples spanning endocrine physiology, diabetes, and pancreatic cancer biology.",
        "tissue_like": ["pancreas", "islet"],
        "disease_like": [],
    },
    {
        "slug": "tumor-immune",
        "title": "Tumor immune landscape",
        "blurb": "Studies that characterise the T-cell, B-cell, NK, dendritic, and myeloid landscape across solid and hematologic tumors.",
        "tissue_like": [],
        "disease_like": ["cancer", "carcinoma", "lymphoma", "leukemia", "melanoma", "glioma"],
        "cell_type_like": ["t cell", "b cell", "nk cell", "natural killer", "macrophage", "myeloid", "dendritic"],
        # Phase 28 QA: AND of disease+cell_type was too narrow because most
        # tumor samples don't carry per-sample cell-type curation. The
        # blurb describes a union ("tumor OR immune cells"), so OR-join
        # delivers the catalog the description promises.
        "join_mode": "OR",
    },
    {
        "slug": "developing-brain",
        "title": "Fetal & developing brain",
        "blurb": "Fetal brain and developing CNS atlases at single-cell resolution.",
        # Phase 28 QA: the canonical SAMPLE_TYPE_KEYWORDS vocab has no
        # 'fetal' value in this DB build (verified: sample_type ∈
        # {primary_tissue, tumor, cell_line, unknown, iPSC_derived,
        # PSC_derived, in_vitro_other, organoid, xenograft}). Using a
        # multi-word LIKE on the tissue field instead — these substrings
        # match real tissue values like "Fetal brain", "fetal cortex",
        # "embryonic neural tube" etc.
        "tissue_like": [
            "fetal brain", "embryonic brain", "fetal cortex",
            "fetal cerebellum", "fetal hippocamp",
            "embryonic neural", "fetal neural", "fetal cns",
        ],
        "disease_like": [],
    },
    {
        "slug": "covid-immune",
        "title": "COVID-19 immune response",
        "blurb": "PBMC, lung, bronchoalveolar, and nasopharyngeal profiles from SARS-CoV-2 infection cohorts.",
        "tissue_like": ["pbmc", "blood", "lung", "bronch", "nasal"],
        "disease_like": ["covid"],
    },
    {
        "slug": "ipsc-organoid",
        "title": "iPSC-derived organoids",
        "blurb": "In-vitro organoid and iPSC-derived models across organ systems.",
        "tissue_like": [],
        "disease_like": [],
        "sample_type_like": ["organoid", "ipsc", "psc_derived"],
    },
    {
        "slug": "kidney-atlas",
        "title": "Kidney atlas & nephropathy",
        "blurb": "Healthy kidney and CKD / AKI single-cell datasets, including KPMP cohorts.",
        # Phase 28 QA: 'glomerul' covers both 'glomerulus'/'glomeruli';
        # added 'tubule' for proximal/distal tubule samples.
        "tissue_like": ["kidney", "renal", "nephron", "glomerul", "tubule"],
        "disease_like": [],
    },
    {
        "slug": "heart-cardiac",
        "title": "Heart & cardiac biology",
        "blurb": "Single-cell cardiac atlases spanning healthy myocardium, heart failure, and cardiomyopathy.",
        # Phase 28 QA: 'atri' was a short substring; widened to 'atrium' and
        # 'atria' so the LIKE only matches anatomical heart terms.
        "tissue_like": ["heart", "cardiac", "myocard", "ventric", "atrium", "atria"],
        "disease_like": [],
    },
]


def _build_theme_query(theme: dict[str, Any], alias: str = "") -> tuple[str, list[Any]]:
    """Return a SQL fragment counting samples that match any of the theme's
    LIKE filters, plus a parameter list. Each filter group is OR-combined
    internally; cross-group join defaults to AND but can be switched to OR
    via the optional ``join_mode`` key on the theme — useful for themes
    like ``tumor-immune`` whose blurb describes a *union* of "tumor
    disease" and "immune cell-type" cohorts, not their intersection."""
    where: list[str] = []
    params: list[Any] = []
    # Phase 37: match the cleaned *_standard columns, not the raw ones. The raw
    # tissue/disease/cell_type columns are messy (18k/5k/6.5k distinct values with
    # case dupes, EFO IDs, and ~4k NULL-standard rows that leak into a raw LIKE),
    # and — critically — they are NOT the columns Explore's facets + filters use.
    # So clicking a collection landed on a subset built from a *different* column
    # space than the page it opened, and under-/over-counted vs the true theme
    # (e.g. Alzheimer's missed ~130 standardized cases; pancreas leaked ~5k
    # un-standardized rows). Standard columns fix precision, recall, and the
    # cross-page consistency in one move.
    for col, key in (
        ("tissue_standard", "tissue_like"),
        ("disease_standard", "disease_like"),
        ("cell_type_standard", "cell_type_like"),
        ("sample_type", "sample_type_like"),
    ):
        likes = theme.get(key) or []
        if not likes:
            continue
        col_ref = f"{alias}.{col}" if alias else col
        ors = []
        for term in likes:
            ors.append(f"LOWER({col_ref}) LIKE ?")
            params.append(f"%{term.lower()}%")
        where.append("(" + " OR ".join(ors) + ")")
    if not where:
        return "1=1", []
    joiner = " OR " if str(theme.get("join_mode", "AND")).upper() == "OR" else " AND "
    return joiner.join(where), params


_THEME_BY_SLUG = {t["slug"]: t for t in THEMES}


def resolve_collection_filter(slug: str) -> tuple[str, list[Any], str] | None:
    """Phase 33 (R2-4): resolve a featured-collection slug to its exact
    catalog filter so clicking a collection lands on the *same* curated subset
    the card counts — not a coarse keyword search or (worse) an unfiltered
    Explore. Returns ``(where_sql, params, title)`` or ``None`` for an unknown
    slug. The WHERE clause is the theme's audited LIKE definition, reused
    verbatim from the card's COUNT query.
    """
    theme = _THEME_BY_SLUG.get(slug)
    if theme is None:
        return None
    where_sql, params = _build_theme_query(theme, alias="s")
    return where_sql, params, theme["title"]


def _compute_collection_for_theme(dal: Any, theme: dict[str, Any]) -> dict[str, Any]:
    """Run the COUNT + sample-projects queries for a single theme.

    Wrapped in its own try/except so one slow theme can't break the rest.
    """
    where_sql, params = _build_theme_query(theme, alias="s")
    sample_count = 0
    project_count = 0
    projects: list[dict[str, Any]] = []
    try:
        cnt = dal.execute(
            f"SELECT COUNT(*) AS c, COUNT(DISTINCT s.project_id) AS p "
            f"FROM unified_samples s WHERE {where_sql}",
            params,
        )
        row = cnt.rows[0] if cnt.rows else {"c": 0, "p": 0}
        sample_count = int(row.get("c") or 0)
        project_count = int(row.get("p") or 0)

        if sample_count > 0:
            # INNER JOIN unified_projects so the showcased example projects are
            # guaranteed to exist in the catalog and be clickable. ~1% of
            # sample.project_id values are orphans (malformed EBI/NCBI IDs like
            # "E-MTAB-41841461925973" with no projects row) — surfacing those as
            # featured links sent users to a 404. The JOIN also fetches the
            # title for a richer card.
            ex = dal.execute(
                f"SELECT s.project_id, s.source_database, COUNT(*) AS sample_count, "
                f"       p.title AS title "
                f"FROM unified_samples s "
                f"JOIN unified_projects p ON s.project_id = p.project_id "
                f"WHERE {where_sql} AND s.project_id IS NOT NULL "
                f"GROUP BY s.project_id "
                f"ORDER BY sample_count DESC LIMIT 3",
                params,
            )
            projects = [
                {
                    "project_id": r["project_id"],
                    "source_database": r["source_database"],
                    "sample_count": int(r["sample_count"] or 0),
                    "title": fix_mojibake(r.get("title")),
                }
                for r in ex.rows
            ]
    except Exception as e:
        log.warning("collection_query_failed slug=%s: %s", theme["slug"], e)
    return {
        "slug": theme["slug"],
        "title": theme["title"],
        "blurb": theme["blurb"],
        "sample_count": sample_count,
        "project_count": project_count,
        "projects": projects,
        "query": _theme_to_explore_query(theme),
    }


def _compute_featured(dal: Any) -> dict[str, Any]:
    started = time.perf_counter()
    out: list[dict[str, Any]] = []
    for t in THEMES:
        # Each theme has its own deadline so one slow LIKE doesn't lock
        # the response for minutes.
        theme_start = time.perf_counter()
        out.append(_compute_collection_for_theme(dal, t))
        elapsed_one = time.perf_counter() - theme_start
        if elapsed_one > _PER_THEME_DEADLINE_SECONDS:
            log.warning(
                "collection_slow slug=%s elapsed=%.2fs",
                t["slug"],
                elapsed_one,
            )
    return {
        "collections": out,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def _skeleton_response() -> dict[str, Any]:
    return {
        "collections": [
            {
                "slug": t["slug"],
                "title": t["title"],
                "blurb": t["blurb"],
                "sample_count": 0,
                "project_count": 0,
                "projects": [],
                "query": _theme_to_explore_query(t),
            }
            for t in THEMES
        ],
        "elapsed_ms": 0,
    }


def prewarm_featured_cache() -> None:
    """Compute the featured collections once at startup and seed the
    process-wide cache. Called from the FastAPI lifespan handler."""
    dal = get_dal()
    if dal is None:
        return
    try:
        result = _compute_featured(dal)
        with _FEATURED_LOCK:
            _FEATURED_CACHE["data"] = result
            _FEATURED_CACHE["ts"] = time.time()
        log.info("featured_collections prewarmed in %d ms", result["elapsed_ms"])
    except Exception as e:
        log.warning("featured_collections prewarm failed: %s", e)


@router.get(
    "/featured",
    summary="Featured cross-source collections",
    description=(
        "Return the hand-curated theme catalogue (8 themes: Alzheimer brain, "
        "pancreas & islet, tumor immune landscape, fetal & developing brain, "
        "COVID immune, iPSC organoids, kidney atlas, heart & cardiac). Each "
        "theme is annotated with **live** sample and project counts plus 3 "
        "representative project IDs sampled from the unified catalog, so "
        "nothing on the landing page is fabricated."
    ),
)
def get_featured_collections() -> dict[str, Any]:
    """Return the curated theme catalogue, each annotated with live counts
    and 3 representative project IDs sampled from the unified DB.

    Cached for ~1 h in process memory. The first request after a cold
    start will populate it; subsequent requests are O(serialisation).
    """
    dal = get_dal()
    if dal is None:
        return _skeleton_response()

    now = time.time()
    with _FEATURED_LOCK:
        cached = _FEATURED_CACHE.get("data")
        ts = _FEATURED_CACHE.get("ts", 0.0)
        if cached is not None and (now - ts) < _FEATURED_TTL_SECONDS:
            return cached

    result = _compute_featured(dal)
    with _FEATURED_LOCK:
        _FEATURED_CACHE["data"] = result
        _FEATURED_CACHE["ts"] = time.time()
    return result


def _theme_to_explore_query(theme: dict[str, Any]) -> dict[str, list[str]]:
    """Convert a theme into a serialisable Explore-page filter set
    (the frontend will URL-encode it)."""
    q: dict[str, list[str]] = {}
    if theme.get("tissue_like"):
        # Approximate: just take the first canonical tissue word as a filter.
        # The Explore page treats `tissue` as exact-match, so we send the
        # full text search to maximise recall instead.
        q["text_search"] = [theme["tissue_like"][0]]
    if theme.get("disease_like"):
        # Same idea for disease.
        q.setdefault("text_search", []).extend(theme["disease_like"][:1])
    return q


@router.get(
    "/trending",
    summary="Trending projects (by cell count)",
    description=(
        "Top-N catalogued projects ordered by `total_cells DESC`. "
        "Returns the project_id, source database, title, organism, sample "
        "count, total cell count, publication date, and PMID. `limit` is "
        "clamped to 1–50."
    ),
)
def get_trending(limit: int = 10) -> dict[str, Any]:
    """Top-N projects by total cell count, with their source / title /
    publication date. Cheap, derived from precomputed unified_projects
    aggregates where they exist."""
    started = time.perf_counter()
    dal = get_dal()
    if dal is None:
        return {"projects": [], "elapsed_ms": 0}

    limit = max(1, min(50, int(limit)))

    now = time.time()
    with _TRENDING_LOCK:
        entry = _TRENDING_CACHE.get(limit)
        if entry and (now - entry["ts"]) < _TRENDING_TTL_SECONDS:
            return entry["data"]

    try:
        res = dal.execute(
            "SELECT project_id, source_database, title, organism, "
            "       sample_count, total_cells, publication_date, pmid "
            "FROM unified_projects "
            "WHERE total_cells IS NOT NULL "
            "ORDER BY total_cells DESC LIMIT ?",
            [limit],
        )
        rows = [
            {
                "project_id": r["project_id"],
                "source_database": r["source_database"],
                "title": r["title"],
                "organism": r["organism"],
                "sample_count": r["sample_count"],
                "total_cells": r["total_cells"],
                "publication_date": (r["publication_date"] or "")[:10] if r["publication_date"] else None,
                "pmid": r["pmid"],
            }
            for r in res.rows
        ]
    except Exception as e:
        log.warning("trending_query_failed: %s", e)
        rows = []

    elapsed = int((time.perf_counter() - started) * 1000)
    payload = {"projects": rows, "elapsed_ms": elapsed}

    with _TRENDING_LOCK:
        _TRENDING_CACHE[limit] = {"data": payload, "ts": time.time()}

    return payload
