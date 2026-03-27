-- ============================================================
-- UNIFIED SINGLE-CELL METADATA DATABASE SCHEMA
-- Target: SQLite (development) / PostgreSQL (production)
-- Version: 3.0
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

-- ============================================================
-- LEVEL 1: UNIFIED PROJECTS
-- ============================================================
CREATE TABLE IF NOT EXISTS unified_projects (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source identifier
    project_id TEXT NOT NULL,
    project_id_type TEXT NOT NULL,
    source_database TEXT NOT NULL,

    -- Core metadata
    title TEXT,
    description TEXT,
    organism TEXT,

    -- Publication
    pmid TEXT,
    doi TEXT,
    pmc_id TEXT,
    publication_date TEXT,
    journal TEXT,
    citation_count INTEGER,

    -- Contact
    contact_name TEXT,
    contact_email TEXT,
    submitter_organization TEXT,

    -- Data stats
    sample_count INTEGER,
    total_cells INTEGER,

    -- Access
    data_availability TEXT,
    access_url TEXT,

    -- Provenance
    submission_date TEXT,
    last_update_date TEXT,
    raw_metadata TEXT,

    -- ETL tracking
    etl_source_file TEXT,
    etl_loaded_at TEXT DEFAULT (datetime('now')),

    UNIQUE(project_id, source_database)
);


-- ============================================================
-- LEVEL 2: UNIFIED SERIES
-- ============================================================
CREATE TABLE IF NOT EXISTS unified_series (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source identifier
    series_id TEXT NOT NULL,
    series_id_type TEXT NOT NULL,
    source_database TEXT NOT NULL,

    -- Parent project
    project_pk INTEGER REFERENCES unified_projects(pk),
    project_id TEXT,

    -- Core metadata
    title TEXT,
    description TEXT,
    organism TEXT,

    -- Technology / Assay
    assay TEXT,
    assay_ontology_term_id TEXT,
    suspension_type TEXT,

    -- Data characteristics
    cell_count INTEGER,
    gene_count INTEGER,
    mean_genes_per_cell REAL,
    sample_count INTEGER,

    -- File availability
    has_h5ad INTEGER DEFAULT 0,
    has_rds INTEGER DEFAULT 0,
    asset_h5ad_url TEXT,
    asset_rds_url TEXT,
    explorer_url TEXT,

    -- Citation
    citation_count INTEGER,
    citation_source TEXT,

    -- Provenance
    published_at TEXT,
    revised_at TEXT,
    raw_metadata TEXT,

    -- ETL
    etl_source_file TEXT,
    etl_loaded_at TEXT DEFAULT (datetime('now')),

    UNIQUE(series_id, source_database)
);


-- ============================================================
-- LEVEL 3: UNIFIED SAMPLES
-- ============================================================
CREATE TABLE IF NOT EXISTS unified_samples (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source identifier
    sample_id TEXT NOT NULL,
    sample_id_type TEXT NOT NULL,
    source_database TEXT NOT NULL,

    -- Parent references
    series_pk INTEGER REFERENCES unified_series(pk),
    series_id TEXT,
    project_pk INTEGER REFERENCES unified_projects(pk),
    project_id TEXT,

    -- Biological identity
    organism TEXT,
    tissue TEXT,
    tissue_ontology_term_id TEXT,
    tissue_general TEXT,
    cell_type TEXT,
    cell_type_ontology_term_id TEXT,
    disease TEXT,
    disease_ontology_term_id TEXT,
    sex TEXT,
    sex_ontology_term_id TEXT,
    age TEXT,
    age_unit TEXT,
    development_stage TEXT,
    development_stage_ontology_term_id TEXT,
    ethnicity TEXT,
    ethnicity_ontology_term_id TEXT,

    -- Sample metadata
    individual_id TEXT,
    sample_source_type TEXT,
    is_primary_data INTEGER,
    suspension_type TEXT,
    tissue_type TEXT,

    -- Quantitative
    n_cells INTEGER,
    n_cell_types INTEGER,

    -- Expression QC (CellXGene)
    expr_raw_sum_mean REAL,
    expr_raw_sum_min REAL,
    expr_raw_sum_max REAL,
    expr_nnz_mean REAL,

    -- Dedup support
    biological_identity_hash TEXT,

    -- Provenance
    raw_metadata TEXT,

    -- ETL
    etl_source_file TEXT,
    etl_loaded_at TEXT DEFAULT (datetime('now')),

    UNIQUE(sample_id, source_database)
);


-- ============================================================
-- LEVEL 4: UNIFIED CELLTYPES
-- ============================================================
CREATE TABLE IF NOT EXISTS unified_celltypes (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    sample_pk INTEGER NOT NULL REFERENCES unified_samples(pk),

    cell_type_name TEXT NOT NULL,
    cell_type_ontology_term_id TEXT,

    source_database TEXT NOT NULL,
    source_field TEXT,

    UNIQUE(sample_pk, cell_type_name)
);


-- ============================================================
-- ENTITY LINKS (cross-database relationships)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_links (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    source_entity_type TEXT NOT NULL,
    source_pk INTEGER NOT NULL,
    source_id TEXT,
    source_database TEXT,

    target_entity_type TEXT NOT NULL,
    target_pk INTEGER NOT NULL,
    target_id TEXT,
    target_database TEXT,

    relationship_type TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'high',
    link_method TEXT,
    link_evidence TEXT,

    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(source_entity_type, source_pk, target_entity_type, target_pk, relationship_type)
);


