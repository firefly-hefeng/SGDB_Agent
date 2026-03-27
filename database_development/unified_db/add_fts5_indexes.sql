-- FTS5 Full-Text Search Indexes for Fast Text Matching
-- Replaces slow LIKE '%term%' queries with fast FTS5 MATCH queries
-- Run this after initial ETL to enable fast text search

-- ========== 1. Samples FTS Index ==========
-- Index tissue, disease, and key metadata for sample searches
CREATE VIRTUAL TABLE IF NOT EXISTS fts_samples USING fts5(
    sample_pk UNINDEXED,
    tissue,
    disease,
    cell_type,
    organism,
    development_stage,
    ethnicity,
    content=unified_samples,
    content_rowid=pk
);

-- Populate FTS index
INSERT INTO fts_samples(sample_pk, tissue, disease, cell_type, organism, development_stage, ethnicity)
SELECT pk, tissue, disease, cell_type, organism, development_stage, ethnicity
FROM unified_samples;

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS fts_samples_ai AFTER INSERT ON unified_samples BEGIN
    INSERT INTO fts_samples(sample_pk, tissue, disease, cell_type, organism, development_stage, ethnicity)
    VALUES (new.pk, new.tissue, new.disease, new.cell_type, new.organism, new.development_stage, new.ethnicity);
END;

CREATE TRIGGER IF NOT EXISTS fts_samples_ad AFTER DELETE ON unified_samples BEGIN
    INSERT INTO fts_samples(fts_samples, sample_pk, tissue, disease, cell_type, organism, development_stage, ethnicity)
    VALUES ('delete', old.pk, old.tissue, old.disease, old.cell_type, old.organism, old.development_stage, old.ethnicity);
END;

CREATE TRIGGER IF NOT EXISTS fts_samples_au AFTER UPDATE ON unified_samples BEGIN
    INSERT INTO fts_samples(fts_samples, sample_pk, tissue, disease, cell_type, organism, development_stage, ethnicity)
    VALUES ('delete', old.pk, old.tissue, old.disease, old.cell_type, old.organism, old.development_stage, old.ethnicity);
    INSERT INTO fts_samples(sample_pk, tissue, disease, cell_type, organism, development_stage, ethnicity)
    VALUES (new.pk, new.tissue, new.disease, new.cell_type, new.organism, new.development_stage, new.ethnicity);
END;

-- ========== 2. Projects FTS Index ==========
-- Index project titles and descriptions for project searches
CREATE VIRTUAL TABLE IF NOT EXISTS fts_projects USING fts5(
    project_pk UNINDEXED,
    project_id UNINDEXED,
    title,
    description,
    organism,
    content=unified_projects,
    content_rowid=pk
);

INSERT INTO fts_projects(project_pk, project_id, title, description, organism)
SELECT pk, project_id, title, description, organism
FROM unified_projects;

CREATE TRIGGER IF NOT EXISTS fts_projects_ai AFTER INSERT ON unified_projects BEGIN
    INSERT INTO fts_projects(project_pk, project_id, title, description, organism)
    VALUES (new.pk, new.project_id, new.title, new.description, new.organism);
END;

CREATE TRIGGER IF NOT EXISTS fts_projects_ad AFTER DELETE ON unified_projects BEGIN
    INSERT INTO fts_projects(fts_projects, project_pk, project_id, title, description, organism)
    VALUES ('delete', old.pk, old.project_id, old.title, old.description, old.organism);
END;

CREATE TRIGGER IF NOT EXISTS fts_projects_au AFTER UPDATE ON unified_projects BEGIN
    INSERT INTO fts_projects(fts_projects, project_pk, project_id, title, description, organism)
    VALUES ('delete', old.pk, old.project_id, old.title, old.description, old.organism);
    INSERT INTO fts_projects(project_pk, project_id, title, description, organism)
    VALUES (new.pk, new.project_id, new.title, new.description, new.organism);
END;

-- ========== 3. Series FTS Index ==========
-- Index series titles and assay info
CREATE VIRTUAL TABLE IF NOT EXISTS fts_series USING fts5(
    series_pk UNINDEXED,
    series_id UNINDEXED,
    title,
    assay,
    content=unified_series,
    content_rowid=pk
);

INSERT INTO fts_series(series_pk, series_id, title, assay)
SELECT pk, series_id, title, assay
FROM unified_series;

CREATE TRIGGER IF NOT EXISTS fts_series_ai AFTER INSERT ON unified_series BEGIN
    INSERT INTO fts_series(series_pk, series_id, title, assay)
    VALUES (new.pk, new.series_id, new.title, new.assay);
END;

CREATE TRIGGER IF NOT EXISTS fts_series_ad AFTER DELETE ON unified_series BEGIN
    INSERT INTO fts_series(fts_series, series_pk, series_id, title, assay)
    VALUES ('delete', old.pk, old.series_id, old.title, old.assay);
END;

CREATE TRIGGER IF NOT EXISTS fts_series_au AFTER UPDATE ON unified_series BEGIN
    INSERT INTO fts_series(fts_series, series_pk, series_id, title, assay)
    VALUES ('delete', old.pk, old.series_id, old.title, old.assay);
    INSERT INTO fts_series(series_pk, series_id, title, assay)
    VALUES (new.pk, new.series_id, new.title, new.assay);
END;

-- ========== Usage Examples ==========
-- Instead of: SELECT * FROM unified_samples WHERE tissue LIKE '%brain%'
-- Use: SELECT s.* FROM unified_samples s
--      JOIN fts_samples f ON s.pk = f.sample_pk
--      WHERE fts_samples MATCH 'tissue:brain'

-- Multi-field search:
-- SELECT s.* FROM unified_samples s
-- JOIN fts_samples f ON s.pk = f.sample_pk
-- WHERE fts_samples MATCH 'tissue:brain AND disease:cancer'

-- Prefix search:
-- WHERE fts_samples MATCH 'tissue:bra*'

-- Phrase search:
-- WHERE fts_samples MATCH 'tissue:"prefrontal cortex"'
