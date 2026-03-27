"""CellXGene ETL: Import collections, datasets, and samples into unified database.

CellXGene is the highest quality source with ontology annotations and zero null core fields.
Hierarchy: Collection (project) → Dataset (series) → Sample (sample/donor)
"""

import pandas as pd
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (CELLXGENE_COLLECTIONS, CELLXGENE_DATASETS,
                    CELLXGENE_SAMPLES)
from etl.base import BaseETL

logger = logging.getLogger(__name__)


class CellXGeneETL(BaseETL):
    SOURCE_DATABASE = 'cellxgene'

    def extract_and_load(self):
        self._load_collections()
        self._load_datasets()
        self._load_samples()

    # ── Collections → unified_projects ────────────────────────

    def _load_collections(self):
        logger.info("Loading CellXGene collections → unified_projects")
        df = pd.read_csv(CELLXGENE_COLLECTIONS)

        rows = []
        for _, r in df.iterrows():
            doi = self.clean_str(r.get('doi'))
            pub_date = None
            pm_ts = r.get('pm_published_at')
            if pm_ts and not pd.isna(pm_ts):
                try:
                    from datetime import datetime as dt
                    pub_date = dt.fromtimestamp(float(pm_ts)).strftime('%Y-%m-%d')
                except (ValueError, OSError):
                    pass

            row = {
                'project_id': r['collection_id'],
                'project_id_type': 'cellxgene_collection',
                'source_database': self.SOURCE_DATABASE,
                'title': self.clean_str(r.get('name')),
                'description': self.clean_str(r.get('description')),
                'organism': 'Homo sapiens',
                'doi': doi,
                'publication_date': pub_date,
                'journal': self.clean_str(r.get('pm_journal')),
                'citation_count': int(r['max_dataset_citation']) if pd.notna(r.get('max_dataset_citation')) else None,
                'contact_name': self.clean_str(r.get('contact_name')),
                'contact_email': self.clean_str(r.get('contact_email')),
                'sample_count': int(r['n_samples']) if pd.notna(r.get('n_samples')) else None,
                'total_cells': int(r['total_cells']) if pd.notna(r.get('total_cells')) else None,
                'data_availability': 'open',
                'access_url': self.clean_str(r.get('collection_url')),
                'submission_date': self.clean_str(r.get('created_at')),
                'last_update_date': self.clean_str(r.get('revised_at')),
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'collections_hierarchy.csv',
            }
            rows.append(row)

        loaded = self.batch_insert('unified_projects', rows)
        self.conn.commit()
        logger.info(f"  Loaded {loaded} collections as projects")

        # Add id_mappings
        for row in rows:
            pk = self.lookup_pk('unified_projects',
                                project_id=row['project_id'],
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.add_id_mapping('project', pk, 'cellxgene_collection', row['project_id'], is_primary=1)
                if row['doi']:
                    self.add_id_mapping('project', pk, 'doi', row['doi'])
        self.flush_id_mappings()
        self.stats['loaded'] += loaded

    # ── Datasets → unified_series ─────────────────────────────

    def _load_datasets(self):
        logger.info("Loading CellXGene datasets → unified_series")
        df = pd.read_csv(CELLXGENE_DATASETS)

        # Build collection_id → project_pk lookup
        project_lookup = {}
        cursor = self.conn.execute(
            "SELECT pk, project_id FROM unified_projects WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            project_lookup[row[1]] = row[0]

        rows = []
        for _, r in df.iterrows():
            collection_id = str(r['collection_id'])
            project_pk = project_lookup.get(collection_id)

            # Parse assay: "10x 3' v3 (EFO:0009922)" → assay, ontology
            assay_raw = self.clean_str(r.get('assays'))
            assay, assay_ontology = self._parse_ontology_field(assay_raw)

            row = {
                'series_id': r['dataset_id'],
                'series_id_type': 'cellxgene_dataset',
                'source_database': self.SOURCE_DATABASE,
                'project_pk': project_pk,
                'project_id': collection_id,
                'title': self.clean_str(r.get('title')),
                'organism': self._extract_organism(r.get('organisms')),
                'assay': assay,
                'assay_ontology_term_id': assay_ontology,
                'suspension_type': self.clean_str(r.get('suspension_types')),
                'cell_count': int(r['cell_count']) if pd.notna(r.get('cell_count')) else None,
                'mean_genes_per_cell': float(r['mean_genes_per_cell']) if pd.notna(r.get('mean_genes_per_cell')) else None,
                'sample_count': int(r['n_samples']) if pd.notna(r.get('n_samples')) else None,
                'has_h5ad': 1 if pd.notna(r.get('asset_h5ad_url')) and r.get('asset_h5ad_url') else 0,
                'has_rds': 1 if pd.notna(r.get('asset_rds_url')) and r.get('asset_rds_url') else 0,
                'asset_h5ad_url': self.clean_str(r.get('asset_h5ad_url')),
                'asset_rds_url': self.clean_str(r.get('asset_rds_url')),
                'explorer_url': self.clean_str(r.get('explorer_url')),
                'citation_count': int(r['citation_count']) if pd.notna(r.get('citation_count')) else None,
                'citation_source': self.clean_str(r.get('citation_source')),
                'published_at': self.clean_str(r.get('published_at')),
                'revised_at': self.clean_str(r.get('revised_at')),
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'datasets_hierarchy_final.csv',
            }
            rows.append(row)

        loaded = self.batch_insert('unified_series', rows)
        self.conn.commit()
        logger.info(f"  Loaded {loaded} datasets as series")

        # Add id_mappings
        for row in rows:
            pk = self.lookup_pk('unified_series',
                                series_id=row['series_id'],
                                source_database=self.SOURCE_DATABASE)
            if pk:
                self.add_id_mapping('series', pk, 'cellxgene_dataset', row['series_id'], is_primary=1)
        self.flush_id_mappings()
        self.stats['loaded'] += loaded

    # ── Samples → unified_samples + unified_celltypes ─────────

    def _load_samples(self):
        logger.info("Loading CellXGene samples → unified_samples + unified_celltypes")
        df = pd.read_csv(CELLXGENE_SAMPLES)

        # Build lookups
        series_lookup = {}
        cursor = self.conn.execute(
            "SELECT pk, series_id FROM unified_series WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            series_lookup[row[1]] = row[0]

        project_lookup = {}
        cursor = self.conn.execute(
            "SELECT pk, project_id FROM unified_projects WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            project_lookup[row[1]] = row[0]

        sample_batch = []
        celltype_pending = []  # (sample_id, cell_type_list)

        for idx, r in df.iterrows():
            self.stats['processed'] += 1
            dataset_id = str(r['dataset_id'])
            collection_id = str(r['collection_id'])
            raw_sample_id = str(r['sample_id'])

            # Composite sample_id for global uniqueness
            sample_id = f"{dataset_id}:{raw_sample_id}"

            series_pk = series_lookup.get(dataset_id)
            project_pk = project_lookup.get(collection_id)

            # Parse disease: handle "||" and ";" separators
            disease, disease_ont = self._parse_disease(r.get('disease'), r.get('disease_ontology_term_id'))

            # Parse age from development_stage
            age, age_unit = self.parse_age_from_dev_stage(self.clean_str(r.get('development_stage')))

            # Determine cell_type summary
            cell_type_list_raw = self.clean_str(r.get('cell_type_list'))
            cell_type_summary = self._summarize_cell_type(cell_type_list_raw)

            row = {
                'sample_id': sample_id,
                'sample_id_type': 'cellxgene_sample',
                'source_database': self.SOURCE_DATABASE,
                'series_pk': series_pk,
                'series_id': dataset_id,
                'project_pk': project_pk,
                'project_id': collection_id,
                'organism': 'Homo sapiens',
                'tissue': self.clean_str(r.get('tissue')),
                'tissue_ontology_term_id': self.clean_str(r.get('tissue_ontology_term_id')),
                'tissue_general': self.clean_str(r.get('tissue_general')),
                'cell_type': cell_type_summary,
                'disease': disease,
                'disease_ontology_term_id': disease_ont,
                'sex': self.normalize_sex(self.clean_str(r.get('sex'))),
                'sex_ontology_term_id': self.clean_str(r.get('sex_ontology_term_id')),
                'age': age,
                'age_unit': age_unit,
                'development_stage': self.clean_str(r.get('development_stage')),
                'development_stage_ontology_term_id': self.clean_str(r.get('development_stage_ontology_term_id')),
                'ethnicity': self.clean_str(r.get('self_reported_ethnicity')),
                'ethnicity_ontology_term_id': self.clean_str(r.get('self_reported_ethnicity_ontology_term_id')),
                'individual_id': raw_sample_id,
                'sample_source_type': self._map_tissue_type(r.get('tissue_type')),
                'is_primary_data': 1 if str(r.get('is_primary_data', '')).lower() == 'true' else 0,
                'suspension_type': self.clean_str(r.get('suspension_type')),
                'tissue_type': self.clean_str(r.get('tissue_type')),
                'n_cells': int(r['n_cells']) if pd.notna(r.get('n_cells')) else None,
                'n_cell_types': int(r['n_cell_types']) if pd.notna(r.get('n_cell_types')) else None,
                'expr_raw_sum_mean': float(r['expr_raw_sum_mean']) if pd.notna(r.get('expr_raw_sum_mean')) else None,
                'expr_raw_sum_min': float(r['expr_raw_sum_min']) if pd.notna(r.get('expr_raw_sum_min')) else None,
                'expr_raw_sum_max': float(r['expr_raw_sum_max']) if pd.notna(r.get('expr_raw_sum_max')) else None,
                'expr_nnz_mean': float(r['expr_nnz_mean']) if pd.notna(r.get('expr_nnz_mean')) else None,
                'biological_identity_hash': self.compute_identity_hash(
                    organism='Homo sapiens',
                    tissue=self.clean_str(r.get('tissue')),
                    disease=disease,
                    sex=self.normalize_sex(self.clean_str(r.get('sex'))),
                    individual_id=raw_sample_id,
                    development_stage=self.clean_str(r.get('development_stage'))
                ),
                'raw_metadata': self.safe_json_dumps(r.to_dict()),
                'etl_source_file': 'samples_full.csv',
            }
            sample_batch.append(row)
            if cell_type_list_raw:
                celltype_pending.append((sample_id, cell_type_list_raw))

            # Flush batch
            if len(sample_batch) >= self.BATCH_SIZE:
                loaded = self.batch_insert('unified_samples', sample_batch)
                self.stats['loaded'] += loaded
                sample_batch = []
                self.log_progress('samples')

        # Final flush
        if sample_batch:
            loaded = self.batch_insert('unified_samples', sample_batch)
            self.stats['loaded'] += loaded

        logger.info(f"  Loaded {self.stats['loaded']} samples")

        # ── Cell types ──
        self._load_celltypes(celltype_pending)

    def _load_celltypes(self, pending: list):
        """Parse cell_type_list and insert into unified_celltypes."""
        logger.info(f"Loading cell types from {len(pending)} samples")

        # Build sample_id → pk lookup
        sample_pk_lookup = {}
        cursor = self.conn.execute(
            "SELECT pk, sample_id FROM unified_samples WHERE source_database = ?",
            (self.SOURCE_DATABASE,)
        )
        for row in cursor.fetchall():
            sample_pk_lookup[row[1]] = row[0]

        ct_batch = []
        ct_count = 0

        for sample_id, ct_list in pending:
            sample_pk = sample_pk_lookup.get(sample_id)
            if not sample_pk:
                continue

            cell_types = [ct.strip() for ct in ct_list.split(';') if ct.strip()]
            for ct_name in cell_types:
                ct_batch.append({
                    'sample_pk': sample_pk,
                    'cell_type_name': ct_name,
                    'cell_type_ontology_term_id': None,
                    'source_database': self.SOURCE_DATABASE,
                    'source_field': 'cell_type_list',
                })

            if len(ct_batch) >= self.BATCH_SIZE:
                loaded = self.batch_insert('unified_celltypes', ct_batch)
                ct_count += loaded
                ct_batch = []

        if ct_batch:
            loaded = self.batch_insert('unified_celltypes', ct_batch)
            ct_count += loaded

        logger.info(f"  Loaded {ct_count} cell type annotations")

    # ── CellXGene-specific parsers ────────────────────────────

    @staticmethod
    def _parse_ontology_field(raw: str):
        """Parse 'term name (ONTOLOGY:ID)' → (name, ontology_id).

        Also handles '||' multi-value: takes first value.
        """
        if not raw:
            return None, None
        # Take first if multi-value
        if '||' in raw:
            raw = raw.split('||')[0].strip()
        if ';' in raw:
            raw = raw.split(';')[0].strip()

        import re
        m = re.match(r'^(.+?)\s*\(([A-Za-z]+:\d+)\)\s*$', raw)
        if m:
            return m.group(1).strip(), m.group(2)
        return raw.strip(), None

    @staticmethod
    def _extract_organism(raw: str) -> str:
        """Extract organism from 'Homo sapiens (NCBITaxon:9606)'."""
        if not raw:
            return 'Homo sapiens'
        if '(' in raw:
            return raw.split('(')[0].strip()
        return raw.strip()

    @staticmethod
    def _parse_disease(disease_raw, ontology_raw):
        """Parse CellXGene disease field.

        Input: 'colorectal carcinoma || metastatic malignant neoplasm;normal'
        The ';' separates observation-level values.
        The '||' separates co-occurring conditions.
        Output: cleaned disease string, cleaned ontology string
        """
        disease_raw = str(disease_raw).strip() if disease_raw and str(disease_raw) != 'nan' else None
        ontology_raw = str(ontology_raw).strip() if ontology_raw and str(ontology_raw) != 'nan' else None

        if not disease_raw or disease_raw.lower() == 'normal':
            return 'normal', ontology_raw

        # Split by ';' (observation groups), filter out 'normal'
        parts = []
        for group in disease_raw.split(';'):
            group = group.strip()
            if group.lower() == 'normal':
                continue
            if group:
                parts.append(group)

        if not parts:
            return 'normal', ontology_raw

        # Join remaining groups with '; '
        return '; '.join(parts), ontology_raw

    @staticmethod
    def _summarize_cell_type(ct_list: str) -> str:
        """Summarize cell type list to a single representative value."""
        if not ct_list:
            return None
        types = [t.strip() for t in ct_list.split(';') if t.strip()]
        if len(types) == 0:
            return None
        if len(types) == 1:
            return types[0]
        if len(types) <= 3:
            return '; '.join(types)
        return 'mixed'

    @staticmethod
    def _map_tissue_type(val) -> str:
        if not val or str(val) == 'nan':
            return None
        val = str(val).strip().lower()
        mapping = {
            'tissue': 'tissue',
            'organoid': 'organoid',
            'cell_culture': 'cell_line',
            'cell culture': 'cell_line',
        }
        return mapping.get(val, val)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import DB_PATH

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    etl = CellXGeneETL(DB_PATH)
    etl.run()
