"""GEO ETL: Import GEO Series and Samples into unified database.

Data source: merged_samples_with_citation.xlsx (378K samples, 5666 series)
Key challenge: Parsing free-form Characteristics Python dict strings.
"""

import ast
import csv
import logging
import math
import os
import sys

# GEO CSV has very large fields
csv.field_size_limit(10 * 1024 * 1024)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEO_SAMPLES_XLSX, GEO_SAMPLES_CSV, GEO_CHUNK_SIZE
from etl.base import BaseETL

logger = logging.getLogger(__name__)

# Mapping from free-form Characteristics keys to unified fields
GEO_CHAR_KEY_MAP = {
    'tissue': [
        'tissue', 'organ', 'body site', 'tissue type', 'cell tissue',
        'tissue/cell type', 'tissue source', 'anatomical site',
        'organ/tissue', 'organ_source', 'tissue_type', 'tissue of origin',
        'body_site', 'organ part', 'tissue subtype', 'tissue_source',
        'source tissue', 'source_tissue', 'anatomical region',
    ],
    'disease': [
        'disease', 'diagnosis', 'condition', 'health status', 'disease state',
        'disease status', 'phenotype', 'clinical diagnosis', 'pathology',
        'disease_state', 'clinical_diagnosis', 'health_status',
        'disease_type', 'disease condition', 'health state',
    ],
    'sex': [
        'sex', 'gender',
    ],
    'age': [
        'age', 'donor_age', 'patient age', 'age at diagnosis', 'age_at_collection',
        'donor age', 'age (years)', 'age_years', 'age at sampling',
        'age at enrollment', 'age_at_diagnosis', 'age (y)',
    ],
    'cell_type': [
        'cell type', 'cell_type', 'celltype', 'cell lineage',
        'cell population', 'sorted population', 'cell identity',
        'cell_subtype',
    ],
    'ethnicity': [
        'ethnicity', 'race', 'ancestry', 'ethnic group',
        'self-reported ethnicity', 'race/ethnicity',
    ],
    'individual_id': [
        'individual', 'donor', 'patient', 'subject', 'donor_id',
        'patient_id', 'individual_id', 'subject_id', 'participant',
        'donor id', 'patient id', 'sample_source_id',
    ],
    'development_stage': [
        'developmental_stage', 'developmental stage', 'dev_stage',
        'life_stage', 'life stage', 'stage',
    ],
}