-- ============================================================
-- ID MAPPINGS (external ID cross-references)
-- ============================================================
CREATE TABLE IF NOT EXISTS id_mappings (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    entity_type TEXT NOT NULL,
    entity_pk INTEGER NOT NULL,

    id_type TEXT NOT NULL,
    id_value TEXT NOT NULL,

    id_source_database TEXT,
    is_primary INTEGER DEFAULT 0,

    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(entity_type, entity_pk, id_type, id_value)
);


-- ============================================================
-- DEDUP CANDIDATES
-- ============================================================
CREATE TABLE IF NOT EXISTS dedup_candidates (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    entity_type TEXT NOT NULL,
    entity_a_pk INTEGER NOT NULL,
    entity_a_id TEXT,
    entity_a_database TEXT,
    entity_b_pk INTEGER NOT NULL,
    entity_b_id TEXT,
    entity_b_database TEXT,

    match_method TEXT NOT NULL,
    confidence_score REAL,
    match_evidence TEXT,

    status TEXT DEFAULT 'pending',
    resolved_by TEXT,
    resolved_at TEXT,
    resolution_notes TEXT,

    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(entity_type, entity_a_pk, entity_b_pk, match_method)
);


-- ============================================================
-- ETL RUN LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS etl_run_log (
    pk INTEGER PRIMARY KEY AUTOINCREMENT,

    source_database TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,

    records_processed INTEGER DEFAULT 0,
    records_loaded INTEGER DEFAULT 0,
    records_skipped INTEGER DEFAULT 0,
    records_errored INTEGER DEFAULT 0,

    error_message TEXT,
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    duration_seconds REAL
);


-- ============================================================
-- INDEXES (uncomment after bulk data loading)
-- ============================================================
-- unified_projects
-- CREATE INDEX idx_up_project_id ON unified_projects(project_id);
-- CREATE INDEX idx_up_source ON unified_projects(source_database);
-- CREATE INDEX idx_up_pmid ON unified_projects(pmid);
-- CREATE INDEX idx_up_doi ON unified_projects(doi);
-- CREATE INDEX idx_up_organism ON unified_projects(organism);

-- unified_series
-- CREATE INDEX idx_us_series_id ON unified_series(series_id);
-- CREATE INDEX idx_us_source ON unified_series(source_database);
-- CREATE INDEX idx_us_project_pk ON unified_series(project_pk);
-- CREATE INDEX idx_us_organism ON unified_series(organism);
-- CREATE INDEX idx_us_assay ON unified_series(assay);

-- unified_samples
-- CREATE INDEX idx_usmp_sample_id ON unified_samples(sample_id);
-- CREATE INDEX idx_usmp_source ON unified_samples(source_database);
-- CREATE INDEX idx_usmp_series_pk ON unified_samples(series_pk);
-- CREATE INDEX idx_usmp_project_pk ON unified_samples(project_pk);
-- CREATE INDEX idx_usmp_organism ON unified_samples(organism);
-- CREATE INDEX idx_usmp_tissue ON unified_samples(tissue);
-- CREATE INDEX idx_usmp_disease ON unified_samples(disease);
-- CREATE INDEX idx_usmp_identity_hash ON unified_samples(biological_identity_hash);
-- CREATE INDEX idx_usmp_individual ON unified_samples(individual_id);

-- unified_celltypes
-- CREATE INDEX idx_uct_sample_pk ON unified_celltypes(sample_pk);
-- CREATE INDEX idx_uct_name ON unified_celltypes(cell_type_name);

-- entity_links
-- CREATE INDEX idx_el_source ON entity_links(source_entity_type, source_pk);
-- CREATE INDEX idx_el_target ON entity_links(target_entity_type, target_pk);
-- CREATE INDEX idx_el_relationship ON entity_links(relationship_type);

-- id_mappings
-- CREATE INDEX idx_im_lookup ON id_mappings(id_type, id_value);
-- CREATE INDEX idx_im_entity ON id_mappings(entity_type, entity_pk);

-- dedup_candidates
-- CREATE INDEX idx_dc_status ON dedup_candidates(status);
-- CREATE INDEX idx_dc_entity ON dedup_candidates(entity_type, entity_a_pk);


-- ============================================================
-- HELPER VIEW (create after data loading)
-- ============================================================
-- CREATE VIEW v_sample_with_hierarchy AS
-- SELECT
--     s.pk as sample_pk, s.sample_id, s.sample_id_type,
--     s.source_database as sample_source,
--     s.organism, s.tissue, s.tissue_ontology_term_id,
--     s.disease, s.disease_ontology_term_id,
--     s.sex, s.age, s.development_stage, s.ethnicity,
--     s.individual_id, s.n_cells, s.biological_identity_hash,
--     sr.pk as series_pk, sr.series_id, sr.title as series_title,
--     sr.assay, sr.cell_count as series_cell_count,
--     p.pk as project_pk, p.project_id, p.title as project_title,
--     p.pmid, p.doi, p.citation_count
-- FROM unified_samples s
-- LEFT JOIN unified_series sr ON s.series_pk = sr.pk
-- LEFT JOIN unified_projects p ON s.project_pk = p.pk;
