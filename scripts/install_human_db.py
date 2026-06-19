"""Install / repair the Phase 16 human-only DB so the agent can run
against it without code changes.

Idempotent — safe to re-run.

What it does:
1. Creates `unified_samples` / `unified_series` / `unified_projects` /
   `unified_celltypes` SQL views aliasing the underlying `human_*`
   tables. The agent's DAL and SQL builder reference the
   `unified_*` names.
2. Drops and re-creates `v_sample_with_hierarchy` with the full
   Phase 15 column list (organism_common, cell_type, treatment,
   cell_line_name, sample_type, …). The version that ships with
   `human_metadata.db` is older and is missing those columns,
   which causes "no such column" errors during bench runs.

Usage:
  python3 -m scripts.install_human_db                  # default path
  python3 -m scripts.install_human_db --db /path/to/human_metadata.db

The default DB path is
`<project_root>/database_development/unified_db/human_metadata.db`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parent / "database_development/unified_db/human_metadata.db"


_VIEW_ALIASES = [
    ("unified_samples",   "human_samples"),
    ("unified_series",    "human_series"),
    ("unified_projects",  "human_projects"),
    ("unified_celltypes", "human_celltypes"),
]


_HIERARCHY_VIEW = """
CREATE VIEW v_sample_with_hierarchy AS
SELECT
    s.pk as sample_pk, s.sample_id, s.sample_id_type,
    s.source_database as sample_source,
    s.organism, s.organism_common, s.organism_normalized,
    s.tissue, s.tissue_ontology_term_id, s.tissue_general,
    s.tissue_standard, s.tissue_system, s.tissue_normalized,
    -- Phase 38: expose the canonical anatomical/lineage roll-ups so the agent can
    -- answer organ-level queries correctly. "brain" must reach prefrontal cortex,
    -- "blood" must reach PBMC, etc. — tissue_standard alone misses subregions.
    s.tissue_standard_l1, s.tissue_standard_leaf,
    s.cell_type, s.cell_type_ontology_term_id, s.cell_type_standard, s.cell_type_lineage,
    s.disease, s.disease_ontology_term_id,
    s.disease_standard, s.disease_standard_l1, s.disease_category, s.disease_normalized,
    s.sex, s.sex_normalized, s.age, s.age_unit,
    s.development_stage, s.ethnicity,
    s.individual_id, s.n_cells,
    s.sample_type, s.cell_line_name, s.control_status,
    s.genotype, s.replicate_type, s.sorting_markers,
    s.time_point, s.treatment,
    sr.pk as series_pk, sr.series_id, sr.title as series_title,
    sr.assay, sr.cell_count as series_cell_count, sr.has_h5ad,
    p.pk as project_pk, p.project_id, p.title as project_title,
    p.pmid, p.doi, p.publication_date, p.citation_count
FROM human_samples s
LEFT JOIN human_series sr ON s.series_pk = sr.pk
LEFT JOIN human_projects p ON s.project_pk = p.pk
"""


def install(db_path: Path) -> None:
    if not db_path.exists():
        print(f"[err] DB not found: {db_path}", file=sys.stderr)
        sys.exit(2)

    con = sqlite3.connect(str(db_path))
    try:
        # Pre-flight: confirm the human_* tables exist.
        present = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'human_%'"
        )}
        for _, src in _VIEW_ALIASES:
            if src not in present:
                print(f"[err] expected source table {src} missing", file=sys.stderr)
                sys.exit(2)

        # 1. View aliases.
        for view, src in _VIEW_ALIASES:
            con.execute(f"DROP VIEW IF EXISTS {view}")
            con.execute(f"CREATE VIEW {view} AS SELECT * FROM {src}")
            n = con.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
            print(f"  [view] {view} ← {src} ({n:,} rows)")

        # 2. Rebuild v_sample_with_hierarchy.
        con.execute("DROP VIEW IF EXISTS v_sample_with_hierarchy")
        con.execute(_HIERARCHY_VIEW)
        cols = [r[1] for r in con.execute("PRAGMA table_info(v_sample_with_hierarchy)")]
        n = con.execute("SELECT COUNT(*) FROM v_sample_with_hierarchy").fetchone()[0]
        print(f"  [view] v_sample_with_hierarchy: {len(cols)} cols, {n:,} rows")

        # Smoke-check: a query the agent issues should now work.
        for col in ("organism_common", "cell_type", "treatment",
                    "cell_line_name", "sample_type"):
            con.execute(f"SELECT {col} FROM v_sample_with_hierarchy LIMIT 1").fetchone()
        print("  [ok]   smoke-check: organism_common / cell_type / treatment "
              "/ cell_line_name / sample_type all reachable")

        con.commit()
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB),
                   help=f"path to human_metadata.db (default: {DEFAULT_DB})")
    args = p.parse_args()
    install(Path(args.db))
    print("\n[done] human_metadata.db is now agent-compatible.")


if __name__ == "__main__":
    main()
