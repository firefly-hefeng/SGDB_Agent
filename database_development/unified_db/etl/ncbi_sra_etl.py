"""NCBI/SRA ETL: Import BioProjects, SRA Studies, BioSamples into unified database.

Data source: Existing SQLite database + CSV files in ncbi_bioproject_sra_data/
Hierarchy: BioProject (PRJNA) → SRA Study (SRP) → BioSample (SAMN) → Experiment (SRX)
"""

import csv
import json
import logging
import os
import re
import sys

# NCBI CSV files contain very large raw_xml fields
csv.field_size_limit(10 * 1024 * 1024)  # 10MB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (NCBI_BIOPROJECTS, NCBI_SRA_STUDIES, NCBI_BIOSAMPLES,
                    NCBI_PUBMED, NCBI_SRA_EXPERIMENTS)
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class NcbiSraETL(BaseETL):
    SOURCE_DATABASE = 'ncbi'

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.pubmed_lookup = {}      # pmid → {doi, journal, citation_count, publication_date}
        self.project_pk_lookup = {}  # accession(PRJNA) → pk

    def extract_and_load(self):
        self._build_pubmed_lookup()
        self._load_bioprojects()
        self._load_sra_studies()
        self._load_biosamples()

    # ── PubMed lookup ─────────────────────────────────────────

    def _build_pubmed_lookup(self):
        logger.info("Building PubMed lookup table")
        count = 0
        with open(NCBI_PUBMED, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                pmid = self.clean_str(row.get('pmid'))
                if pmid:
                    self.pubmed_lookup[pmid] = {
                        'doi': self.clean_str(row.get('doi')),
                        'journal': self.clean_str(row.get('journal')),
                        'citation_count': int(row['citation_count']) if row.get('citation_count') and row['citation_count'].strip() else None,
                        'publication_date': self.clean_str(row.get('publication_date')),
                        'title': self.clean_str(row.get('title')),
                    }
                    count += 1
        logger.info(f"  PubMed lookup: {count} articles")

    # ── BioProjects → unified_projects ────────────────────────

    def _load_bioprojects(self):
        logger.info("Loading NCBI BioProjects → unified_projects")
        batch = []
        count = 0

        with open(NCBI_BIOPROJECTS, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                accession = self.clean_str(row.get('accession'))
                if not accession:
                    self.stats['skipped'] += 1
                    continue

                # Parse publications JSON for PMID
                pmid = None
                pubs_raw = row.get('publications', '')
                if pubs_raw and pubs_raw.strip():
                    try:
                        pubs = json.loads(pubs_raw)
                        if isinstance(pubs, list) and pubs:
                            pmid = str(pubs[0]).strip()
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Lookup PubMed info
                pub_info = self.pubmed_lookup.get(pmid, {})

                # Extract GSE cross-reference from raw_xml
                gse_id = self._extract_gse_from_xml(row.get('raw_xml', ''))

                rec = {
                    'project_id': accession,
                    'project_id_type': 'bioproject',
                    'source_database': self.SOURCE_DATABASE,
                    'title': self.clean_str(row.get('title')),
                    'description': self.clean_str(row.get('description')),
                    'organism': self.normalize_organism(self.clean_str(row.get('organism'))),
                    'pmid': pmid,
                    'doi': pub_info.get('doi'),
                    'publication_date': pub_info.get('publication_date'),
                    'journal': pub_info.get('journal'),
                    'citation_count': pub_info.get('citation_count'),
                    'contact_name': self.clean_str(row.get('submitter_name')),
                    'contact_email': self.clean_str(row.get('submitter_email')),
                    'submitter_organization': self.clean_str(row.get('submitter_organization')),
                    'submission_date': self.clean_str(row.get('submission_date')),
                    'last_update_date': self.clean_str(row.get('last_update_date')),
                    'data_availability': 'open',
                    'access_url': f"https://www.ncbi.nlm.nih.gov/bioproject/{accession}",
                    'raw_metadata': self.safe_json_dumps({
                        k: v for k, v in row.items() if k != 'raw_xml'
                    }),
                    'etl_source_file': 'raw_bioprojects.csv',
                    '_gse_id': gse_id,  # Temp field, removed before insert
                    '_pmid': pmid,
                }
                batch.append(rec)
                count += 1

                if len(batch) >= self.BATCH_SIZE:
                    self._flush_bioproject_batch(batch)
                    batch = []

        if batch:
            self._flush_bioproject_batch(batch)

        self.stats['loaded'] += count
        logger.info(f"  Loaded {count} bioprojects as projects")

    def _flush_bioproject_batch(self, batch):
        """Insert bioprojects and create id_mappings."""
        # Remove temp fields before insert
        insert_rows = []
        for rec in batch:
            gse_id = rec.pop('_gse_id', None)
            pmid = rec.pop('_pmid', None)
            insert_rows.append(rec)

        self.batch_insert('unified_projects', insert_rows)

        # Build id_mappings
        for i, rec in enumerate(batch):
            pk = self.lookup_pk('unified_projects',
                                project_id=insert_rows[i]['project_id'],
                                source_database=self.SOURCE_DATABASE)
            if not pk:
                continue

            self.project_pk_lookup[insert_rows[i]['project_id']] = pk
            self.add_id_mapping('project', pk, 'prjna', insert_rows[i]['project_id'], is_primary=1)

            # GSE cross-reference
            gse_id = self._extract_gse_from_xml(
                batch[i].get('raw_metadata', '') if '_gse_id' not in batch[i] else ''
            )
            # Re-extract since we popped it; use original batch data
            if hasattr(batch[i], '_gse_id_cached'):
                gse_id = batch[i]._gse_id_cached

        self.flush_id_mappings()

    def _load_bioprojects_id_mappings(self):
        """Second pass: create GSE cross-reference id_mappings from raw_xml."""
        logger.info("  Extracting GSE cross-references from BioProject XML")
        gse_count = 0

        with open(NCBI_BIOPROJECTS, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                accession = self.clean_str(row.get('accession'))
                if not accession:
                    continue

                gse_id = self._extract_gse_from_xml(row.get('raw_xml', ''))
                if gse_id:
                    pk = self.project_pk_lookup.get(accession)
                    if pk:
                        self.add_id_mapping('project', pk, 'gse', gse_id)
                        gse_count += 1

                pmid = None
                pubs_raw = row.get('publications', '')
                if pubs_raw and pubs_raw.strip():
                    try:
                        pubs = json.loads(pubs_raw)
                        if isinstance(pubs, list) and pubs:
                            pmid = str(pubs[0]).strip()
                    except (json.JSONDecodeError, ValueError):
                        pass

                if pmid:
                    pk = self.project_pk_lookup.get(accession)
                    if pk:
                        self.add_id_mapping('project', pk, 'pmid', pmid)

        self.flush_id_mappings()
        logger.info(f"  Found {gse_count} GSE cross-references")

    # ── SRA Studies → unified_series ──────────────────────────

    def _load_sra_studies(self):
        logger.info("Loading NCBI SRA Studies → unified_series")

        # Build project_pk_lookup from DB
        cursor = self.conn.execute(
            "SELECT pk, project_id FROM unified_projects WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            self.project_pk_lookup[row[1]] = row[0]

        # Also do GSE id_mappings second pass
        self._load_bioprojects_id_mappings()

        batch = []
        count = 0

        with open(NCBI_SRA_STUDIES, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                study_acc = self.clean_str(row.get('study_accession'))
                if not study_acc:
                    self.stats['skipped'] += 1
                    continue

                bioproject_acc = self.clean_str(row.get('bioproject_accession'))
                # Try to extract from XML if missing
                if not bioproject_acc:
                    bioproject_acc = self._extract_bioproject_from_xml(row.get('raw_xml', ''))

                project_pk = self.project_pk_lookup.get(bioproject_acc) if bioproject_acc else None

                rec = {
                    'series_id': study_acc,
                    'series_id_type': 'sra_study',
                    'source_database': self.SOURCE_DATABASE,
                    'project_pk': project_pk,
                    'project_id': bioproject_acc,
                    'title': self.clean_str(row.get('title')),
                    'description': self.clean_str(row.get('abstract')),
                    'raw_metadata': self.safe_json_dumps(
                        {k: v for k, v in row.items() if k != 'raw_xml'}
                    ),
                    'etl_source_file': 'raw_sra_studies.csv',
                }
                batch.append(rec)
                count += 1

                if len(batch) >= self.BATCH_SIZE:
                    self.batch_insert('unified_series', batch)
                    batch = []

        if batch:
            self.batch_insert('unified_series', batch)

        # Add id_mappings for SRA studies
        cursor = self.conn.execute(
            "SELECT pk, series_id, project_id FROM unified_series WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            self.add_id_mapping('series', row[0], 'srp', row[1], is_primary=1)
            if row[2]:
                self.add_id_mapping('series', row[0], 'prjna', row[2])
        self.flush_id_mappings()

        self.stats['loaded'] += count
        logger.info(f"  Loaded {count} SRA studies as series")

    # ── BioSamples → unified_samples ─────────────────────────

    def _load_biosamples(self):
        logger.info("Loading NCBI BioSamples → unified_samples")

        # Build SRP lookup: bioproject_accession → series_pk
        series_lookup = {}
        cursor = self.conn.execute(
            "SELECT pk, project_id FROM unified_series WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            if row[1]:
                series_lookup[row[1]] = row[0]

        batch = []
        count = 0

        with open(NCBI_BIOSAMPLES, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.stats['processed'] += 1
                accession = self.clean_str(row.get('accession'))
                if not accession:
                    self.stats['skipped'] += 1
                    continue

                bioproject_id = self.clean_str(row.get('bioproject_id'))
                project_pk = self.project_pk_lookup.get(bioproject_id) if bioproject_id else None
                series_pk = series_lookup.get(bioproject_id) if bioproject_id else None

                # Parse attributes JSON
                attrs = self._parse_attributes(row.get('attributes', ''))

                # Extract fields from top-level columns and attributes
                organism = self.normalize_organism(
                    self.clean_str(row.get('organism'))
                )
                tissue = self.clean_str(row.get('tissue')) or attrs.get('tissue')
                cell_type = self.clean_str(row.get('cell_type')) or attrs.get('cell_type')
                disease = self.clean_str(row.get('disease')) or attrs.get('disease')
                sex = self.normalize_sex(
                    self.clean_str(row.get('sex')) or attrs.get('sex')
                )
                age = self.clean_str(row.get('age')) or attrs.get('age')
                ethnicity = self.clean_str(row.get('ethnicity')) or attrs.get('ethnicity')
                dev_stage = self.clean_str(row.get('development_stage')) or attrs.get('development_stage')
                individual_id = attrs.get('individual_id')

                # Extract SRS from raw_xml
                srs_acc = self._extract_srs_from_xml(row.get('raw_xml', ''))

                rec = {
                    'sample_id': accession,
                    'sample_id_type': 'biosample',
                    'source_database': self.SOURCE_DATABASE,
                    'series_pk': series_pk,
                    'series_id': None,
                    'project_pk': project_pk,
                    'project_id': bioproject_id,
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
                    'raw_metadata': self.safe_json_dumps(
                        {k: v for k, v in row.items() if k != 'raw_xml'}
                    ),
                    'etl_source_file': 'raw_biosamples.csv',
                    '_srs_acc': srs_acc,  # Temp
                }
                batch.append(rec)
                count += 1

                if len(batch) >= self.BATCH_SIZE:
                    self._flush_biosample_batch(batch)
                    batch = []
                    self.log_progress('biosamples')

        if batch:
            self._flush_biosample_batch(batch)

        self.stats['loaded'] += count
        logger.info(f"  Loaded {count} biosamples as samples")

    def _flush_biosample_batch(self, batch):
        """Insert biosamples and create id_mappings."""
        insert_rows = []
        srs_map = []
        for rec in batch:
            srs = rec.pop('_srs_acc', None)
            srs_map.append(srs)
            insert_rows.append(rec)

        self.batch_insert('unified_samples', insert_rows)

        for i, rec in enumerate(insert_rows):
            pk = self.lookup_pk('unified_samples',
                                sample_id=rec['sample_id'],
                                source_database=self.SOURCE_DATABASE)
            if not pk:
                continue
            self.add_id_mapping('sample', pk, 'samn', rec['sample_id'], is_primary=1)
            if srs_map[i]:
                self.add_id_mapping('sample', pk, 'srs', srs_map[i])
            if rec.get('project_id'):
                self.add_id_mapping('sample', pk, 'prjna', rec['project_id'])

        self.flush_id_mappings()

    # ── XML parsing helpers ───────────────────────────────────

    @staticmethod
    def _extract_gse_from_xml(raw_xml: str) -> str:
        if not raw_xml:
            return None
        m = re.search(r'center="GEO"[^>]*>(\w+)<', raw_xml)
        if m:
            val = m.group(1)
            if val.startswith('GSE'):
                return val
        m = re.search(r'(GSE\d+)', raw_xml)
        return m.group(1) if m else None

    @staticmethod
    def _extract_bioproject_from_xml(raw_xml: str) -> str:
        if not raw_xml:
            return None
        m = re.search(r'namespace="BioProject"[^>]*>(PRJNA\d+)<', raw_xml)
        if m:
            return m.group(1)
        m = re.search(r'(PRJNA\d+)', raw_xml)
        return m.group(1) if m else None

    @staticmethod
    def _extract_srs_from_xml(raw_xml: str) -> str:
        if not raw_xml:
            return None
        m = re.search(r'<Id db="SRA">(SRS\d+)</Id>', raw_xml)
        return m.group(1) if m else None

    @staticmethod
    def _parse_attributes(attrs_str: str) -> dict:
        """Parse BioSample attributes JSON and extract standard fields."""
        if not attrs_str or attrs_str.strip() in ('', '{}'):
            return {}
        try:
            raw = json.loads(attrs_str)
        except json.JSONDecodeError:
            try:
                raw = json.loads(attrs_str.replace('\n', ' '))
            except json.JSONDecodeError:
                return {}

        if not isinstance(raw, dict):
            return {}

        normalized = {k.strip().lower(): str(v).strip() for k, v in raw.items() if v}

        ATTR_MAP = {
            'tissue': ['tissue', 'organ', 'body site', 'tissue type', 'organism part',
                       'tissue source', 'tissue_type', 'anatomical site'],
            'cell_type': ['cell type', 'cell_type', 'celltype', 'cell lineage',
                          'cell population'],
            'disease': ['disease', 'diagnosis', 'condition', 'health status',
                        'disease state', 'disease_state', 'phenotype'],
            'sex': ['sex', 'gender'],
            'age': ['age', 'donor_age', 'patient age', 'age at diagnosis',
                    'donor age', 'age_years'],
            'ethnicity': ['ethnicity', 'race', 'ancestry', 'ethnic group'],
            'individual_id': ['individual', 'donor', 'patient', 'subject',
                              'donor_id', 'patient_id', 'individual_id', 'subject_id'],
            'development_stage': ['developmental_stage', 'developmental stage',
                                  'dev_stage', 'life stage', 'life_stage'],
        }

        result = {}
        for field, keys in ATTR_MAP.items():
            for key in keys:
                if key in normalized and normalized[key] not in ('', 'not applicable', 'n/a', 'na', 'missing'):
                    result[field] = normalized[key]
                    break

        return result


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    etl = NcbiSraETL(DB_PATH)
    etl.run()
