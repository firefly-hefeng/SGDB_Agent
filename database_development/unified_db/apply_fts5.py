#!/usr/bin/env python3
"""
Apply FTS5 full-text search indexes to unified_metadata.db

This script creates FTS5 virtual tables for fast text search on:
- unified_samples (tissue, disease, cell_type, organism, etc.)
- unified_projects (title, description)
- unified_series (title, assay)

FTS5 replaces slow LIKE '%term%' queries with fast MATCH queries.
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "unified_metadata.db"
SQL_PATH = Path(__file__).parent / "add_fts5_indexes.sql"


def main():
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return 1

    if not SQL_PATH.exists():
        print(f"❌ SQL file not found: {SQL_PATH}")
        return 1

    print("=" * 60)
    print("  Adding FTS5 Full-Text Search Indexes")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Check if FTS5 is available
        cursor = conn.execute("PRAGMA compile_options")
        options = [row[0] for row in cursor.fetchall()]
        if not any("FTS5" in opt for opt in options):
            print("❌ FTS5 not available in this SQLite build")
            return 1

        print("✓ FTS5 support detected")
        print()

        # Check existing FTS tables
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%'"
        )
        existing = [row[0] for row in cursor.fetchall()]
        if existing:
            print(f"⚠ Found existing FTS tables: {', '.join(existing)}")
            response = input("Drop and recreate? [y/N]: ").strip().lower()
            if response == 'y':
                for table in existing:
                    print(f"  Dropping {table}...")
                    conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()
            else:
                print("Aborted.")
                return 0

        # Read and execute SQL
        print("Reading SQL script...")
        sql_script = SQL_PATH.read_text()

        print("Creating FTS5 indexes (this may take a few minutes)...")
        t0 = time.time()

        conn.executescript(sql_script)
        conn.commit()

        elapsed = time.time() - t0
        print(f"✓ FTS5 indexes created in {elapsed:.1f}s")
        print()

        # Verify and show stats
        print("=" * 60)
        print("  FTS5 Index Statistics")
        print("=" * 60)

        for table in ["fts_samples", "fts_projects", "fts_series"]:
            try:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"  {table:20s}: {count:>10,} rows")
            except sqlite3.OperationalError:
                print(f"  {table:20s}: NOT CREATED")

        print()

        # Test query
        print("Testing FTS5 search...")
        cursor = conn.execute("""
            SELECT COUNT(*) FROM unified_samples s
            JOIN fts_samples f ON s.pk = f.sample_pk
            WHERE fts_samples MATCH 'tissue:brain'
        """)
        brain_count = cursor.fetchone()[0]
        print(f"  Brain samples found: {brain_count:,}")

        # Compare performance
        print()
        print("Performance comparison:")

        # LIKE query
        t0 = time.time()
        cursor = conn.execute("SELECT COUNT(*) FROM unified_samples WHERE tissue LIKE '%brain%'")
        like_count = cursor.fetchone()[0]
        like_time = (time.time() - t0) * 1000

        # FTS query
        t0 = time.time()
        cursor = conn.execute("""
            SELECT COUNT(*) FROM unified_samples s
            JOIN fts_samples f ON s.pk = f.sample_pk
            WHERE fts_samples MATCH 'tissue:brain'
        """)
        fts_count = cursor.fetchone()[0]
        fts_time = (time.time() - t0) * 1000

        print(f"  LIKE query: {like_time:.0f}ms ({like_count:,} results)")
        print(f"  FTS query:  {fts_time:.0f}ms ({fts_count:,} results)")
        if like_time > 0:
            speedup = like_time / fts_time
            print(f"  Speedup: {speedup:.1f}x faster")

        print()
        print("=" * 60)
        print("  ✓ FTS5 indexes successfully applied!")
        print("=" * 60)

        # Show database size increase
        new_size = DB_PATH.stat().st_size / 1024 / 1024
        print(f"New database size: {new_size:.1f} MB")

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
