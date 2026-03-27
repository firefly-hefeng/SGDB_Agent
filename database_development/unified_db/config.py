"""Configuration for the unified metadata database pipeline."""

import os

# Base paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Output database
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'unified_metadata.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')

# === Data source paths ===

# CellXGene
CELLXGENE_DIR = os.path.join(PROJECT_ROOT, 'cellxgene', 'output_v2')
CELLXGENE_COLLECTIONS = os.path.join(CELLXGENE_DIR, 'collections_hierarchy.csv')
CELLXGENE_DATASETS = os.path.join(CELLXGENE_DIR, 'datasets_hierarchy_final.csv')
CELLXGENE_SAMPLES = os.path.join(CELLXGENE_DIR, 'samples_full.csv')

# NCBI / SRA
NCBI_DIR = os.path.join(PROJECT_ROOT, 'ncbi_bioproject_sra_data')
NCBI_BIOPROJECTS = os.path.join(NCBI_DIR, 'raw_bioprojects.csv')
NCBI_BIOSAMPLES = os.path.join(NCBI_DIR, 'raw_biosamples.csv')
NCBI_SRA_STUDIES = os.path.join(NCBI_DIR, 'raw_sra_studies.csv')
NCBI_SRA_EXPERIMENTS = os.path.join(NCBI_DIR, 'raw_sra_experiments.csv')
NCBI_SRA_RUNS = os.path.join(NCBI_DIR, 'raw_sra_runs.csv')
NCBI_PUBMED = os.path.join(NCBI_DIR, 'raw_pubmed_articles.csv')
NCBI_SQLITE_DB = os.path.join(NCBI_DIR, 'bioproject_sra_metadata.db')

# GEO
GEO_DIR = os.path.join(PROJECT_ROOT, 'geo')
GEO_SAMPLES_XLSX = os.path.join(GEO_DIR, 'merged_samples_with_citation.xlsx')
GEO_SAMPLES_CSV = os.path.join(GEO_DIR, 'merged_samples_with_citation.csv')

# EBI
EBI_DIR = os.path.join(PROJECT_ROOT, 'ebi', 'collected_data')
EBI_BIOSTUDIES_DIR = os.path.join(EBI_DIR, 'raw_biostudies')
EBI_BIOSAMPLES_DIR = os.path.join(EBI_DIR, 'raw_biosamples')
EBI_SCEA = os.path.join(EBI_DIR, 'raw_scea.json')

# Small sources
HCA_FILE = os.path.join(PROJECT_ROOT, 'HCA.xlsx')
HTAN_FILE = os.path.join(PROJECT_ROOT, 'HTAN.tsv')
EGA_FILE = os.path.join(PROJECT_ROOT, 'ega_scrna_metadata.xlsx')
PSYCHAD_FILE = os.path.join(PROJECT_ROOT, 'PsychAD_media-1.csv')
BISCP_DIR = os.path.join(PROJECT_ROOT, 'biscp')
KPMP_DIR = os.path.join(PROJECT_ROOT, 'kpmp')
ZENODO_FILE = os.path.join(PROJECT_ROOT, 'zenodo+figshare', 'data_human_sc', 'zenodo_records.csv')
FIGSHARE_FILE = os.path.join(PROJECT_ROOT, 'zenodo+figshare', 'data_human_sc', 'figshare_records.csv')

# ETL settings
BATCH_SIZE = 5000
GEO_CHUNK_SIZE = 10000
EBI_FILE_BATCH_SIZE = 1000

# Logging
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
LOG_LEVEL = 'INFO'
