# 单细胞元数据库统一Schema v2.0
## 多表存储 + 统一视图呈现架构
注：目前该schema体系只是一个想法，目前需要这样的架构来容纳和适配不同数据库的数据。也需要你了解不同数据库的数据皴存放和整理逻辑（geo：project-series-sample,cellxgene:collection-dataset-donor(sample)-cell等，都是不同的数据架构），这就需要你的超大脑容量和架构设计能力发挥作用了。
---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         统一视图层 (Presentation Layer)                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │         unified_single_cell_view (虚拟视图/物化视图)                     │ │
│  │  - 单条记录 = 一个生物学概念样本 (样本+组织+疾病+...)                   │ │
│  │  - 聚合所有数据源和版本信息                                             │ │
│  │  - 支持多态数据展示 (JSON数组格式存储多版本)                            │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         关联层 (Relationship Layer)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ entity_links │  │ version_tree │  │  id_mappings │  │  cross_refs  │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         实体层 (Entity Layer)                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ projects │ │ samples  │ │experiments│ │ files   │ │datasets  │          │
│  │ (研究)   │ │ (样本)   │ │ (测序)   │ │ (文件)  │ │(数据集)  │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         数据源层 (Source Layer)                              │
│  CellXGene    GEO    NCBI SRA    EBI    CNGB    EGA    SCP    Zenodo...      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心实体表设计

### 2.1 samples - 生物学样本主表（去重后）

这是**最核心的实体表**，基于生物学唯一性去重（同一组织来源的同一个人/动物视为同一样本）。

```sql
CREATE TABLE samples (
    -- 主键
    sample_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 生物学身份标识（用于去重判断）
    biological_identity_hash VARCHAR(64) UNIQUE, -- MD5(organism:tissue:individual_id:development_stage:disease)
    
    -- 标准样本信息
    organism VARCHAR(100) NOT NULL,              -- Homo sapiens
    organism_taxid INTEGER,                      -- 9606
    tissue VARCHAR(200),                         -- liver
    tissue_ontology VARCHAR(50),                 -- UBERON:0002107
    tissue_general VARCHAR(100),                 -- liver/hepatocyte
    cell_type VARCHAR(200),                      -- hepatocyte
    cell_type_ontology VARCHAR(50),              -- CL:0000182
    
    -- 疾病和表型
    disease VARCHAR(200),                        -- hepatocellular carcinoma
    disease_ontology VARCHAR(50),                -- MONDO:0007256
    disease_general VARCHAR(100),                -- cancer
    
    -- 个体信息
    individual_id VARCHAR(100),                  -- 个体唯一ID（donor_id/patient_id）
    sex VARCHAR(20),                             -- male/female/unknown
    age_value VARCHAR(50),                       -- 35
    age_unit VARCHAR(20),                        -- year/month/week
    developmental_stage VARCHAR(100),            -- adult/fetus/embryo
    developmental_stage_ontology VARCHAR(50),    -- HsapDv:0000087
    ethnicity VARCHAR(100),                      -- European/African
    ethnicity_ontology VARCHAR(50),              -- HANCESTRO:0005
    
    -- 样本来源
    sample_source_type VARCHAR(50),              -- tissue/cell_line/organoid/pbmc
    cell_line VARCHAR(100),                      -- HEK293
    biomaterial_provider VARCHAR(200),           -- 样本提供机构
    
    -- 质控信息
    is_primary_data BOOLEAN DEFAULT true,        -- 是否原始样本
    has_multiple_versions BOOLEAN DEFAULT false, -- 是否有多个版本
    version_count INTEGER DEFAULT 1,             -- 版本数量
    
    -- 统计信息
    total_cell_count BIGINT,                     -- 该样本所有版本的细胞总数
    data_source_count INTEGER,                   -- 来源数据库数量
    
    -- 时间戳
    first_seen_date DATE,                        -- 首次出现时间
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 约束
    CONSTRAINT chk_organism CHECK (organism IN ('Homo sapiens', 'Mus musculus', 'Macaca mulatta', 'Rattus norvegicus', 'Danio rerio')),
    CONSTRAINT chk_sex CHECK (sex IN ('male', 'female', 'unknown', 'mixed'))
);

-- 索引
CREATE INDEX idx_samples_organism ON samples(organism);
CREATE INDEX idx_samples_tissue ON samples(tissue);
CREATE INDEX idx_samples_cell_type ON samples(cell_type);
CREATE INDEX idx_samples_disease ON samples(disease);
CREATE INDEX idx_samples_individual ON samples(individual_id);
CREATE INDEX idx_samples_identity_hash ON samples(biological_identity_hash);
```

