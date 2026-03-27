#!/usr/bin/env python3
"""
Build ontology cache from OBO files + pre-compute value mapping.

Usage:
    python scripts/build_ontology_cache.py [--skip-value-map]
"""

import sys
import time
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ontology.cache import OntologyCache

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ontologies"
CACHE_PATH = DATA_DIR / "ontology_cache.db"
METADATA_DB = Path(__file__).resolve().parent.parent.parent / "database_development" / "unified_db" / "unified_metadata.db"

OBO_FILES = [
    ("uberon.obo", None),
    ("mondo.obo",  None),
    ("cl.obo",     None),
    ("efo.obo",    None),
]


def main():
    skip_value_map = "--skip-value-map" in sys.argv

    print("=" * 60)
    print("  Building Ontology Cache")
    print("=" * 60)
    print(f"  Cache DB : {CACHE_PATH}")
    print(f"  Data dir : {DATA_DIR}")
    print()

    cache = OntologyCache(CACHE_PATH)
    cache.init_schema()

    t0_total = time.time()

    # Step 1: Parse OBO files
    print("Step 1: Loading OBO ontology files")
    print("-" * 40)
    for filename, source_filter in OBO_FILES:
        obo_path = DATA_DIR / filename
        if not obo_path.exists():
            print(f"  ⚠ {filename} not found, skipping")
            continue
        cache.build_from_obo(obo_path, source_filter)
    print()

    # Step 2: Build value mapping
    if not skip_value_map:
        if not METADATA_DB.exists():
            print(f"⚠ Metadata DB not found at {METADATA_DB}")
            print("  Skipping value mapping. Run with --skip-value-map to suppress.")
        else:
            print("Step 2: Building ontology → DB value mapping")
            print("-" * 40)
            cache.build_value_map(METADATA_DB)
            print()
    else:
        print("Step 2: Skipped (--skip-value-map)")
        print()

    total_time = time.time() - t0_total

    # Stats
    stats = cache.get_stats()
    print("=" * 60)
    print("  Ontology Cache Summary")
    print("=" * 60)
    print(f"  Total terms : {stats['total_terms']:,}")
    for src, cnt in stats["by_source"].items():
        print(f"    {src:10s}: {cnt:>8,}")
    print(f"  Value mappings: {stats['total_mappings']:,}")
    print(f"  Build time    : {total_time:.1f}s")
    print(f"  Cache file    : {CACHE_PATH}")
    print(f"  Cache size    : {CACHE_PATH.stat().st_size / 1024 / 1024:.1f} MB")
    print()

    # Quick test
    print("Quick test:")
    for term in ["brain", "liver", "Alzheimer", "T cell", "10x"]:
        result = cache.lookup_exact(term)
        if result:
            vals = cache.get_db_values(result["ontology_id"], "tissue") or \
                   cache.get_db_values(result["ontology_id"], "disease") or \
                   cache.get_db_values(result["ontology_id"], "cell_type")
            val_str = f", DB values: {len(vals)}" if vals else ""
            print(f"  '{term}' → {result['ontology_id']} ({result['label']}){val_str}")
        else:
            fuzzy = cache.lookup_fuzzy(term, limit=1)
            if fuzzy:
                print(f"  '{term}' → fuzzy: {fuzzy[0]['ontology_id']} ({fuzzy[0]['label']})")
            else:
                print(f"  '{term}' → not found")

    cache.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
