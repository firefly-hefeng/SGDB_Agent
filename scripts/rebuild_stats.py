#!/usr/bin/env python3
"""Phase 29.A — rebuild precomputed `stats_*` tables to match live data.

After a DB cleanup (e.g. the Phase 29 v2-clean swap), the precomputed
`stats_overall` / `stats_by_*` tables are stale — they reflect a
pre-cleanup row set. The /stats endpoint trusts them blindly, so users
see inflated totals (e.g. 1,009,652 samples shown but only 943,732
queryable).

This script reads live aggregates straight from `unified_samples` /
`unified_projects` / `unified_series` / `unified_celltypes` and writes
them back into the same precomputed tables, preserving the existing
schema so the existing API code keeps working without changes.

Usage:
    python3 scripts/rebuild_stats.py [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import sqlite3
import sys
from pathlib import Path

LOG = logging.getLogger("rebuild_stats")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = (
    PROJECT_ROOT.parent / "database_development/unified_db/human_metadata.db"
).resolve()


def _now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def rebuild_stats_overall(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """Recompute every metric in `stats_overall` from live tables."""
    now = _now()

    def n(sql: str, *params) -> int:
        return con.execute(sql, params).fetchone()[0]

    metrics: dict[str, int] = {}
    metrics["total_projects"] = n("SELECT COUNT(*) FROM unified_projects")
    metrics["total_series"] = n("SELECT COUNT(*) FROM unified_series")
    metrics["total_samples"] = n("SELECT COUNT(*) FROM unified_samples")
    metrics["total_celltypes"] = n("SELECT COUNT(*) FROM unified_celltypes")
    metrics["total_entity_links"] = n("SELECT COUNT(*) FROM entity_links")
    metrics["total_sources"] = n(
        "SELECT COUNT(DISTINCT source_database) FROM unified_samples"
    )

    metrics["distinct_tissues_raw"] = n(
        "SELECT COUNT(DISTINCT tissue) FROM unified_samples WHERE tissue IS NOT NULL"
    )
    metrics["distinct_tissues_standard"] = n(
        "SELECT COUNT(DISTINCT tissue_standard) FROM unified_samples WHERE tissue_standard IS NOT NULL"
    )
    metrics["distinct_diseases_raw"] = n(
        "SELECT COUNT(DISTINCT disease) FROM unified_samples WHERE disease IS NOT NULL"
    )
    metrics["distinct_diseases_standard"] = n(
        "SELECT COUNT(DISTINCT disease_standard) FROM unified_samples WHERE disease_standard IS NOT NULL"
    )

    # Coverage metrics (how many samples have a standardised value).
    metrics["samples_with_tissue_standard"] = n(
        "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard IS NOT NULL"
    )
    metrics["samples_with_disease_standard"] = n(
        "SELECT COUNT(*) FROM unified_samples WHERE disease_standard IS NOT NULL"
    )
    metrics["samples_with_sex"] = n(
        "SELECT COUNT(*) FROM unified_samples WHERE sex_normalized IS NOT NULL"
    )
    metrics["samples_with_age"] = n(
        "SELECT COUNT(*) FROM unified_samples WHERE age IS NOT NULL"
    )

    # New (v2-clean) coverage metrics — optional columns.
    optional_columns = [
        ("samples_with_tissue_l1", "tissue_standard_l1"),
        ("samples_with_disease_l1", "disease_standard_l1"),
        ("samples_with_cell_type_standard", "cell_type_standard"),
        ("samples_with_cell_lineage", "cell_type_lineage"),
        ("samples_with_ancestry_category", "ancestry_category"),
        ("samples_with_dev_stage_category", "dev_stage_category"),
        ("samples_with_treatment_status", "treatment_status"),
        ("samples_with_genotype_status", "genotype_status"),
        ("samples_with_individual_id_namespaced", "individual_id_namespaced"),
    ]
    for metric, col in optional_columns:
        try:
            metrics[metric] = n(
                f"SELECT COUNT(*) FROM unified_samples WHERE {col} IS NOT NULL"
            )
        except sqlite3.OperationalError:
            # column missing on this DB build — skip the metric quietly.
            continue

    # Distinct counts for new columns
    for metric, col in [
        ("distinct_tissues_l1", "tissue_standard_l1"),
        ("distinct_tissues_leaf", "tissue_standard_leaf"),
        ("distinct_diseases_l1", "disease_standard_l1"),
        ("distinct_cell_types_standard", "cell_type_standard"),
        ("distinct_cell_lineages", "cell_type_lineage"),
        ("distinct_assay_chemistry", "assay_chemistry"),
        ("distinct_assay_modality", "assay_modality"),
    ]:
        try:
            table = "unified_series" if col.startswith("assay") else "unified_samples"
            metrics[metric] = n(
                f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE {col} IS NOT NULL"
            )
        except sqlite3.OperationalError:
            continue
    try:
        metrics["distinct_seq_manufacturer"] = n(
            "SELECT COUNT(DISTINCT seq_manufacturer) FROM unified_series "
            "WHERE seq_manufacturer IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass

    LOG.info("Computed %d stats_overall metrics", len(metrics))
    for k in sorted(metrics):
        LOG.info("  %-40s %12d", k, metrics[k])

    if dry_run:
        LOG.info("[dry-run] skipping write to stats_overall")
        return

    # Truncate & write — keep the schema (metric, value, last_updated).
    con.execute("DELETE FROM stats_overall")
    con.executemany(
        "INSERT INTO stats_overall (metric, value, last_updated) VALUES (?, ?, ?)",
        [(k, v, now) for k, v in metrics.items()],
    )
    LOG.info("Wrote %d rows to stats_overall", len(metrics))


def rebuild_stats_by_source(con: sqlite3.Connection, dry_run: bool = False) -> None:
    now = _now()
    rows = con.execute(
        "SELECT s.source_database AS source_database, "
        "COUNT(*) AS sample_count, "
        "COUNT(DISTINCT s.project_pk) AS project_count, "
        "COUNT(DISTINCT s.series_pk) AS series_count, "
        "SUM(COALESCE(s.n_cells, 0)) AS total_cells, "
        "AVG(s.n_cells) AS avg_cells_per_sample, "
        "SUM(CASE WHEN s.tissue IS NOT NULL THEN 1 ELSE 0 END) AS samples_with_tissue, "
        "SUM(CASE WHEN s.disease IS NOT NULL THEN 1 ELSE 0 END) AS samples_with_disease, "
        "SUM(CASE WHEN s.cell_type IS NOT NULL THEN 1 ELSE 0 END) AS samples_with_cell_type "
        "FROM unified_samples s GROUP BY s.source_database "
        "ORDER BY sample_count DESC"
    ).fetchall()
    LOG.info("stats_by_source: %d source databases", len(rows))
    for r in rows:
        LOG.info(
            "  %-12s samples=%7d projects=%5d series=%5d cells=%12d",
            r[0], r[1], r[2], r[3], r[4] or 0,
        )

    if dry_run:
        return

    con.execute("DELETE FROM stats_by_source")
    con.executemany(
        "INSERT INTO stats_by_source "
        "(source_database, sample_count, project_count, series_count, "
        " total_cells, avg_cells_per_sample, "
        " samples_with_tissue, samples_with_disease, samples_with_cell_type, "
        " last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(*r, now) for r in rows],
    )
    LOG.info("Wrote %d rows to stats_by_source", len(rows))


def rebuild_stats_by_tissue(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """stats_by_tissue schema: tissue, sample_count, source_count, total_cells,
    top_diseases, last_updated. source_count and sample_count are NOT NULL."""
    now = _now()
    rows = con.execute(
        "SELECT tissue, "
        "       COUNT(*) AS sample_count, "
        "       COUNT(DISTINCT source_database) AS source_count, "
        "       SUM(COALESCE(n_cells, 0)) AS total_cells "
        "FROM unified_samples WHERE tissue IS NOT NULL "
        "GROUP BY tissue HAVING COUNT(*) > 0 "
        "ORDER BY sample_count DESC LIMIT 500"
    ).fetchall()
    LOG.info("stats_by_tissue: top %d", len(rows))

    if dry_run:
        return

    con.execute("DELETE FROM stats_by_tissue")
    con.executemany(
        "INSERT INTO stats_by_tissue "
        "(tissue, sample_count, source_count, total_cells, last_updated) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r[0], r[1], r[2], r[3], now) for r in rows],
    )
    LOG.info("Wrote %d rows to stats_by_tissue", len(rows))


def rebuild_stats_by_disease(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """stats_by_disease schema mirrors stats_by_tissue."""
    now = _now()
    rows = con.execute(
        "SELECT disease, "
        "       COUNT(*) AS sample_count, "
        "       COUNT(DISTINCT source_database) AS source_count, "
        "       SUM(COALESCE(n_cells, 0)) AS total_cells "
        "FROM unified_samples WHERE disease IS NOT NULL "
        "GROUP BY disease HAVING COUNT(*) > 0 "
        "ORDER BY sample_count DESC LIMIT 500"
    ).fetchall()
    LOG.info("stats_by_disease: top %d", len(rows))

    if dry_run:
        return

    con.execute("DELETE FROM stats_by_disease")
    con.executemany(
        "INSERT INTO stats_by_disease "
        "(disease, sample_count, source_count, total_cells, last_updated) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r[0], r[1], r[2], r[3], now) for r in rows],
    )
    LOG.info("Wrote %d rows to stats_by_disease", len(rows))


def rebuild_stats_by_organism(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """Rebuild stats_by_organism from organism_normalized (post-cleanup column)."""
    now = _now()
    cols = [c[1] for c in con.execute("PRAGMA table_info(stats_by_organism)").fetchall()]
    rows = con.execute(
        "SELECT organism, sample_count FROM ("
        "  SELECT COALESCE(organism_normalized, organism, 'unknown') AS organism, "
        "         COUNT(*) AS sample_count "
        "  FROM unified_samples "
        "  GROUP BY COALESCE(organism_normalized, organism, 'unknown')"
        ") WHERE sample_count > 0 ORDER BY sample_count DESC"
    ).fetchall()
    LOG.info("stats_by_organism: %d rows", len(rows))
    for r in rows[:8]:
        LOG.info("  %s %s", r[0], r[1])
    if dry_run:
        return
    con.execute("DELETE FROM stats_by_organism")
    if "last_updated" in cols:
        con.executemany(
            "INSERT INTO stats_by_organism (organism, sample_count, last_updated) "
            "VALUES (?, ?, ?)",
            [(r[0], r[1], now) for r in rows],
        )
    else:
        con.executemany(
            "INSERT INTO stats_by_organism (organism, sample_count) VALUES (?, ?)",
            [tuple(r) for r in rows],
        )
    LOG.info("Wrote %d rows to stats_by_organism", len(rows))


def rebuild_stats_by_sex(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """Rebuild stats_by_sex from sex_normalized."""
    now = _now()
    cols = [c[1] for c in con.execute("PRAGMA table_info(stats_by_sex)").fetchall()]
    rows = con.execute(
        "SELECT sex, sample_count FROM ("
        "  SELECT COALESCE(sex_normalized, sex, 'unknown') AS sex, "
        "         COUNT(*) AS sample_count "
        "  FROM unified_samples "
        "  GROUP BY COALESCE(sex_normalized, sex, 'unknown')"
        ") WHERE sample_count > 0 ORDER BY sample_count DESC"
    ).fetchall()
    LOG.info("stats_by_sex: %d rows", len(rows))
    if dry_run:
        return
    con.execute("DELETE FROM stats_by_sex")
    if "last_updated" in cols:
        con.executemany(
            "INSERT INTO stats_by_sex (sex, sample_count, last_updated) VALUES (?, ?, ?)",
            [(r[0], r[1], now) for r in rows],
        )
    else:
        con.executemany(
            "INSERT INTO stats_by_sex (sex, sample_count) VALUES (?, ?)",
            [tuple(r) for r in rows],
        )
    LOG.info("Wrote %d rows to stats_by_sex", len(rows))


def rebuild_stats_by_assay(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """Rebuild stats_by_assay from unified_series.assay → joined unified_samples.

    Schema: assay, series_count, sample_count, total_cells, last_updated.
    """
    now = _now()
    cols = [c[1] for c in con.execute("PRAGMA table_info(stats_by_assay)").fetchall()]
    rows = con.execute(
        "SELECT sr.assay AS assay, "
        "       COUNT(DISTINCT sr.pk) AS series_count, "
        "       COUNT(s.pk) AS sample_count, "
        "       SUM(COALESCE(s.n_cells, 0)) AS total_cells "
        "FROM unified_series sr "
        "LEFT JOIN unified_samples s ON s.series_pk = sr.pk "
        "WHERE sr.assay IS NOT NULL AND sr.assay != '' "
        "GROUP BY sr.assay HAVING COUNT(*) > 0 "
        "ORDER BY sample_count DESC LIMIT 100"
    ).fetchall()
    LOG.info("stats_by_assay: %d rows", len(rows))
    if dry_run:
        return
    con.execute("DELETE FROM stats_by_assay")
    if "last_updated" in cols and "total_cells" in cols and "series_count" in cols:
        con.executemany(
            "INSERT INTO stats_by_assay (assay, series_count, sample_count, total_cells, last_updated) "
            "VALUES (?, ?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3], now) for r in rows],
        )
    elif "last_updated" in cols:
        con.executemany(
            "INSERT INTO stats_by_assay (assay, sample_count, last_updated) VALUES (?, ?, ?)",
            [(r[0], r[2], now) for r in rows],
        )
    else:
        con.executemany(
            "INSERT INTO stats_by_assay (assay, sample_count) VALUES (?, ?)",
            [(r[0], r[2]) for r in rows],
        )
    LOG.info("Wrote %d rows to stats_by_assay", len(rows))


def rebuild_stats_by_year(con: sqlite3.Connection, dry_run: bool = False) -> None:
    """Rebuild stats_by_year by parsing the year out of unified_projects.publication_date.

    The previous build had a bug — it stored the *month abbreviation* (`'Jan '`,
    `'Feb '`, …) in the year column. The frontend chart renders that as
    gibberish on the time-series axis. We now extract the leading 4-digit
    year token from publication_date and project the count by year.
    """
    now = _now()
    cols = [c[1] for c in con.execute("PRAGMA table_info(stats_by_year)").fetchall()]
    rows = con.execute(
        "SELECT SUBSTR(publication_date, 1, 4) AS year, COUNT(*) AS project_count "
        "FROM unified_projects "
        "WHERE publication_date IS NOT NULL AND publication_date != '' "
        "  AND SUBSTR(publication_date, 1, 4) GLOB '20[0-9][0-9]' "
        "GROUP BY year ORDER BY year ASC"
    ).fetchall()
    LOG.info("stats_by_year: %d year buckets", len(rows))
    for r in rows[:6]: LOG.info("  %s: %s", r[0], r[1])
    if dry_run:
        return
    con.execute("DELETE FROM stats_by_year")
    if "last_updated" in cols:
        con.executemany(
            "INSERT INTO stats_by_year (year, project_count, last_updated) VALUES (?, ?, ?)",
            [(r[0], r[1], now) for r in rows],
        )
    else:
        con.executemany(
            "INSERT INTO stats_by_year (year, project_count) VALUES (?, ?)",
            [tuple(r) for r in rows],
        )
    LOG.info("Wrote %d rows to stats_by_year", len(rows))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help=f"path to human_metadata.db (default: {DEFAULT_DB})")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute but don't write")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = Path(args.db).resolve()
    if not db.exists():
        LOG.error("DB not found: %s", db)
        return 2

    LOG.info("Rebuilding stats in %s (dry_run=%s)", db, args.dry_run)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN")
        rebuild_stats_overall(con, dry_run=args.dry_run)
        rebuild_stats_by_source(con, dry_run=args.dry_run)
        rebuild_stats_by_tissue(con, dry_run=args.dry_run)
        rebuild_stats_by_disease(con, dry_run=args.dry_run)
        rebuild_stats_by_organism(con, dry_run=args.dry_run)
        rebuild_stats_by_sex(con, dry_run=args.dry_run)
        rebuild_stats_by_assay(con, dry_run=args.dry_run)
        rebuild_stats_by_year(con, dry_run=args.dry_run)
        if args.dry_run:
            con.rollback()
            LOG.info("[dry-run] rolled back")
        else:
            con.commit()
            LOG.info("Committed.")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
