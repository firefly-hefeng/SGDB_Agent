# `api/routes/_archive/` — superseded explore route variants

The files in this folder are kept for historical reference only; they
are not imported by `api/main.py` and are not part of the live API.

| File | Status |
|---|---|
| `explore_original.py` | Phase ≤ 13 simple list endpoint, no facets, no caching. Superseded by `explore.py`. |
| `explore_optimized.py` | Phase 14 caching prototype that was folded into `explore.py`. |

Moved here in Phase 28 (2026-05-16) to keep `api/routes/` clean while
preserving the diff history. Safe to delete after the next release if
nobody has cited them.
