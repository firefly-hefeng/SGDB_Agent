"""Small Sources ETL: Import HCA, HTAN, EGA, PsychAD, BISCP, KPMP, Zenodo, Figshare.

These are smaller datasets that go primarily into unified_projects,
with some also having sample-level data.
"""

import csv
import json
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (HCA_FILE, HTAN_FILE, EGA_FILE, PSYCHAD_FILE,
                    BISCP_DIR, KPMP_DIR, ZENODO_FILE, FIGSHARE_FILE)
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class SmallSourcesETL(BaseETL):
    SOURCE_DATABASE = 'small'

    def extract_and_load(self):
        self._load_hca()
        self._load_htan()
        self._load_ega()
        self._load_psychad()
        self._load_biscp()
        self._load_kpmp()
        self._load_zenodo_figshare()

    # ── HCA ───────────────────────────────────────────────────

    def _load_hca(self):
        logger.info("Loading HCA → projects + samples")
        if not os.path.exists(HCA_FILE):
            logger.warning(f"  File not found: {HCA_FILE}")
            return

        df = pd.read_excel(HCA_FILE)
        logger.info(f"  HCA: {len(df)} rows, {len(df.columns)} columns")

        # Extract unique studies for projects
        study_ids = df['study_id'].dropna().unique() if 'study_id' in df.columns else []
        proj_count = 0
        for sid in study_ids:
            self.insert_one('unified_projects', {
                'project_id': str(sid),
                'project_id_type': 'hca_study',
                'source_database': 'hca',
                'title': f"HCA Study {sid}",
                'organism': 'Homo sapiens',
                'etl_source_file': 'HCA.xlsx',
            })
            proj_count += 1
        self.conn.commit()

        # Samples (donors)
        sample_count = 0
        batch = []
        for _, r in df.iterrows():
            # Try multiple possible ID columns
            donor_id = None
            for col in ['donor_organism.biomaterial_core.biomaterial_id',
                        'donor_organism.uuid', 'biomaterial_core.biomaterial_id']:
                if col in df.columns and pd.notna(r.get(col)):
                    donor_id = str(r[col])
                    break
            if not donor_id:
                continue

            organism = 'Homo sapiens'
            sex = self.normalize_sex(self.clean_str(r.get('donor_organism.sex')))
            age = self.clean_str(r.get('donor_organism.organism_age'))
            age_unit = self.clean_str(r.get('donor_organism.organism_age_unit.text'))
            dev_stage = self.clean_str(r.get('donor_organism.development_stage.text'))
            ethnicity = self.clean_str(r.get('donor_organism.human_specific.ethnicity.text'))
            disease = self.clean_str(r.get('donor_organism.diseases.text'))

            batch.append({
                'sample_id': donor_id,
                'sample_id_type': 'hca_donor',
                'source_database': 'hca',
                'organism': organism,
                'sex': sex,
                'age': age,
                'age_unit': age_unit,
                'development_stage': dev_stage,
                'ethnicity': ethnicity,
                'disease': disease,
                'biological_identity_hash': self.compute_identity_hash(
                    organism=organism, disease=disease, sex=sex,
                    individual_id=donor_id, development_stage=dev_stage
                ),
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'HCA.xlsx',
            })
            sample_count += 1

        self.batch_insert('unified_samples', batch)
        self.conn.commit()
        logger.info(f"  HCA: {proj_count} projects, {sample_count} samples")
        self.stats['loaded'] += proj_count + sample_count

    # ── HTAN ──────────────────────────────────────────────────

    def _load_htan(self):
        logger.info("Loading HTAN → projects + samples")
        if not os.path.exists(HTAN_FILE):
            logger.warning(f"  File not found: {HTAN_FILE}")
            return

        df = pd.read_csv(HTAN_FILE, sep='\t')
        logger.info(f"  HTAN: {len(df)} rows")

        # Projects per Atlas
        atlas_ids = df['Atlas Name'].dropna().unique() if 'Atlas Name' in df.columns else []
        proj_batch = []
        for atlas in atlas_ids:
            proj_batch.append({
                'project_id': str(atlas),
                'project_id_type': 'htan_atlas',
                'source_database': 'htan',
                'title': f"HTAN {atlas}",
                'organism': 'Homo sapiens',
                'etl_source_file': 'HTAN.tsv',
            })
        self.batch_insert('unified_projects', proj_batch)

        # Samples
        sample_batch = []
        for _, r in df.iterrows():
            pid = self.clean_str(r.get('HTAN Participant ID'))
            if not pid:
                continue

            sex = self.normalize_sex(self.clean_str(r.get('Gender')))
            age = self.clean_str(r.get('Age at Diagnosis (years)'))
            disease = self.clean_str(r.get('Primary Diagnosis'))
            tissue = self.clean_str(r.get('Tissue or Organ of Origin'))
            ethnicity_parts = []
            if pd.notna(r.get('Race')):
                ethnicity_parts.append(str(r['Race']))
            if pd.notna(r.get('Ethnicity')):
                ethnicity_parts.append(str(r['Ethnicity']))
            ethnicity = '; '.join(ethnicity_parts) if ethnicity_parts else None

            sample_batch.append({
                'sample_id': pid,
                'sample_id_type': 'htan_participant',
                'source_database': 'htan',
                'organism': 'Homo sapiens',
                'sex': sex,
                'age': age,
                'disease': disease,
                'tissue': tissue,
                'ethnicity': ethnicity,
                'biological_identity_hash': self.compute_identity_hash(
                    organism='Homo sapiens', tissue=tissue, disease=disease,
                    sex=sex, individual_id=pid
                ),
                'raw_metadata': self.safe_json_dumps({
                    'HTAN_Participant_ID': pid,
                    'Atlas_Name': r.get('Atlas Name'),
                    'Primary_Diagnosis': disease,
                }),
                'etl_source_file': 'HTAN.tsv',
            })

        loaded = self.batch_insert('unified_samples', sample_batch)
        self.conn.commit()
        logger.info(f"  HTAN: {len(proj_batch)} projects, {loaded} samples")
        self.stats['loaded'] += len(proj_batch) + loaded

    # ── EGA ───────────────────────────────────────────────────

    def _load_ega(self):
        logger.info("Loading EGA → projects only")
        if not os.path.exists(EGA_FILE):
            logger.warning(f"  File not found: {EGA_FILE}")
            return

        df = pd.read_excel(EGA_FILE)
        logger.info(f"  EGA: {len(df)} rows")

        batch = []
        for _, r in df.iterrows():
            ega_id = self.clean_str(r.get('id'))
            if not ega_id:
                continue
            batch.append({
                'project_id': ega_id,
                'project_id_type': 'ega_dataset',
                'source_database': 'ega',
                'title': self.clean_str(r.get('title')),
                'pmid': self.clean_str(r.get('pubmed')),
                'data_availability': self.clean_str(r.get('open_status')),
                'sample_count': int(r['sample_count']) if pd.notna(r.get('sample_count')) else None,
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'ega_scrna_metadata.xlsx',
            })

        loaded = self.batch_insert('unified_projects', batch)
        self.conn.commit()
        logger.info(f"  EGA: {loaded} projects")
        self.stats['loaded'] += loaded

    # ── PsychAD ───────────────────────────────────────────────

    def _load_psychad(self):
        logger.info("Loading PsychAD → projects + samples")
        if not os.path.exists(PSYCHAD_FILE):
            logger.warning(f"  File not found: {PSYCHAD_FILE}")
            return

        df = pd.read_csv(PSYCHAD_FILE)
        logger.info(f"  PsychAD: {len(df)} rows")

        # One project
        self.insert_one('unified_projects', {
            'project_id': 'PsychAD',
            'project_id_type': 'psychad',
            'source_database': 'psychad',
            'title': 'PsychAD - Psychiatric Disorders Atlas',
            'organism': 'Homo sapiens',
            'etl_source_file': 'PsychAD_media-1.csv',
        })
        self.conn.commit()

        # Samples
        batch = []
        for _, r in df.iterrows():
            donor_id = self.clean_str(r.get('DonorID'))
            if not donor_id:
                continue

            sex = self.normalize_sex(self.clean_str(r.get('sex')))
            age = self.clean_str(r.get('ageDeath'))
            ethnicity = self.clean_str(r.get('Ancestry'))

            # Derive disease from diagnosis columns
            diseases = []
            for col in ['dx_AD', 'crossDis_AD', 'crossDis_SCZ', 'crossDis_DLBD']:
                val = self.clean_str(r.get(col))
                if val and val not in ('0', 'Control', 'control'):
                    diseases.append(val)
            disease = '; '.join(diseases) if diseases else 'control'

            batch.append({
                'sample_id': donor_id,
                'sample_id_type': 'psychad_donor',
                'source_database': 'psychad',
                'organism': 'Homo sapiens',
                'tissue': 'brain',
                'sex': sex,
                'age': age,
                'ethnicity': ethnicity,
                'disease': disease,
                'individual_id': donor_id,
                'biological_identity_hash': self.compute_identity_hash(
                    organism='Homo sapiens', tissue='brain', disease=disease,
                    sex=sex, individual_id=donor_id
                ),
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'PsychAD_media-1.csv',
            })

        loaded = self.batch_insert('unified_samples', batch)
        self.conn.commit()
        logger.info(f"  PsychAD: 1 project, {loaded} samples")
        self.stats['loaded'] += 1 + loaded

    # ── BISCP ─────────────────────────────────────────────────

    def _load_biscp(self):
        logger.info("Loading BISCP → projects only")
        csv_path = None
        proc_dir = os.path.join(BISCP_DIR, 'data', 'processed')
        if os.path.exists(proc_dir):
            for f in os.listdir(proc_dir):
                if f.endswith('.csv') and 'human_studies' in f:
                    csv_path = os.path.join(proc_dir, f)
                    break

        if not csv_path:
            logger.warning("  BISCP CSV not found")
            return

        df = pd.read_csv(csv_path)
        logger.info(f"  BISCP: {len(df)} rows")

        batch = []
        for _, r in df.iterrows():
            acc = self.clean_str(r.get('accession'))
            if not acc:
                continue
            batch.append({
                'project_id': acc,
                'project_id_type': 'scp_study',
                'source_database': 'biscp',
                'title': self.clean_str(r.get('name')),
                'description': self.clean_str(r.get('description')),
                'organism': 'Homo sapiens',
                'total_cells': int(r['cell_count']) if pd.notna(r.get('cell_count')) else None,
                'etl_source_file': os.path.basename(csv_path),
            })

        loaded = self.batch_insert('unified_projects', batch)
        self.conn.commit()
        logger.info(f"  BISCP: {loaded} projects")
        self.stats['loaded'] += loaded

    # ── KPMP ──────────────────────────────────────────────────

    def _load_kpmp(self):
        logger.info("Loading KPMP → projects only")
        csv_path = os.path.join(KPMP_DIR, 'kpmp_series_metadata.csv')
        if not os.path.exists(csv_path):
            logger.warning(f"  File not found: {csv_path}")
            return

        df = pd.read_csv(csv_path)
        logger.info(f"  KPMP: {len(df)} rows")

        batch = []
        for _, r in df.iterrows():
            kid = self.clean_str(r.get('id'))
            if not kid:
                continue
            batch.append({
                'project_id': kid,
                'project_id_type': 'kpmp',
                'source_database': 'kpmp',
                'title': self.clean_str(r.get('title')),
                'organism': 'Homo sapiens',
                'etl_source_file': 'kpmp_series_metadata.csv',
            })

        loaded = self.batch_insert('unified_projects', batch)
        self.conn.commit()
        logger.info(f"  KPMP: {loaded} projects")
        self.stats['loaded'] += loaded

    # ── Zenodo + Figshare ─────────────────────────────────────

    def _load_zenodo_figshare(self):
        for source, fpath in [('zenodo', ZENODO_FILE), ('figshare', FIGSHARE_FILE)]:
            logger.info(f"Loading {source} → projects")
            if not os.path.exists(fpath):
                logger.warning(f"  File not found: {fpath}")
                continue

            df = pd.read_csv(fpath)
            logger.info(f"  {source}: {len(df)} rows")

            batch = []
            for _, r in df.iterrows():
                sid = self.clean_str(r.get('source_id'))
                if not sid:
                    continue
                batch.append({
                    'project_id': str(sid),
                    'project_id_type': source,
                    'source_database': source,
                    'title': self.clean_str(r.get('title')),
                    'doi': self.clean_str(r.get('doi')),
                    'publication_date': self.clean_str(r.get('publication_date')),
                    'organism': self.normalize_organism(self.clean_str(r.get('organism'))),
                    'total_cells': int(r['cell_count']) if pd.notna(r.get('cell_count')) else None,
                    'access_url': self.clean_str(r.get('url')),
                    'raw_metadata': self.safe_json_dumps({
                        'confidence': r.get('confidence'),
                        'confidence_score': r.get('confidence_score'),
                        'has_h5ad': r.get('has_h5ad'),
                        'has_rds': r.get('has_rds'),
                    }),
                    'etl_source_file': os.path.basename(fpath),
                })

            loaded = self.batch_insert('unified_projects', batch)
            self.conn.commit()
            logger.info(f"  {source}: {loaded} projects")
            self.stats['loaded'] += loaded


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    etl = SmallSourcesETL(DB_PATH)
    etl.run()
