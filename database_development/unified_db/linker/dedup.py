"""Dedup candidate generator: Find potential duplicate entities across databases.

Uses biological identity hash matching for cross-database dedup detection.
All results go to dedup_candidates with status='pending' for review.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class DedupGenerator(BaseETL):
    SOURCE_DATABASE = 'dedup'

    def extract_and_load(self):
        self._hash_dedup_cross_db()
        self._report()

    def _hash_dedup_cross_db(self):
        """Find samples from different databases with matching identity hashes."""
        logger.info("Generating cross-database dedup candidates via identity hash")

        sql = """
        INSERT OR IGNORE INTO dedup_candidates (
            entity_type,
            entity_a_pk, entity_a_id, entity_a_database,
            entity_b_pk, entity_b_id, entity_b_database,
            match_method, confidence_score, match_evidence
        )
        SELECT
            'sample',
            a.pk, a.sample_id, a.source_database,
            b.pk, b.sample_id, b.source_database,
            'biological_identity_hash',
            0.7,
            json_object(
                'hash', a.biological_identity_hash,
                'organism', a.organism,
                'tissue_a', a.tissue, 'tissue_b', b.tissue,
                'disease_a', a.disease, 'disease_b', b.disease,
                'sex_a', a.sex, 'sex_b', b.sex
            )
        FROM unified_samples a
        JOIN unified_samples b
            ON a.biological_identity_hash = b.biological_identity_hash
            AND a.pk < b.pk
        WHERE a.biological_identity_hash IS NOT NULL
            AND a.source_database != b.source_database
        LIMIT 100000
        """
        cursor = self.conn.execute(sql)
        self.conn.commit()
        count = cursor.rowcount
        logger.info(f"  Cross-DB hash dedup candidates: {count}")
        self.stats['loaded'] += count

    def _report(self):
        """Report dedup statistics."""
        logger.info("=== Dedup Summary ===")

        # By database pair
        for row in self.conn.execute("""
            SELECT entity_a_database || ' <-> ' || entity_b_database as pair,
                   COUNT(*) as cnt,
                   ROUND(AVG(confidence_score), 2) as avg_conf
            FROM dedup_candidates
            GROUP BY pair
            ORDER BY cnt DESC
        """).fetchall():
            logger.info(f"  {row[0]}: {row[1]} candidates (avg conf: {row[2]})")

        # Sample some high-quality matches
        logger.info("\n=== Sample Dedup Candidates ===")
        for row in self.conn.execute("""
            SELECT
                dc.entity_a_id, dc.entity_a_database,
                a.tissue, a.disease, a.sex,
                dc.entity_b_id, dc.entity_b_database,
                b.tissue, b.disease, b.sex
            FROM dedup_candidates dc
            JOIN unified_samples a ON dc.entity_a_pk = a.pk
            JOIN unified_samples b ON dc.entity_b_pk = b.pk
            LIMIT 10
        """).fetchall():
            logger.info(f"  {row[0]}({row[1]})[{row[2]}/{row[3]}/{row[4]}] "
                        f"<-> {row[5]}({row[6]})[{row[7]}/{row[8]}/{row[9]}]")


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    gen = DedupGenerator(DB_PATH)
    gen.run()