### 2.2 projects - 研究项目表

```sql
CREATE TABLE projects (
    project_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 项目标识（不强制唯一，因为同一项目可能在不同数据库有不同记录）
    project_id VARCHAR(100) NOT NULL,            -- GSE100118/PRJNA625920
    project_id_type VARCHAR(50) NOT NULL,        -- geo/bioproject/arrayexpress/cngb/ega/scp
    
    -- 项目信息
    title TEXT NOT NULL,
    description TEXT,
    study_type VARCHAR(100),                     -- scRNA-seq/spatial/multiome
    
    -- 生物学信息
    organism VARCHAR(100),
    organism_taxid INTEGER,
    disease_focus VARCHAR(200),
    
    -- 文献信息
    pmid VARCHAR(50),
    pmcid VARCHAR(50),
    doi VARCHAR(200),
    citation_count INTEGER,
    publication_date DATE,
    
    -- 数据可用性
    data_availability VARCHAR(20),               -- open/controlled/private
    access_link TEXT,
    
    -- 统计
    sample_count INTEGER,
    total_cells BIGINT,
    file_count INTEGER,
    
    -- 来源
    source_database VARCHAR(50) NOT NULL,        -- geo/ncbi/ebi/cngb/ega/scp/cellxgene
    source_url TEXT,
    raw_metadata JSONB,                          -- 原始元数据完整存储
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 同一项目在不同数据库的记录关联
    canonical_project_fk UUID REFERENCES projects(project_pk), -- 指向规范化记录
    
    UNIQUE(project_id, source_database)
);

CREATE INDEX idx_projects_pmid ON projects(pmid);
CREATE INDEX idx_projects_doi ON projects(doi);
CREATE INDEX idx_projects_organism ON projects(organism);
CREATE INDEX idx_projects_source ON projects(source_database);
```

### 2.3 datasets - 数据集实例表

**关键设计**：一个样本可以有多个数据集（原始、处理、重分析）

```sql
CREATE TABLE datasets (
    dataset_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联关系
    sample_fk UUID REFERENCES samples(sample_pk),    -- 生物学样本
    project_fk UUID REFERENCES projects(project_pk), -- 所属项目
    
    -- 数据集标识
    dataset_id VARCHAR(100),                     -- CellXGene dataset_id / SCP accession
    dataset_id_type VARCHAR(50),                 -- cellxgene/scp/geo_superset/zenodo
    
    -- 数据集类型和版本
    dataset_type VARCHAR(50) NOT NULL,           -- raw/author_processed/db_processed/third_party
    dataset_version VARCHAR(50),                 -- v1/v2/1.0.0
    processing_pipeline VARCHAR(100),            -- cellranger/starscan/seurat/scanpy
    
    -- 如果是派生数据，记录父数据集
    parent_dataset_fk UUID REFERENCES datasets(dataset_pk),
    root_dataset_fk UUID REFERENCES datasets(dataset_pk), -- 追溯到最原始数据集
    
    -- 版本链信息
    version_depth INTEGER DEFAULT 0,             -- 距离root的深度
    version_path UUID[],                         -- 完整版本路径数组
    
    -- 数据特征
    assay VARCHAR(100),                          -- 10x 3' v3/Smart-seq2
    assay_ontology VARCHAR(50),                  -- EFO ID
    suspension_type VARCHAR(50),                 -- cell/nucleus
    
    -- 细胞统计
    cell_count INTEGER,
    gene_count INTEGER,
    mean_genes_per_cell FLOAT,
    
    -- 数据质量
    quality_score FLOAT,                         -- 质量评分0-1
    quality_metrics JSONB,                       -- 详细质控指标
    
    -- 文件信息（JSON数组）
    files JSONB,                                 -- [{file_type, url, size, format}, ...]
    
    -- 来源信息
    source_database VARCHAR(50) NOT NULL,
    source_url TEXT,
    raw_metadata JSONB,
    
    -- 时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_generation_date DATE,                   -- 数据实际产生时间
    
    UNIQUE(dataset_id, source_database, dataset_version)
);

-- 关键索引
CREATE INDEX idx_datasets_sample ON datasets(sample_fk);
CREATE INDEX idx_datasets_project ON datasets(project_fk);
CREATE INDEX idx_datasets_type ON datasets(dataset_type);
CREATE INDEX idx_datasets_root ON datasets(root_dataset_fk);
CREATE INDEX idx_datasets_parent ON datasets(parent_dataset_fk);
```

