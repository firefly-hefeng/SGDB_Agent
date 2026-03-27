-- Data Quality Monitoring View
-- Tracks field completeness and data quality metrics across all sources

CREATE VIEW IF NOT EXISTS v_data_quality AS
SELECT
    s.source_database,
    COUNT(*) as total_samples,

    -- Core metadata completeness
    ROUND(100.0 * SUM(CASE WHEN s.tissue IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as tissue_pct,
    ROUND(100.0 * SUM(CASE WHEN s.disease IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as disease_pct,
    ROUND(100.0 * SUM(CASE WHEN s.cell_type IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as cell_type_pct,
    ROUND(100.0 * SUM(CASE WHEN s.sex IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as sex_pct,
    ROUND(100.0 * SUM(CASE WHEN s.age IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as age_pct,
    ROUND(100.0 * SUM(CASE WHEN s.ethnicity IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as ethnicity_pct,
    ROUND(100.0 * SUM(CASE WHEN s.development_stage IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as dev_stage_pct,

    -- Ontology term completeness
    ROUND(100.0 * SUM(CASE WHEN s.tissue_ontology_term_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as tissue_onto_pct,
    ROUND(100.0 * SUM(CASE WHEN s.disease_ontology_term_id IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as disease_onto_pct,

    -- Quantitative data
    ROUND(100.0 * SUM(CASE WHEN s.n_cells IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as n_cells_pct,
    SUM(CASE WHEN s.n_cells IS NOT NULL THEN s.n_cells ELSE 0 END) as total_cells,

    -- Project linkage
    ROUND(100.0 * SUM(CASE WHEN s.project_pk IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as has_project_pct,
    ROUND(100.0 * SUM(CASE WHEN s.series_pk IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as has_series_pct,

    -- Overall quality score (weighted average of key fields)
    ROUND(
        (
            SUM(CASE WHEN s.tissue IS NOT NULL THEN 1 ELSE 0 END) * 0.25 +
            SUM(CASE WHEN s.disease IS NOT NULL THEN 1 ELSE 0 END) * 0.20 +
            SUM(CASE WHEN s.sex IS NOT NULL THEN 1 ELSE 0 END) * 0.15 +
            SUM(CASE WHEN s.n_cells IS NOT NULL THEN 1 ELSE 0 END) * 0.15 +
            SUM(CASE WHEN s.tissue_ontology_term_id IS NOT NULL THEN 1 ELSE 0 END) * 0.15 +
            SUM(CASE WHEN s.disease_ontology_term_id IS NOT NULL THEN 1 ELSE 0 END) * 0.10
        ) * 100.0 / COUNT(*),
        1
    ) as quality_score

FROM unified_samples s
GROUP BY s.source_database
ORDER BY quality_score DESC;

-- Field-level quality view
CREATE VIEW IF NOT EXISTS v_field_quality AS
SELECT
    'tissue' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN tissue IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN tissue IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT tissue) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'disease' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN disease IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN disease IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT disease) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'cell_type' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN cell_type IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN cell_type IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT cell_type) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'sex' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN sex IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN sex IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT sex) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'age' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN age IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN age IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT age) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'n_cells' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN n_cells IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN n_cells IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT n_cells) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_samples

UNION ALL

SELECT
    'assay' as field_name,
    COUNT(*) as total_records,
    SUM(CASE WHEN assay IS NOT NULL THEN 1 ELSE 0 END) as non_null_count,
    ROUND(100.0 * SUM(CASE WHEN assay IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as completeness_pct,
    COUNT(DISTINCT assay) as distinct_values,
    COUNT(DISTINCT source_database) as sources_with_data
FROM unified_series;
