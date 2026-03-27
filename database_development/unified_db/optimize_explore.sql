-- ============================================================================
-- Explore API 性能优化索引
-- 解决 /api/v1/explore 端点 10秒+ 延迟问题
-- ============================================================================

-- 1. 覆盖索引：支持 ORDER BY n_cells + 快速 JOIN 定位
-- 这是最关键的索引，直接解决排序性能问题
CREATE INDEX IF NOT EXISTS idx_samples_n_cells_covering 
ON unified_samples(n_cells DESC, series_pk, project_pk, sample_id, tissue, disease, cell_type, organism, sex, source_database);

-- 2. 常用过滤组合索引
CREATE INDEX IF NOT EXISTS idx_samples_tissue_disease_n_cells 
ON unified_samples(tissue, disease, n_cells DESC) 
WHERE tissue IS NOT NULL AND disease IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_samples_source_n_cells 
ON unified_samples(source_database, n_cells DESC);

-- 3. 支持分页的索引（配合 OFFSET）
CREATE INDEX IF NOT EXISTS idx_samples_pk_n_cells 
ON unified_samples(pk, n_cells DESC);

-- 4. 加速 COUNT 查询的索引
CREATE INDEX IF NOT EXISTS idx_samples_nonempty 
ON unified_samples(pk) 
WHERE tissue IS NOT NULL OR disease IS NOT NULL;

-- ============================================================================
-- 执行后验证
-- ============================================================================

-- 查看新创建的索引
SELECT name, tbl_name FROM sqlite_master 
WHERE type='index' AND name LIKE 'idx_samples_%' 
ORDER BY tbl_name, name;

-- 分析表（更新统计信息）
ANALYZE unified_samples;
ANALYZE unified_series;
ANALYZE unified_projects;
