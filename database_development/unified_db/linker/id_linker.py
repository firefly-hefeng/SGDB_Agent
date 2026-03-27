"""Hard link builder: Create cross-database entity links using ID matching.

Links:
1. PRJNA ↔ GSE via BioProject XML GSE cross-references
2. PMID cross-link across databases
3. DOI cross-link (CellXGene ↔ NCBI)
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class IdLinker(BaseETL):
    SOURCE_DATABASE = 'linker'

    def extract_and_load(self):
        self._link_prjna_gse()
        self._link_pmid()
        self._link_doi()
        self._report()

    def _link_prjna_gse(self):
        """Link 1: PRJNA ↔ GSE via id_mappings GSE cross-references."""
        logger.info("Building PRJNA ↔ GSE links")

        sql = """
        INSERT OR IGNORE INTO entity_links (
            source_entity_type, source_pk, source_id, source_database,
            target_entity_type, target_pk, target_id, target_database,
            relationship_type, confidence, link_method, link_evidence
        )
        SELECT
            'project', ncbi_proj.pk, ncbi_proj.project_id, 'ncbi',
            'project', geo_proj.pk, geo_proj.project_id, 'geo',
            'same_as', 'high',
            'bioproject_xml_geo_center_id',
            'PRJNA ' || ncbi_proj.project_id || ' -> GSE ' || im.id_value
        FROM id_mappings im
        JOIN unified_projects ncbi_proj
            ON im.entity_type = 'project'
            AND im.entity_pk = ncbi_proj.pk
            AND im.id_type = 'gse'
        JOIN unified_projects geo_proj
            ON geo_proj.project_id = im.id_value
            AND geo_proj.source_database = 'geo'
        WHERE ncbi_proj.source_database = 'ncbi'
        """
        cursor = self.conn.execute(sql)
        self.conn.commit()
        count = cursor.rowcount
        logger.info(f"  PRJNA ↔ GSE links created: {count}")
        self.stats['loaded'] += count

    def _link_pmid(self):
        """Link 2: Projects sharing the same PMID across databases."""
        logger.info("Building PMID cross-links")

        sql = """
        INSERT OR IGNORE INTO entity_links (
            source_entity_type, source_pk, source_id, source_database,
            target_entity_type, target_pk, target_id, target_database,
            relationship_type, confidence, link_method, link_evidence
        )
        SELECT
            'project', a.pk, a.project_id, a.source_database,
            'project', b.pk, b.project_id, b.source_database,
            'linked_via_pmid', 'high',
            'pmid_match',
            'Shared PMID: ' || a.pmid
        FROM unified_projects a
        JOIN unified_projects b
            ON a.pmid = b.pmid
            AND a.pk < b.pk
        WHERE a.pmid IS NOT NULL
            AND a.pmid != ''
            AND a.source_database != b.source_database
        """
        cursor = self.conn.execute(sql)
        self.conn.commit()
        count = cursor.rowcount
        logger.info(f"  PMID cross-links created: {count}")
        self.stats['loaded'] += count

    def _link_doi(self):
        """Link 3: Projects sharing the same DOI across databases."""
        logger.info("Building DOI cross-links")

        sql = """
        INSERT OR IGNORE INTO entity_links (
            source_entity_type, source_pk, source_id, source_database,
            target_entity_type, target_pk, target_id, target_database,
            relationship_type, confidence, link_method, link_evidence
        )
        SELECT
            'project', a.pk, a.project_id, a.source_database,
            'project', b.pk, b.project_id, b.source_database,
            'linked_via_doi', 'high',
            'doi_match',
            'Shared DOI: ' || a.doi
        FROM unified_projects a
        JOIN unified_projects b
            ON a.doi = b.doi
            AND a.pk < b.pk
        WHERE a.doi IS NOT NULL
            AND a.doi != ''
            AND a.source_database != b.source_database
        """
        cursor = self.conn.execute(sql)
        self.conn.commit()
        count = cursor.rowcount
        logger.info(f"  DOI cross-links created: {count}")
        self.stats['loaded'] += count

    def _report(self):
        """Report link statistics."""
        logger.info("=== Cross-Link Summary ===")
        for row in self.conn.execute("""
            SELECT relationship_type, confidence,
                   source_database || ' -> ' || target_database as direction,
                   COUNT(*) as cnt
            FROM entity_links
            GROUP BY relationship_type, confidence, direction
            ORDER BY cnt DESC
        """).fetchall():
            logger.info(f"  {row[0]} ({row[1]}): {row[2]} = {row[3]}")

        # Verify: sample a few links
        logger.info("\n=== Sample PRJNA ↔ GSE Links (first 5) ===")
        for row in self.conn.execute("""
            SELECT el.source_id, np.title, el.target_id, gp.title
            FROM entity_links el
            JOIN unified_projects np ON el.source_pk = np.pk
            JOIN unified_projects gp ON el.target_pk = gp.pk
            WHERE el.relationship_type = 'same_as'
            LIMIT 5
        """).fetchall():
            logger.info(f"  {row[0]}: {row[1][:50]}...")
            logger.info(f"  {row[2]}: {row[3][:50]}...")
            logger.info("")


def create_indexes(db_path: str):
    """Create all indexes after bulk data loading."""
    import sqlite3
    logger.info("Creating indexes...")

    conn = sqlite3.connect(db_path)

    indexes = [
        # unified_projects
        "CREATE INDEX IF NOT EXISTS idx_up_project_id ON unified_projects(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_up_source ON unified_projects(source_database)",
        "CREATE INDEX IF NOT EXISTS idx_up_pmid ON unified_projects(pmid)",
        "CREATE INDEX IF NOT EXISTS idx_up_doi ON unified_projects(doi)",
        "CREATE INDEX IF NOT EXISTS idx_up_organism ON unified_projects(organism)",

        # unified_series
        "CREATE INDEX IF NOT EXISTS idx_us_series_id ON unified_series(series_id)",
        "CREATE INDEX IF NOT EXISTS idx_us_source ON unified_series(source_database)",
        "CREATE INDEX IF NOT EXISTS idx_us_project_pk ON unified_series(project_pk)",

        # unified_samples
        "CREATE INDEX IF NOT EXISTS idx_usmp_sample_id ON unified_samples(sample_id)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_source ON unified_samples(source_database)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_series_pk ON unified_samples(series_pk)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_project_pk ON unified_samples(project_pk)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_organism ON unified_samples(organism)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_tissue ON unified_samples(tissue)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_disease ON unified_samples(disease)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_identity_hash ON unified_samples(biological_identity_hash)",
        "CREATE INDEX IF NOT EXISTS idx_usmp_individual ON unified_samples(individual_id)",

        # unified_celltypes
        "CREATE INDEX IF NOT EXISTS idx_uct_sample_pk ON unified_celltypes(sample_pk)",
        "CREATE INDEX IF NOT EXISTS idx_uct_name ON unified_celltypes(cell_type_name)",

        # entity_links
        "CREATE INDEX IF NOT EXISTS idx_el_source ON entity_links(source_entity_type, source_pk)",
        "CREATE INDEX IF NOT EXISTS idx_el_target ON entity_links(target_entity_type, target_pk)",
        "CREATE INDEX IF NOT EXISTS idx_el_relationship ON entity_links(relationship_type)",

        # id_mappings
        "CREATE INDEX IF NOT EXISTS idx_im_lookup ON id_mappings(id_type, id_value)",
        "CREATE INDEX IF NOT EXISTS idx_im_entity ON id_mappings(entity_type, entity_pk)",

        # dedup_candidates
        "CREATE INDEX IF NOT EXISTS idx_dc_status ON dedup_candidates(status)",
    ]

    for idx_sql in indexes:
        idx_name = idx_sql.split('IF NOT EXISTS ')[1].split(' ON')[0]
        logger.info(f"  Creating {idx_name}...")
        conn.execute(idx_sql)

    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    logger.info("All indexes created.")


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    # Run linking
    linker = IdLinker(DB_PATH)
    linker.run()

    # Create indexes
    create_indexes(DB_PATH)