### 2.4 experiments - 测序实验表（原始数据层）

```sql
CREATE TABLE experiments (
    experiment_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    sample_fk UUID REFERENCES samples(sample_pk),
    project_fk UUID REFERENCES projects(project_pk),
    
    -- 实验标识
    experiment_id VARCHAR(100) NOT NULL,         -- SRX/ERX/CNX
    experiment_id_type VARCHAR(50),              -- srx/erx/cngb
    
    -- 测序技术
    library_strategy VARCHAR(50),                -- RNA-Seq
    library_source VARCHAR(50),                  -- TRANSCRIPTOMIC
    library_selection VARCHAR(100),              -- PCR/cDNA
    library_layout VARCHAR(20),                  -- SINGLE/PAIRED
    
    -- 平台信息
    platform VARCHAR(100),                       -- ILLUMINA
    platform_ontology VARCHAR(50),               -- EFO ID
    instrument_model VARCHAR(100),               -- NovaSeq 6000
    
    -- 单细胞特定
    single_cell_platform VARCHAR(100),           -- 10x Genomics
    chemistry_version VARCHAR(50),               -- v2/v3/5prime
    
    -- 测序统计
    run_count INTEGER,
    total_spots BIGINT,
    total_bases BIGINT,
    read_length INTEGER,
    
    -- 原始文件
    raw_files JSONB,                             -- FASTQ文件列表
    
    source_database VARCHAR(50),
    source_url TEXT,
    raw_metadata JSONB,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. 关联层表设计（核心创新）

### 3.1 entity_links - 实体关联表（构建数据网络）

这是**最核心的关联表**，构建样本-项目-数据集-实验之间的多对多关系。

```sql
CREATE TABLE entity_links (
    link_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 源实体
    source_type VARCHAR(50) NOT NULL,            -- sample/project/dataset/experiment
    source_pk UUID NOT NULL,
    source_id VARCHAR(100),                      -- 原始ID（便于查询）
    
    -- 目标实体
    target_type VARCHAR(50) NOT NULL,
    target_pk UUID NOT NULL,
    target_id VARCHAR(100),
    
    -- 关系类型
    relationship_type VARCHAR(50) NOT NULL,      -- has_dataset/has_experiment/belongs_to/derived_from/version_of
    relationship_confidence VARCHAR(20),         -- high/medium/low
    
    -- 关系元数据
    link_metadata JSONB,                         -- 关系详细信息
    
    -- 来源
    source_database VARCHAR(50),
    link_reason TEXT,                            -- 为什么建立这个链接（用于审计）
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 约束：避免重复链接
    UNIQUE(source_type, source_pk, target_type, target_pk, relationship_type)
);

-- 关键索引：支持各种方向的查询
CREATE INDEX idx_links_source ON entity_links(source_type, source_pk);
CREATE INDEX idx_links_target ON entity_links(target_type, target_pk);
CREATE INDEX idx_links_relationship ON entity_links(relationship_type);
CREATE INDEX idx_links_type_pair ON entity_links(source_type, target_type);
```

**关系类型定义**:
- `belongs_to`: sample → project (样本属于项目)
- `has_experiment`: sample → experiment (样本有测序实验)
- `has_dataset`: sample → dataset (样本有数据集)
- `derived_from`: dataset → dataset (数据集派生关系)
- `version_of`: dataset → dataset (版本关系)
- `same_as`: sample → sample (同一生物学样本在不同数据库)

### 3.2 id_mappings - ID映射表（跨数据库去重）

```sql
CREATE TABLE id_mappings (
    mapping_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 实体信息
    entity_type VARCHAR(50) NOT NULL,            -- sample/project/dataset/experiment
    entity_pk UUID NOT NULL,
    
    -- ID信息
    id_type VARCHAR(50) NOT NULL,                -- gsm/biosample/samea/doi/pmid
    id_value VARCHAR(200) NOT NULL,
    id_source_database VARCHAR(50),              -- 该ID来自哪个数据库
    
    -- 映射质量
    is_canonical BOOLEAN DEFAULT false,          -- 是否规范化ID
    confidence VARCHAR(20),                      -- high/medium/low
    
    -- 原始上下文
    raw_context JSONB,                           -- ID出现的原始上下文
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(entity_type, entity_pk, id_type, id_value)
);