class GeoETL(BaseETL):
    SOURCE_DATABASE = 'geo'
    BATCH_SIZE = 5000

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.series_pk_lookup = {}   # GSE → pk in unified_series
        self.project_pk_lookup = {}  # GSE → pk in unified_projects
        self.seen_series = set()     # Track which series we've already inserted

    def extract_and_load(self):
        self._ensure_csv()
        self._load_series_and_samples()

    def _ensure_csv(self):
        """Convert Excel to CSV if not already done."""
        if os.path.exists(GEO_SAMPLES_CSV):
            logger.info(f"CSV already exists: {GEO_SAMPLES_CSV}")
            return

        logger.info("Converting GEO Excel to CSV (this may take a few minutes)...")
        import pandas as pd
        df = pd.read_excel(GEO_SAMPLES_XLSX, dtype={'Series_PubMed_ID': str})
        df.to_csv(GEO_SAMPLES_CSV, index=False)
        logger.info(f"CSV created: {GEO_SAMPLES_CSV}")

    def _load_series_and_samples(self):
        """Stream through CSV, inserting series (first encounter) and all samples."""
        logger.info("Loading GEO data → unified_projects + unified_series + unified_samples")

        sample_batch = []

        with open(GEO_SAMPLES_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.stats['processed'] += 1

                series_id = self.clean_str(row.get('Series_id'))
                sample_id = self.clean_str(row.get('Sample_id'))

                if not series_id or not sample_id:
                    self.stats['skipped'] += 1
                    continue

                # Insert series on first encounter
                if series_id not in self.seen_series:
                    self._insert_series(series_id, row)
                    self.seen_series.add(series_id)

                # Build sample record
                sample_rec = self._build_sample_record(sample_id, series_id, row)
                sample_batch.append(sample_rec)

                if len(sample_batch) >= self.BATCH_SIZE:
                    self._flush_sample_batch(sample_batch)
                    sample_batch = []
                    self.log_progress('samples')

        if sample_batch:
            self._flush_sample_batch(sample_batch)

        logger.info(
            f"  Loaded {len(self.seen_series)} series, "
            f"{self.stats['loaded']} samples"
        )

    def _insert_series(self, series_id: str, row: dict):
        """Insert a GEO series as both project and series."""
        pmid = self.float_to_int_str(row.get('Series_PubMed_ID'))
        citation = None
        cit_raw = row.get('Series_publication_citation_count', '')
        if cit_raw and cit_raw.strip():
            try:
                citation = int(float(cit_raw))
            except (ValueError, OverflowError):
                pass

        # Insert as project
        proj_rec = {
            'project_id': series_id,
            'project_id_type': 'geo_series',
            'source_database': self.SOURCE_DATABASE,
            'title': self.clean_str(row.get('Series_Title')),
            'description': self.clean_str(row.get('Series_Summary')),
            'organism': self.normalize_organism(self.clean_str(row.get('Series_Organism') or row.get('Sample_Organism'))),
            'pmid': pmid,
            'citation_count': citation,
            'contact_name': self.clean_str(row.get('Series_Contact_Name')),
            'contact_email': self.clean_str(row.get('Series_Contact_Email')),
            'submitter_organization': self.clean_str(row.get('Series_Contact_Institute')),
            'submission_date': self.clean_str(row.get('Series_Submission_Date')),
            'last_update_date': self.clean_str(row.get('Series_Last_Update_Date')),
            'publication_date': self.clean_str(row.get('Series_Publication_Date')),
            'data_availability': 'open',
            'access_url': self.clean_str(row.get('Series_GEO_Link')),
            'sample_count': int(row['Series_Sample_Count']) if row.get('Series_Sample_Count') and str(row['Series_Sample_Count']).strip() else None,
            'raw_metadata': self.safe_json_dumps({
                'Series_Title': row.get('Series_Title'),
                'Series_Summary': row.get('Series_Summary'),
                'Series_Overall_Design': row.get('Series_Overall_Design'),
                'Series_SRA_Link': row.get('Series_SRA_Link'),
                'Series_FTP_Link': row.get('Series_FTP_Link'),
            }),
            'etl_source_file': 'merged_samples_with_citation.csv',
        }
        self.insert_one('unified_projects', proj_rec)
        self.conn.commit()

        proj_pk = self.lookup_pk('unified_projects',
                                 project_id=series_id,
                                 source_database=self.SOURCE_DATABASE)
        if proj_pk:
            self.project_pk_lookup[series_id] = proj_pk
            self.add_id_mapping('project', proj_pk, 'gse', series_id, is_primary=1)
            if pmid:
                self.add_id_mapping('project', proj_pk, 'pmid', pmid)

        # Insert as series (same GSE, linking to project)
        series_rec = {
            'series_id': series_id,
            'series_id_type': 'geo_series',
            'source_database': self.SOURCE_DATABASE,
            'project_pk': proj_pk,
            'project_id': series_id,
            'title': self.clean_str(row.get('Series_Title')),
            'organism': self.normalize_organism(self.clean_str(row.get('Series_Organism') or row.get('Sample_Organism'))),
            'raw_metadata': None,  # Already stored in project
            'etl_source_file': 'merged_samples_with_citation.csv',
        }
        self.insert_one('unified_series', series_rec)
        self.conn.commit()

        series_pk = self.lookup_pk('unified_series',
                                   series_id=series_id,
                                   source_database=self.SOURCE_DATABASE)
        if series_pk:
            self.series_pk_lookup[series_id] = series_pk

        self.flush_id_mappings()

    def _build_sample_record(self, sample_id: str, series_id: str, row: dict) -> dict:
        """Build a unified_samples record from a GEO row."""
        # Parse Characteristics
        chars = self._parse_characteristics(row.get('Characteristics', ''))

        # Use Source_name as tissue fallback
        tissue = chars.get('tissue')
        if not tissue:
            source_name = self.clean_str(row.get('Source_name'))
            if source_name and len(source_name) < 100:
                tissue = source_name

        sex = self.normalize_sex(chars.get('sex'))
        disease = chars.get('disease')
        age = chars.get('age')
        cell_type = chars.get('cell_type')
        ethnicity = chars.get('ethnicity')
        individual_id = chars.get('individual_id')
        dev_stage = chars.get('development_stage')

        organism = self.normalize_organism(
            self.clean_str(row.get('Sample_Organism'))
        )

        return {
            'sample_id': sample_id,
            'sample_id_type': 'gsm',
            'source_database': self.SOURCE_DATABASE,
            'series_pk': self.series_pk_lookup.get(series_id),
            'series_id': series_id,
            'project_pk': self.project_pk_lookup.get(series_id),
            'project_id': series_id,
            'organism': organism,
            'tissue': tissue,
            'cell_type': cell_type,
            'disease': disease,
            'sex': sex,
            'age': age,
            'development_stage': dev_stage,
            'ethnicity': ethnicity,
            'individual_id': individual_id,
            'n_cells': None,
            'biological_identity_hash': self.compute_identity_hash(
                organism=organism, tissue=tissue, disease=disease,
                sex=sex, individual_id=individual_id,
                development_stage=dev_stage
            ),
            'raw_metadata': self.safe_json_dumps({
                'Sample_Title': row.get('Sample_Title'),
                'Source_name': row.get('Source_name'),
                'Characteristics': row.get('Characteristics'),
                'Library_strategy': row.get('Library_strategy'),
                'Instrument_model': row.get('Instrument_model'),
            }),
            'etl_source_file': 'merged_samples_with_citation.csv',
        }

    def _flush_sample_batch(self, batch: list):
        """Insert sample batch and create id_mappings."""
        loaded = self.batch_insert('unified_samples', batch)
        self.stats['loaded'] += loaded

        # Add id_mappings for GSM accessions
        for rec in batch:
            pk = self.lookup_pk('unified_samples',
                                sample_id=rec['sample_id'],
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.add_id_mapping('sample', pk, 'gsm', rec['sample_id'], is_primary=1)
        self.flush_id_mappings()

    # ── Characteristics parsing ───────────────────────────────

    @staticmethod
    def _parse_characteristics(char_str: str) -> dict:
        """Parse GEO Characteristics Python dict string.

        Input: "{'tissue': 'liver', 'age': '55', 'Sex': 'Male'}"
        Output: {'tissue': 'liver', 'age': '55', 'sex': 'Male'}
        """
        if not char_str or char_str.strip() in ('', '{}', 'nan'):
            return {}

        try:
            raw_dict = ast.literal_eval(char_str)
        except (SyntaxError, ValueError):
            return {}

        if not isinstance(raw_dict, dict):
            return {}

        # Normalize keys to lowercase
        normalized = {}
        for k, v in raw_dict.items():
            if v is not None:
                normalized[k.strip().lower()] = str(v).strip()

        result = {}
        for unified_field, candidate_keys in GEO_CHAR_KEY_MAP.items():
            for key in candidate_keys:
                if key.lower() in normalized:
                    val = normalized[key.lower()]
                    if val and val.lower() not in ('', 'n/a', 'na', 'not applicable', 'not available', 'unknown', '--'):
                        result[unified_field] = val
                        break

        return result


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    etl = GeoETL(DB_PATH)
    etl.run()
