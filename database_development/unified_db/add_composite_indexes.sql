-- Composite Indexes for Common Query Patterns
-- These indexes speed up multi-condition WHERE clauses

-- ========== unified_samples indexes ==========

-- Most common: tissue + disease filtering
CREATE INDEX IF NOT EXISTS idx_samples_tissue_disease
ON unified_samples(tissue, disease) WHERE tissue IS NOT NULL;

-- Tissue + source filtering
CREATE INDEX IF NOT EXISTS idx_samples_tissue_source
ON unified_samples(tissue, source_database) WHERE tissue IS NOT NULL;

-- Disease + source filtering
CREATE INDEX IF NOT EXISTS idx_samples_disease_source
ON unified_samples(disease, source_database) WHERE disease IS NOT NULL;

-- Organism + tissue (for species-specific searches)
CREATE INDEX IF NOT EXISTS idx_samples_organism_tissue
ON unified_samples(organism, tissue);

-- Source + tissue + disease (covers most multi-condition queries)
CREATE INDEX IF NOT EXISTS idx_samples_source_tissue_disease
ON unified_samples(source_database, tissue, disease);

-- Cell count filtering (for "large datasets" queries)
CREATE INDEX IF NOT EXISTS idx_samples_n_cells
ON unified_samples(n_cells) WHERE n_cells IS NOT NULL;

-- Sex filtering
CREATE INDEX IF NOT EXISTS idx_samples_sex
ON unified_samples(sex) WHERE sex IS NOT NULL;

-- Biological identity hash (for deduplication)
CREATE INDEX IF NOT EXISTS idx_samples_bio_hash
ON unified_samples(biological_identity_hash) WHERE biological_identity_hash IS NOT NULL;

-- Foreign keys (if not already indexed)
CREATE INDEX IF NOT EXISTS idx_samples_series_pk ON unified_samples(series_pk);
CREATE INDEX IF NOT EXISTS idx_samples_project_pk ON unified_samples(project_pk);

-- ========== unified_projects indexes ==========

-- PMID lookup (very common)
CREATE INDEX IF NOT EXISTS idx_projects_pmid
ON unified_projects(pmid) WHERE pmid IS NOT NULL;

-- DOI lookup
CREATE INDEX IF NOT EXISTS idx_projects_doi
ON unified_projects(doi) WHERE doi IS NOT NULL;

-- Citation count (for "most cited" queries)
CREATE INDEX IF NOT EXISTS idx_projects_citation_count
ON unified_projects(citation_count DESC) WHERE citation_count IS NOT NULL;

-- Source database
CREATE INDEX IF NOT EXISTS idx_projects_source
ON unified_projects(source_database);

-- Project ID (should already exist, but ensure it)
CREATE INDEX IF NOT EXISTS idx_projects_project_id
ON unified_projects(project_id);

-- ========== unified_series indexes ==========

-- Assay filtering
CREATE INDEX IF NOT EXISTS idx_series_assay
ON unified_series(assay) WHERE assay IS NOT NULL;

-- Data availability (h5ad/rds)
CREATE INDEX IF NOT EXISTS idx_series_has_h5ad
ON unified_series(has_h5ad) WHERE has_h5ad = 1;

CREATE INDEX IF NOT EXISTS idx_series_has_rds
ON unified_series(has_rds) WHERE has_rds = 1;

-- Cell count (for "large datasets")
CREATE INDEX IF NOT EXISTS idx_series_cell_count
ON unified_series(cell_count DESC) WHERE cell_count IS NOT NULL;

-- Foreign key
CREATE INDEX IF NOT EXISTS idx_series_project_pk ON unified_series(project_pk);

-- Series ID
CREATE INDEX IF NOT EXISTS idx_series_series_id ON unified_series(series_id);

-- ========== entity_links indexes ==========

-- Cross-database linking lookups
CREATE INDEX IF NOT EXISTS idx_links_source
ON entity_links(source_entity_type, source_pk, relationship_type);

CREATE INDEX IF NOT EXISTS idx_links_target
ON entity_links(target_entity_type, target_pk, relationship_type);

-- Bidirectional lookup
CREATE INDEX IF NOT EXISTS idx_links_both
ON entity_links(source_pk, target_pk);

-- ========== id_mappings indexes ==========

-- ID value lookup (most common)
CREATE INDEX IF NOT EXISTS idx_mappings_id_value
ON id_mappings(id_value);

-- Entity type + ID
CREATE INDEX IF NOT EXISTS idx_mappings_entity_id
ON id_mappings(entity_type, id_value);

-- Reverse lookup (entity_pk -> IDs)
CREATE INDEX IF NOT EXISTS idx_mappings_entity_pk
ON id_mappings(entity_type, entity_pk);

-- ========== dedup_candidates indexes ==========

-- Identity hash lookup (for deduplication)
CREATE INDEX IF NOT EXISTS idx_dedup_hash
ON dedup_candidates(identity_hash);

-- Entity lookup
CREATE INDEX IF NOT EXISTS idx_dedup_entity
ON dedup_candidates(entity_type, entity_pk);

-- Similarity score (for ranking)
CREATE INDEX IF NOT EXISTS idx_dedup_similarity
ON dedup_candidates(similarity_score DESC) WHERE similarity_score IS NOT NULL;
