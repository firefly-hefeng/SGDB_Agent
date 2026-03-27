"""Main pipeline orchestrator for the unified metadata database.

Usage:
    python run_pipeline.py --phase all       # Run everything
    python run_pipeline.py --phase phase1    # CellXGene only
    python run_pipeline.py --phase phase2    # NCBI + GEO + links
    python run_pipeline.py --phase phase3    # EBI + small + dedup
    python run_pipeline.py --step cellxgene  # Single step
    python run_pipeline.py --verify          # Run verification queries only
"""

import argparse
import logging
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH, SCHEMA_PATH

logger = logging.getLogger('pipeline')

STEPS = {
    'init': 'Initialize database',
    'cellxgene': 'CellXGene ETL',
    'ncbi': 'NCBI/SRA ETL',
    'geo': 'GEO ETL',
    'links': 'Hard link building',
    'indexes': 'Index creation',
    'ebi': 'EBI ETL',
    'small': 'Small sources ETL',
    'dedup': 'Dedup candidate generation',
    'view': 'Create helper view',
    'verify': 'Run verification',
}

PHASES = {
    'phase1': ['init', 'cellxgene'],
    'phase2': ['ncbi', 'geo', 'links', 'indexes'],
    'phase3': ['ebi', 'small', 'dedup', 'view', 'verify'],
    'all': ['init', 'cellxgene', 'ncbi', 'geo', 'links', 'indexes',
            'ebi', 'small', 'dedup', 'view', 'verify'],
}


def run_step(step: str):
    start = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"STEP: {step} - {STEPS.get(step, '?')}")
    logger.info(f"{'='*60}")

    if step == 'init':
        from create_db import create_database
        create_database(DB_PATH, SCHEMA_PATH, force=True)

    elif step == 'cellxgene':
        from etl.cellxgene_etl import CellXGeneETL
        CellXGeneETL(DB_PATH).run()

    elif step == 'ncbi':
        from etl.ncbi_sra_etl import NcbiSraETL
        NcbiSraETL(DB_PATH).run()

    elif step == 'geo':
        from etl.geo_etl import GeoETL
        GeoETL(DB_PATH).run()

    elif step == 'links':
        from linker.id_linker import IdLinker
        IdLinker(DB_PATH).run()

    elif step == 'indexes':
        from linker.id_linker import create_indexes
        create_indexes(DB_PATH)

    elif step == 'ebi':
        from etl.ebi_etl import EbiETL
        EbiETL(DB_PATH).run()

    elif step == 'small':
        from etl.small_sources_etl import SmallSourcesETL
        SmallSourcesETL(DB_PATH).run()

    elif step == 'dedup':
        from linker.dedup import DedupGenerator
        DedupGenerator(DB_PATH).run()

    elif step == 'view':
        _create_view()

    elif step == 'verify':
        _run_verification()

    elapsed = time.time() - start
    logger.info(f"Step {step} completed in {elapsed:.1f}s\n")


def _create_view():
    """Create the helper view for easy querying."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP VIEW IF EXISTS v_sample_with_hierarchy")
    conn.execute("""
        CREATE VIEW v_sample_with_hierarchy AS
        SELECT
            s.pk as sample_pk, s.sample_id, s.sample_id_type,
            s.source_database as sample_source,
            s.organism, s.tissue, s.tissue_ontology_term_id,
            s.tissue_general,
            s.disease, s.disease_ontology_term_id,
            s.sex, s.age, s.age_unit,
            s.development_stage, s.ethnicity,
            s.individual_id, s.n_cells, s.biological_identity_hash,
            sr.pk as series_pk, sr.series_id, sr.title as series_title,
            sr.assay, sr.cell_count as series_cell_count,
            p.pk as project_pk, p.project_id, p.title as project_title,
            p.pmid, p.doi, p.citation_count
        FROM unified_samples s
        LEFT JOIN unified_series sr ON s.series_pk = sr.pk
        LEFT JOIN unified_projects p ON s.project_pk = p.pk
    """)
    conn.commit()
    conn.close()
    logger.info("Helper view v_sample_with_hierarchy created")


def _run_verification():
    """Run verification queries and print a quality report."""
    conn = sqlite3.connect(DB_PATH)

    print("\n" + "="*70)
    print("  UNIFIED METADATA DATABASE - QUALITY REPORT")
    print("="*70)

    # 1. Record counts by source
    print("\n--- Record Counts by Source ---")
    for table in ['unified_projects', 'unified_series', 'unified_samples', 'unified_celltypes']:
        print(f"\n  {table}:")
        total = 0
        for row in conn.execute(
            f"SELECT source_database, COUNT(*) FROM {table} GROUP BY source_database ORDER BY COUNT(*) DESC"
        ).fetchall():
            print(f"    {row[0]:15s}: {row[1]:>10,}")
            total += row[1]
        print(f"    {'TOTAL':15s}: {total:>10,}")

    # 2. ID mappings
    print("\n--- ID Mappings by Type ---")
    for row in conn.execute(
        "SELECT id_type, COUNT(*) FROM id_mappings GROUP BY id_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"    {row[0]:25s}: {row[1]:>10,}")

    # 3. Entity links
    print("\n--- Entity Links ---")
    for row in conn.execute("""
        SELECT relationship_type, confidence,
               source_database || ' -> ' || target_database,
               COUNT(*)
        FROM entity_links
        GROUP BY relationship_type, confidence, source_database || ' -> ' || target_database
        ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    {row[0]:20s} ({row[1]:6s}): {row[2]:20s} = {row[3]:>6,}")

    # 4. Dedup candidates
    dc_count = conn.execute("SELECT COUNT(*) FROM dedup_candidates").fetchone()[0]
    print(f"\n--- Dedup Candidates: {dc_count:,} ---")
    for row in conn.execute("""
        SELECT entity_a_database || ' <-> ' || entity_b_database, COUNT(*)
        FROM dedup_candidates GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """).fetchall():
        print(f"    {row[0]:30s}: {row[1]:>8,}")

    # 5. Field completeness per source
    print("\n--- Sample Field Completeness ---")
    for src in ['cellxgene', 'ncbi', 'geo', 'ebi', 'hca', 'htan', 'psychad']:
        row = conn.execute(f"""
            SELECT COUNT(*),
                SUM(CASE WHEN tissue IS NOT NULL AND tissue != '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN disease IS NOT NULL AND disease != '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN sex IS NOT NULL AND sex != '' THEN 1 ELSE 0 END),
                SUM(CASE WHEN biological_identity_hash IS NOT NULL THEN 1 ELSE 0 END)
            FROM unified_samples WHERE source_database = ?
        """, (src,)).fetchone()
        if row[0] > 0:
            total = row[0]
            print(f"  {src:12s} (n={total:>8,}): "
                  f"tissue={row[1]*100/total:5.1f}% "
                  f"disease={row[2]*100/total:5.1f}% "
                  f"sex={row[3]*100/total:5.1f}% "
                  f"hash={row[4]*100/total:5.1f}%")

    # 6. Database size
    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\n--- Database Size: {db_size:.1f} MB ---")

    print("\n" + "="*70)
    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Unified Metadata DB Pipeline')
    parser.add_argument('--phase', choices=list(PHASES.keys()),
                        help='Run a phase (group of steps)')
    parser.add_argument('--step', choices=list(STEPS.keys()),
                        help='Run a single step')
    parser.add_argument('--verify', action='store_true',
                        help='Run verification only')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    if args.verify:
        _run_verification()
    elif args.step:
        run_step(args.step)
    elif args.phase:
        for step in PHASES[args.phase]:
            run_step(step)
    else:
        parser.print_help()