CREATE INDEX idx_id_mappings_entity ON id_mappings(entity_type, entity_pk);
CREATE INDEX idx_id_mappings_lookup ON id_mappings(id_type, id_value);
CREATE INDEX idx_id_mappings_canonical ON id_mappings(entity_type, id_value) WHERE is_canonical = true;
```

### 3.3 version_tree - 版本树表（追踪数据血缘）

```sql
CREATE TABLE version_tree (
    tree_pk UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 根节点（最原始的数据）
    root_dataset_fk UUID REFERENCES datasets(dataset_pk),
    root_sample_fk UUID REFERENCES samples(sample_pk),
    
    -- 节点信息
    node_dataset_fk UUID REFERENCES datasets(dataset_pk),
    node_type VARCHAR(50),                       -- root/branch/leaf
    
    -- 树形结构（闭包表设计）
    parent_node_fk UUID REFERENCES version_tree(tree_pk),
    node_depth INTEGER,                          -- 深度
    node_path UUID[],                            -- 根到当前节点的路径
    
    -- 派生信息
    derivation_method VARCHAR(100),              -- 派生方法
    derivation_params JSONB,                     -- 派生参数
    
    -- 统计
    subtree_dataset_count INTEGER,               -- 子树数据集数量
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_version_tree_root ON version_tree(root_dataset_fk);
CREATE INDEX idx_version_tree_node ON version_tree(node_dataset_fk);
CREATE INDEX idx_version_tree_parent ON version_tree(parent_node_fk);
```

---

## 4. 统一视图设计（核心需求）

### 4.1 unified_single_cell_view - 统一查询视图

这是**给用户展示的核心视图**，将多表数据串联成一条完整记录。

```sql
CREATE OR REPLACE VIEW unified_single_cell_view AS
WITH sample_aggregates AS (
    -- 预聚合每个样本的数据集和项目信息
    SELECT 
        s.sample_pk,
        s.organism,
        s.organism_taxid,
        s.tissue,
        s.tissue_ontology,
        s.cell_type,
        s.cell_type_ontology,
        s.disease,
        s.disease_ontology,
        s.sex,
        s.age_value,
        s.age_unit,
        s.developmental_stage,
        s.ethnicity,
        s.individual_id,
        s.sample_source_type,
        s.cell_line,
        s.total_cell_count,
        s.data_source_count,
        
        -- 聚合所有相关项目
        jsonb_agg(DISTINCT jsonb_build_object(
            'project_pk', p.project_pk,
            'project_id', p.project_id,
            'project_id_type', p.project_id_type,
            'title', p.title,
            'pmid', p.pmid,
            'doi', p.doi,
            'citation_count', p.citation_count,
            'publication_date', p.publication_date,
            'source_database', p.source_database,
            'source_url', p.source_url
        )) FILTER (WHERE p.project_pk IS NOT NULL) AS projects,
        
        -- 聚合所有数据集（包括版本链）
        jsonb_agg(DISTINCT jsonb_build_object(
            'dataset_pk', d.dataset_pk,
            'dataset_id', d.dataset_id,
            'dataset_type', d.dataset_type,
            'dataset_version', d.dataset_version,
            'processing_pipeline', d.processing_pipeline,
            'assay', d.assay,
            'cell_count', d.cell_count,
            'gene_count', d.gene_count,
            'quality_score', d.quality_score,
            'files', d.files,
            'source_database', d.source_database,
            'parent_dataset_fk', d.parent_dataset_fk,
            'root_dataset_fk', d.root_dataset_fk,
            'version_depth', d.version_depth
        )) FILTER (WHERE d.dataset_pk IS NOT NULL) AS datasets,
        
        -- 聚合所有原始实验
        jsonb_agg(DISTINCT jsonb_build_object(
            'experiment_pk', e.experiment_pk,
            'experiment_id', e.experiment_id,
            'library_strategy', e.library_strategy,
            'platform', e.platform,
            'instrument_model', e.instrument_model,
            'single_cell_platform', e.single_cell_platform,
            'chemistry_version', e.chemistry_version,
            'run_count', e.run_count,
            'total_spots', e.total_spots,
            'raw_files', e.raw_files,
            'source_database', e.source_database
        )) FILTER (WHERE e.experiment_pk IS NOT NULL) AS experiments,
        
        -- 聚合所有ID
        jsonb_object_agg(DISTINCT im.id_type, im.id_value) 
            FILTER (WHERE im.id_type IS NOT NULL) AS all_identifiers,
        
        -- 计算版本链统计
        COUNT(DISTINCT d.dataset_pk) FILTER (WHERE d.dataset_type = 'raw') AS raw_dataset_count,
        COUNT(DISTINCT d.dataset_pk) FILTER (WHERE d.dataset_type = 'author_processed') AS author_processed_count,
        COUNT(DISTINCT d.dataset_pk) FILTER (WHERE d.dataset_type = 'db_processed') AS db_processed_count,
        COUNT(DISTINCT d.dataset_pk) FILTER (WHERE d.dataset_type = 'third_party') AS third_party_count
        
    FROM samples s
    LEFT JOIN entity_links el_p ON s.sample_pk = el_p.source_pk 
        AND el_p.source_type = 'sample' 
        AND el_p.target_type = 'project'
    LEFT JOIN projects p ON el_p.target_pk = p.project_pk
    LEFT JOIN entity_links el_d ON s.sample_pk = el_d.source_pk 
        AND el_d.source_type = 'sample' 
        AND el_d.target_type = 'dataset'
    LEFT JOIN datasets d ON el_d.target_pk = d.dataset_pk
    LEFT JOIN entity_links el_e ON s.sample_pk = el_e.source_pk 
        AND el_e.source_type = 'sample' 
        AND el_e.target_type = 'experiment'
    LEFT JOIN experiments e ON el_e.target_pk = e.experiment_pk
    LEFT JOIN id_mappings im ON im.entity_type = 'sample' AND im.entity_pk = s.sample_pk
    GROUP BY s.sample_pk
)
SELECT 
    sa.*,
    
    -- 生成版本链JSON（按root_dataset_fk分组）
    (
        SELECT jsonb_agg(version_chain)
        FROM (
            SELECT jsonb_build_object(
                'root_dataset', jsonb_build_object(
                    'dataset_pk', root_d.dataset_pk,
                    'dataset_id', root_d.dataset_id,
                    'source_database', root_d.source_database
                ),
                'versions', jsonb_agg(jsonb_build_object(
                    'dataset_pk', d.dataset_pk,
                    'dataset_id', d.dataset_id,
                    'dataset_type', d.dataset_type,
                    'version_depth', d.version_depth,
                    'processing_pipeline', d.processing_pipeline,
                    'cell_count', d.cell_count,
                    'files', d.files
                ) ORDER BY d.version_depth)
            ) AS version_chain
            FROM datasets d
            JOIN datasets root_d ON d.root_dataset_fk = root_d.dataset_pk
            WHERE d.sample_fk = sa.sample_pk
            GROUP BY root_d.dataset_pk, root_d.dataset_id, root_d.source_database
        ) subq
    ) AS version_chains,
    
    -- 生成推荐的最佳数据集（优先已处理的高质量数据）
    (
        SELECT jsonb_build_object(
            'dataset_pk', best_d.dataset_pk,
            'dataset_id', best_d.dataset_id,
            'dataset_type', best_d.dataset_type,
            'source_database', best_d.source_database,
            'quality_score', best_d.quality_score,
            'cell_count', best_d.cell_count,
            'files', best_d.files
        )
        FROM datasets best_d
        WHERE best_d.sample_fk = sa.sample_pk
        ORDER BY 
            CASE best_d.dataset_type 
                WHEN 'db_processed' THEN 1 
                WHEN 'author_processed' THEN 2 
                WHEN 'third_party' THEN 3 
                WHEN 'raw' THEN 4 
            END,
            best_d.quality_score DESC NULLS LAST,
            best_d.cell_count DESC NULLS LAST
        LIMIT 1
    ) AS recommended_dataset,
    
    -- 数据完整性评分
    (
        CASE WHEN sa.tissue IS NOT NULL THEN 20 ELSE 0 END +
        CASE WHEN sa.cell_type IS NOT NULL THEN 20 ELSE 0 END +
        CASE WHEN sa.disease IS NOT NULL THEN 15 ELSE 0 END +
        CASE WHEN sa.sex IS NOT NULL THEN 10 ELSE 0 END +
        CASE WHEN sa.age_value IS NOT NULL THEN 10 ELSE 0 END +
        CASE WHEN sa.developmental_stage IS NOT NULL THEN 10 ELSE 0 END +
        CASE WHEN sa.ethnicity IS NOT NULL THEN 5 ELSE 0 END +
        CASE WHEN sa.datasets IS NOT NULL THEN 10 ELSE 0 END
    ) AS metadata_completeness_score
    
FROM sample_aggregates sa;
```

### 4.2 物化视图（用于高性能查询）

```sql
-- 创建物化视图以提高查询性能
CREATE MATERIALIZED VIEW unified_single_cell_view_mv AS
SELECT * FROM unified_single_cell_view;

-- 创建索引
CREATE INDEX idx_mv_organism ON unified_single_cell_view_mv(organism);
CREATE INDEX idx_mv_tissue ON unified_single_cell_view_mv(tissue);
CREATE INDEX idx_mv_cell_type ON unified_single_cell_view_mv(cell_type);
CREATE INDEX idx_mv_disease ON unified_single_cell_view_mv(disease);
CREATE INDEX idx_mv_individual ON unified_single_cell_view_mv(individual_id);
CREATE INDEX idx_mv_completeness ON unified_single_cell_view_mv(metadata_completeness_score);

-- 刷新策略：每日凌晨或增量更新
-- REFRESH MATERIALIZED VIEW CONCURRENTLY unified_single_cell_view_mv;
```

---

## 5. 关键查询示例

### 5.1 查询特定样本的所有版本

```sql
-- 查找individual_id为"Donor_001"的所有数据版本
SELECT 
    sample_pk,
    organism,
    tissue,
    cell_type,
    datasets
FROM unified_single_cell_view
WHERE individual_id = 'Donor_001'
  AND organism = 'Homo sapiens';
```

### 5.2 查询跨数据库的同一数据

```sql
-- 查找通过BioSample ID关联的所有记录
WITH target_sample AS (
    SELECT entity_pk AS sample_pk
    FROM id_mappings
    WHERE id_type = 'biosample' AND id_value = 'SAMN12345678'
)
SELECT 
    s.sample_pk,
    s.organism,
    s.tissue,
    s.disease,
    jsonb_pretty(s.all_identifiers) AS all_ids,
    s.projects,
    s.datasets
FROM unified_single_cell_view s
JOIN target_sample t ON s.sample_pk = t.sample_pk;
```

### 5.3 查询版本链

```sql
-- 查找特定数据集的完整版本链
WITH RECURSIVE version_chain AS (
    -- 起点：特定数据集
    SELECT 
        dataset_pk,
        dataset_id,
        parent_dataset_fk,
        root_dataset_fk,
        dataset_type,
        0 AS level,
        ARRAY[dataset_pk] AS path
    FROM datasets
    WHERE dataset_id = 'e3ed2ba4-edf5-40ac-8750-8a417ad1eefe'
    
    UNION ALL
    
    -- 递归查找父数据集
    SELECT 
        d.dataset_pk,
        d.dataset_id,
        d.parent_dataset_fk,
        d.root_dataset_fk,
        d.dataset_type,
        vc.level + 1,
        d.dataset_pk || vc.path
    FROM datasets d
    JOIN version_chain vc ON d.dataset_pk = vc.parent_dataset_fk
    WHERE NOT d.dataset_pk = ANY(vc.path) -- 避免循环
)
SELECT 
    dataset_pk,
    dataset_id,
    dataset_type,
    level,
    path
FROM version_chain
ORDER BY level DESC;
```

### 5.4 全文搜索

```sql
-- 在PostgreSQL中使用全文搜索（需要额外配置）
SELECT 
    sample_pk,
    organism,
    tissue,
    cell_type,
    disease,
    projects->0->>'title' AS project_title
FROM unified_single_cell_view
WHERE 
    to_tsvector('english', 
        coalesce(tissue, '') || ' ' || 
        coalesce(cell_type, '') || ' ' || 
        coalesce(disease, '')
    ) @@ plainto_tsquery('english', 'liver cancer hepatocyte');
```

---

## 6. 数据血缘追踪设计

### 6.1 血缘查询函数

```sql
-- 获取数据的完整血缘树
CREATE OR REPLACE FUNCTION get_data_lineage(p_sample_pk UUID)
RETURNS TABLE (
    level INTEGER,
    entity_type VARCHAR,
    entity_id VARCHAR,
    entity_name VARCHAR,
    relationship VARCHAR,
    source_database VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE lineage AS (
        -- 起点：样本
        SELECT 
            0 AS lvl,
            'sample'::VARCHAR AS etype,
            s.sample_pk::VARCHAR AS eid,
            s.individual_id::VARCHAR AS ename,
            'root'::VARCHAR AS rel,
            'unified'::VARCHAR AS src
        FROM samples s
        WHERE s.sample_pk = p_sample_pk
        
        UNION ALL
        
        -- 向上追溯实验
        SELECT 
            l.lvl + 1,
            'experiment'::VARCHAR,
            e.experiment_id::VARCHAR,
            e.instrument_model::VARCHAR,
            'sequenced_by'::VARCHAR,
            e.source_database::VARCHAR
        FROM lineage l
        JOIN entity_links el ON l.eid::UUID = el.source_pk 
            AND el.source_type = 'sample' 
            AND el.target_type = 'experiment'
        JOIN experiments e ON el.target_pk = e.experiment_pk
        
        UNION ALL
        
        -- 向上追溯数据集
        SELECT 
            l.lvl + 1,
            'dataset'::VARCHAR,
            d.dataset_id::VARCHAR,
            d.dataset_type::VARCHAR,
            CASE 
                WHEN d.dataset_type = 'raw' THEN 'raw_data'::VARCHAR
                WHEN d.dataset_type = 'author_processed' THEN 'processed_by_author'::VARCHAR
                WHEN d.dataset_type = 'db_processed' THEN 'processed_by_db'::VARCHAR
                ELSE 'derived'::VARCHAR
            END,
            d.source_database::VARCHAR
        FROM lineage l
        JOIN entity_links el ON l.eid::UUID = el.source_pk 
            AND el.source_type = 'sample' 
            AND el.target_type = 'dataset'
        JOIN datasets d ON el.target_pk = d.dataset_pk
        
        UNION ALL
        
        -- 追溯版本链
        SELECT 
            l.lvl + 1,
            'dataset'::VARCHAR,
            child.dataset_id::VARCHAR,
            child.dataset_type::VARCHAR,
            'version_of'::VARCHAR,
            child.source_database::VARCHAR
        FROM lineage l
        JOIN datasets child ON child.parent_dataset_fk = l.eid::UUID
        WHERE l.etype = 'dataset'
    )
    SELECT * FROM lineage;
END;
$$ LANGUAGE plpgsql;
```

---

## 7. 与上一版方案的对比

| 特性 | v1.0 方案 | v2.0 方案（当前） |
|------|----------|------------------|
| 核心实体 | 分散的多表 | 以sample为中心的星型模型 |
| 版本追踪 | 简单字段 | 完整的版本树+血缘追踪 |
| 统一视图 | 概念设计 | 完整的SQL视图实现 |
| 跨库关联 | ID映射表 | entity_links网络+ID映射 |
| 查询复杂度 | 高（多表JOIN） | 低（预聚合视图） |
| 扩展性 | 中等 | 高（JSONB灵活字段） |
| 数据完整性 | 基础约束 | 多层校验+评分 |

