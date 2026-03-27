"""EBI ETL: Import BioStudies, SCEA experiments, and BioSamples into unified database.

Data sources:
- raw_biostudies/*.json (2196 files) → unified_projects
- raw_scea.json (383 experiments) → unified_series
- raw_biosamples/*.json (160K files) → unified_samples
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import EBI_BIOSTUDIES_DIR, EBI_SCEA, EBI_BIOSAMPLES_DIR
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class EbiETL(BaseETL):
    SOURCE_DATABASE = 'ebi'
    BATCH_SIZE = 5000

    def __init__(self, db_path: str):
        super().__init__(db_path)
        self.project_pk_lookup = {}

    def extract_and_load(self):
        self._load_biostudies()
        self._load_scea()
        self._load_biosamples()

    # ── BioStudies → unified_projects ─────────────────────────

    def _load_biostudies(self):
        logger.info("Loading EBI BioStudies → unified_projects")
        batch = []
        count = 0
        errors = 0

        for fname in sorted(os.listdir(EBI_BIOSTUDIES_DIR)):
            if not fname.endswith('.json'):
                continue

            fpath = os.path.join(EBI_BIOSTUDIES_DIR, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                errors += 1
                continue

            if '_error' in data or 'error' in data:
                errors += 1
                continue

            accno = data.get('accno')
            if not accno:
                errors += 1
                continue

            # Parse attributes
            top_attrs = {}
            for a in data.get('attributes', []):
                if isinstance(a, dict) and 'name' in a:
                    top_attrs[a['name']] = a.get('value', '')

            section = data.get('section', {})
            sect_attrs = {}
            for a in section.get('attributes', []):
                if isinstance(a, dict) and 'name' in a:
                    sect_attrs[a['name']] = a.get('value', '')

            title = sect_attrs.get('Title') or top_attrs.get('Title')
            organism = sect_attrs.get('Organism')
            description = sect_attrs.get('Description')
            release_date = top_attrs.get('ReleaseDate')

            # Extract ENA study link
            ena_acc = None
            for link_item in section.get('links', []):
                links = link_item if isinstance(link_item, list) else [link_item]
                for link in links:
                    if isinstance(link, dict):
                        link_attrs = {}
                        for a in link.get('attributes', []):
                            if isinstance(a, dict):
                                link_attrs[a.get('name', '')] = a.get('value', '')
                        if link_attrs.get('Type') == 'ENA':
                            ena_acc = link.get('url')

            rec = {
                'project_id': accno,
                'project_id_type': 'ebi_study',
                'source_database': self.SOURCE_DATABASE,
                'title': title,
                'description': description[:2000] if description else None,
                'organism': self.normalize_organism(organism),
                'publication_date': release_date,
                'data_availability': 'open',
                'raw_metadata': self.safe_json_dumps({
                    'accno': accno, 'title': title,
                    'organism': organism, 'release_date': release_date,
                    'ena_accession': ena_acc
                }),
                'etl_source_file': fname,
            }
            batch.append((rec, accno, ena_acc))
            count += 1

            if len(batch) >= self.BATCH_SIZE:
                self._flush_biostudies_batch(batch)
                batch = []

        if batch:
            self._flush_biostudies_batch(batch)

        self.stats['loaded'] += count
        logger.info(f"  Loaded {count} biostudies, {errors} errors/skipped")

    def _flush_biostudies_batch(self, batch):
        insert_rows = [item[0] for item in batch]
        self.batch_insert('unified_projects', insert_rows)

        for rec, accno, ena_acc in batch:
            pk = self.lookup_pk('unified_projects',
                                project_id=accno,
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.project_pk_lookup[accno] = pk
                self.add_id_mapping('project', pk, 'e_mtab', accno, is_primary=1)
                if ena_acc:
                    self.add_id_mapping('project', pk, 'erp', ena_acc)
        self.flush_id_mappings()

    # ── SCEA → unified_series ─────────────────────────────────

    def _load_scea(self):
        logger.info("Loading EBI SCEA experiments → unified_series")

        if not os.path.exists(EBI_SCEA):
            logger.warning(f"  SCEA file not found: {EBI_SCEA}")
            return

        with open(EBI_SCEA, 'r', encoding='utf-8') as f:
            scea_data = json.load(f)
        # SCEA JSON is {"experiments": [...]}
        experiments = scea_data.get('experiments', scea_data) if isinstance(scea_data, dict) else scea_data

        batch = []
        for exp in experiments:
            acc = exp.get('experimentAccession')
            if not acc:
                continue

            species = exp.get('species', [])
            if isinstance(species, list):
                species = '; '.join(species)

            # Filter for human only (or include all)
            tech = exp.get('technologyType', [])
            if isinstance(tech, list):
                tech = '; '.join(tech)

            project_pk = self.project_pk_lookup.get(acc)

            rec = {
                'series_id': acc,
                'series_id_type': 'scea_experiment',
                'source_database': self.SOURCE_DATABASE,
                'project_pk': project_pk,
                'project_id': acc,
                'title': exp.get('experimentDescription'),
                'organism': species,
                'assay': tech,
                'cell_count': exp.get('numberOfAssays'),
                'raw_metadata': self.safe_json_dumps(exp),
                'etl_source_file': 'raw_scea.json',
            }
            batch.append(rec)

        loaded = self.batch_insert('unified_series', batch)
        self.conn.commit()

        for rec in batch:
            pk = self.lookup_pk('unified_series',
                                series_id=rec['series_id'],
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.add_id_mapping('series', pk, 'scea', rec['series_id'], is_primary=1)
        self.flush_id_mappings()

        self.stats['loaded'] += loaded
        logger.info(f"  Loaded {loaded} SCEA experiments as series")

    # ── BioSamples → unified_samples ──────────────────────────

    def _load_biosamples(self):
        logger.info("Loading EBI BioSamples → unified_samples")
        logger.info(f"  Scanning {EBI_BIOSAMPLES_DIR}...")

        batch = []
        count = 0
        errors = 0

        entries = sorted(os.scandir(EBI_BIOSAMPLES_DIR), key=lambda e: e.name)
        total_files = sum(1 for e in entries if e.name.endswith('.json'))
        logger.info(f"  Found {total_files} JSON files")

        # Re-scan since we consumed the iterator
        for entry in sorted(os.scandir(EBI_BIOSAMPLES_DIR), key=lambda e: e.name):
            if not entry.name.endswith('.json'):
                continue

            self.stats['processed'] += 1

            try:
                with open(entry.path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                errors += 1
                self.stats['errored'] += 1
                continue

            if '_error' in data or 'error' in data:
                errors += 1
                self.stats['errored'] += 1
                continue

            rec = self._parse_biosample(data, entry.name)
            if rec:
                batch.append(rec)
                count += 1

            if len(batch) >= self.BATCH_SIZE:
                self._flush_biosample_batch(batch)
                batch = []
                self.log_progress('biosamples')

        if batch:
            self._flush_biosample_batch(batch)

        self.stats['loaded'] += count
        logger.info(f"  Loaded {count} biosamples, {errors} errors")

    def _parse_biosample(self, data: dict, filename: str) -> dict:
        chars = data.get('characteristics', {})

        def get_char(key):
            vals = chars.get(key, [])
            if vals and isinstance(vals, list) and len(vals) > 0:
                return vals[0].get('text') if isinstance(vals[0], dict) else str(vals[0])
            return None

        def get_ontology(key):
            vals = chars.get(key, [])
            if vals and isinstance(vals, list) and len(vals) > 0 and isinstance(vals[0], dict):
                terms = vals[0].get('ontologyTerms', [])
                if terms and terms[0]:
                    url = terms[0]
                    parts = url.rstrip('/').split('/')
                    return parts[-1].replace('_', ':') if parts else None
            return None

        accession = data.get('accession')
        if not accession:
            return None

        sra_acc = data.get('sraAccession')
        name = data.get('name', '')

        # Extract study accession from Submitter Id or name
        study_acc = None
        submitter_id = get_char('Submitter Id')
        if submitter_id and ':' in submitter_id:
            study_acc = submitter_id.split(':')[0]
        elif name and ':' in name:
            study_acc = name.split(':')[0]

        project_pk = self.project_pk_lookup.get(study_acc) if study_acc else None

        organism = get_char('organism') or get_char('Organism')
        tissue = get_char('organism part') or get_char('tissue')
        cell_type = get_char('cell type') or get_char('cell_type')
        cell_line = get_char('cell line')
        disease = get_char('disease') or get_char('disease state')
        sex = get_char('sex') or get_char('Sex')
        age = get_char('age') or get_char('Age')
        dev_stage = get_char('developmental stage')
        ethnicity = get_char('ethnicity')
        individual_id = get_char('individual') or get_char('donor') or get_char('subject')

        organism = self.normalize_organism(organism)
        sex = self.normalize_sex(sex)

        return {
            'sample_id': accession,
            'sample_id_type': 'ebi_biosample',
            'source_database': self.SOURCE_DATABASE,
            'project_pk': project_pk,
            'project_id': study_acc,
            'organism': organism,
            'tissue': tissue or cell_line,
            'cell_type': cell_type,
            'disease': disease,
            'sex': sex,
            'age': age,
            'development_stage': dev_stage,
            'ethnicity': ethnicity,
            'individual_id': individual_id,
            'sample_source_type': 'cell_line' if cell_line else 'tissue',
            'biological_identity_hash': self.compute_identity_hash(
                organism=organism, tissue=tissue or cell_line,
                disease=disease, sex=sex,
                individual_id=individual_id,
                development_stage=dev_stage
            ),
            'raw_metadata': self.safe_json_dumps({
                'accession': accession, 'sraAccession': sra_acc,
                'name': name, 'taxId': data.get('taxId'),
                'study': study_acc,
            }),
            'etl_source_file': filename,
            '_sra_acc': sra_acc,
        }

    def _flush_biosample_batch(self, batch):
        insert_rows = []
        sra_map = []
        for rec in batch:
            sra = rec.pop('_sra_acc', None)
            sra_map.append(sra)
            insert_rows.append(rec)

        self.batch_insert('unified_samples', insert_rows)

        for i, rec in enumerate(insert_rows):
            pk = self.lookup_pk('unified_samples',
                                sample_id=rec['sample_id'],
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.add_id_mapping('sample', pk, 'samea', rec['sample_id'], is_primary=1)
                if sra_map[i]:
                    self.add_id_mapping('sample', pk, 'ers', sra_map[i])
        self.flush_id_mappings()


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    etl = EbiETL(DB_PATH)
    etl.run()
