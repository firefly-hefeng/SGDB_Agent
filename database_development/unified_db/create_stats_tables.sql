-- Precomputed Statistics Tables
-- These tables cache aggregated statistics to speed up common queries

-- ========== 1. Source Database Statistics ==========
-- Replaces: SELECT source_database, COUNT(*) FROM unified_samples GROUP BY source_database
CREATE TABLE IF NOT EXISTS stats_by_source (
    source_database TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL,
    project_count INTEGER NOT NULL,
    series_count INTEGER NOT NULL,
    total_cells INTEGER,
    avg_cells_per_sample REAL,
    samples_with_tissue INTEGER,
    samples_with_disease INTEGER,
    samples_with_cell_type INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== 2. Tissue Statistics ==========
CREATE TABLE IF NOT EXISTS stats_by_tissue (
    tissue TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL,
    source_count INTEGER NOT NULL,
    total_cells INTEGER,
    top_diseases TEXT,  -- JSON array of top 5 diseases
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== 3. Disease Statistics ==========
CREATE TABLE IF NOT EXISTS stats_by_disease (
    disease TEXT PRIMARY KEY,
    sample_count INTEGER NOT NULL,
    source_count INTEGER NOT NULL,
    total_cells INTEGER,
    top_tissues TEXT,  -- JSON array of top 5 tissues
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== 4. Assay Statistics ==========
CREATE TABLE IF NOT EXISTS stats_by_assay (
    assay TEXT PRIMARY KEY,
    series_count INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    total_cells INTEGER,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== 5. Overall Statistics ==========
CREATE TABLE IF NOT EXISTS stats_overall (
    metric TEXT PRIMARY KEY,
    value INTEGER NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Populate overall stats
INSERT OR REPLACE INTO stats_overall (metric, value) VALUES
    ('total_projects', (SELECT COUNT(*) FROM unified_projects)),
    ('total_series', (SELECT COUNT(*) FROM unified_series)),
    ('total_samples', (SELECT COUNT(*) FROM unified_samples)),
    ('total_celltypes', (SELECT COUNT(*) FROM unified_celltypes)),
    ('total_entity_links', (SELECT COUNT(*) FROM entity_links)),
    ('total_sources', (SELECT COUNT(DISTINCT source_database) FROM unified_samples));
