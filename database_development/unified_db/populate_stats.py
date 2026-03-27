#!/usr/bin/env python3
"""
Populate precomputed statistics tables for fast query responses.

This script computes and caches common aggregations to avoid
expensive GROUP BY queries on large tables.
"""

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "unified_metadata.db"


def populate_source_stats(conn):
    """Populate stats_by_source table"""
    print("Computing source database statistics...")
    t0 = time.time()

    conn.execute("""
        INSERT OR REPLACE INTO stats_by_source
        (source_database, sample_count, project_count, series_count,
         total_cells, avg_cells_per_sample, samples_with_tissue,
         samples_with_disease, samples_with_cell_type)
        SELECT
            s.source_database,
            COUNT(DISTINCT s.pk) as sample_count,
            COUNT(DISTINCT s.project_pk) as project_count,
            COUNT(DISTINCT s.series_pk) as series_count,
            SUM(CASE WHEN s.n_cells IS NOT NULL THEN s.n_cells ELSE 0 END) as total_cells,
            AVG(s.n_cells) as avg_cells_per_sample,
            SUM(CASE WHEN s.tissue IS NOT NULL THEN 1 ELSE 0 END) as samples_with_tissue,
            SUM(CASE WHEN s.disease IS NOT NULL THEN 1 ELSE 0 END) as samples_with_disease,
            SUM(CASE WHEN s.cell_type IS NOT NULL THEN 1 ELSE 0 END) as samples_with_cell_type
        FROM unified_samples s
        GROUP BY s.source_database
    """)

    count = conn.execute("SELECT COUNT(*) FROM stats_by_source").fetchone()[0]
    print(f"  ✓ {count} sources in {time.time()-t0:.1f}s")


def populate_tissue_stats(conn):
    """Populate stats_by_tissue table"""
    print("Computing tissue statistics...")
    t0 = time.time()

    # Get all tissues with counts
    cursor = conn.execute("""
        SELECT tissue, COUNT(*) as cnt,
               COUNT(DISTINCT source_database) as src_cnt,
               SUM(CASE WHEN n_cells IS NOT NULL THEN n_cells ELSE 0 END) as total_cells
        FROM unified_samples
        WHERE tissue IS NOT NULL
        GROUP BY tissue
        HAVING cnt >= 10
        ORDER BY cnt DESC
        LIMIT 500
    """)

    tissues = cursor.fetchall()

    for tissue, cnt, src_cnt, total_cells in tissues:
        # Get top diseases for this tissue
        cursor = conn.execute("""
            SELECT disease, COUNT(*) as cnt
            FROM unified_samples
            WHERE tissue = ? AND disease IS NOT NULL
            GROUP BY disease
            ORDER BY cnt DESC
            LIMIT 5
        """, [tissue])
        top_diseases = [row[0] for row in cursor.fetchall()]

        conn.execute("""
            INSERT OR REPLACE INTO stats_by_tissue
            (tissue, sample_count, source_count, total_cells, top_diseases)
            VALUES (?, ?, ?, ?, ?)
        """, [tissue, cnt, src_cnt, total_cells, json.dumps(top_diseases)])

    print(f"  ✓ {len(tissues)} tissues in {time.time()-t0:.1f}s")


def populate_disease_stats(conn):
    """Populate stats_by_disease table"""
    print("Computing disease statistics...")
    t0 = time.time()

    cursor = conn.execute("""
        SELECT disease, COUNT(*) as cnt,
               COUNT(DISTINCT source_database) as src_cnt,
               SUM(CASE WHEN n_cells IS NOT NULL THEN n_cells ELSE 0 END) as total_cells
        FROM unified_samples
        WHERE disease IS NOT NULL
        GROUP BY disease
        HAVING cnt >= 10
        ORDER BY cnt DESC
        LIMIT 500
    """)

    diseases = cursor.fetchall()

    for disease, cnt, src_cnt, total_cells in diseases:
        # Get top tissues for this disease
        cursor = conn.execute("""
            SELECT tissue, COUNT(*) as cnt
            FROM unified_samples
            WHERE disease = ? AND tissue IS NOT NULL
            GROUP BY tissue
            ORDER BY cnt DESC
            LIMIT 5
        """, [disease])
        top_tissues = [row[0] for row in cursor.fetchall()]

        conn.execute("""
            INSERT OR REPLACE INTO stats_by_disease
            (disease, sample_count, source_count, total_cells, top_tissues)
            VALUES (?, ?, ?, ?, ?)
        """, [disease, cnt, src_cnt, total_cells, json.dumps(top_tissues)])

    print(f"  ✓ {len(diseases)} diseases in {time.time()-t0:.1f}s")


def populate_assay_stats(conn):
    """Populate stats_by_assay table"""
    print("Computing assay statistics...")
    t0 = time.time()

    conn.execute("""
        INSERT OR REPLACE INTO stats_by_assay
        (assay, series_count, sample_count, total_cells)
        SELECT
            sr.assay,
            COUNT(DISTINCT sr.pk) as series_count,
            COUNT(DISTINCT s.pk) as sample_count,
            SUM(CASE WHEN s.n_cells IS NOT NULL THEN s.n_cells ELSE 0 END) as total_cells
        FROM unified_series sr
        LEFT JOIN unified_samples s ON s.series_pk = sr.pk
        WHERE sr.assay IS NOT NULL
        GROUP BY sr.assay
        HAVING series_count >= 5
    """)

    count = conn.execute("SELECT COUNT(*) FROM stats_by_assay").fetchone()[0]
    print(f"  ✓ {count} assays in {time.time()-t0:.1f}s")


def main():
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return 1

    print("=" * 60)
    print("  Populating Precomputed Statistics Tables")
    print("=" * 60)
    print()

    conn = sqlite3.connect(DB_PATH)

    try:
        # Create tables
        print("Creating statistics tables...")
        with open(Path(__file__).parent / "create_stats_tables.sql") as f:
            conn.executescript(f.read())
        conn.commit()
        print("  ✓ Tables created")
        print()

        # Populate each table
        t0_total = time.time()

        populate_source_stats(conn)
        conn.commit()

        populate_tissue_stats(conn)
        conn.commit()

        populate_disease_stats(conn)
        conn.commit()

        populate_assay_stats(conn)
        conn.commit()

        total_time = time.time() - t0_total

        print()
        print("=" * 60)
        print(f"  ✓ Statistics computed in {total_time:.1f}s")
        print("=" * 60)
        print()

        # Show sample results
        print("Sample statistics:")
        cursor = conn.execute("""
            SELECT source_database, sample_count, total_cells
            FROM stats_by_source
            ORDER BY sample_count DESC
            LIMIT 5
        """)
        print("\nTop 5 sources by sample count:")
        for row in cursor:
            print(f"  {row[0]:15s}: {row[1]:>8,} samples, {row[2]:>12,} cells")

        cursor = conn.execute("""
            SELECT tissue, sample_count
            FROM stats_by_tissue
            ORDER BY sample_count DESC
            LIMIT 5
        """)
        print("\nTop 5 tissues by sample count:")
        for row in cursor:
            print(f"  {row[0]:30s}: {row[1]:>8,} samples")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    exit(main())
