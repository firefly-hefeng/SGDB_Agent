# 示例数据流程验证

## 场景：一个肝癌样本的完整数据生命周期（帮助你理解不同数据库id混杂可能的情况，更好的设计该schema体系）

### 背景故事
某位研究者对肝癌组织进行了单细胞测序，数据逐步出现在各个数据库中...

---

## Step 1: 原始数据提交到GEO/SRA

**时间点**: 2023-01-15
**研究者**: 提交原始FASTQ到GEO

### GEO原始记录 (GSE200001)
```json
{
  "Series_id": "GSE200001",
  "Series_Title": "Single cell RNA-seq of hepatocellular carcinoma",
  "Series_Summary": "We performed scRNA-seq on 6 HCC patient tumor samples...",
  "Series_PubMed_ID": "37012345",
  "Sample_id": "GSM6000001",
  "Sample_Title": "HCC_Patient_1_Tumor",
  "Source_name": "liver tumor tissue",
  "Sample_Organism": "Homo sapiens",
  "Characteristics": {
    "patient_id": "HCC001",
    "disease": "hepatocellular carcinoma",
    "tissue": "liver",
    "sex": "male",
    "age": "55"
  },
  "Instrument_model": "Illumina NovaSeq 6000",
  "Library_strategy": "RNA-Seq"
}
```

### SRA原始记录 (关联GSM)
```json
{
  "experiment_id": "SRX9000001",
  "run_id": "SRR10000001",
  "biosample": "SAMN15000001",
  "total_spots": 284500000,
  "total_bases": 85750000000,
  "platform": "ILLUMINA",
  "instrument": "Illumina NovaSeq 6000"
}
```

---

## Step 2: 数据进入我们的数据库

### 2.1 samples表 - 创建样本记录

```sql
INSERT INTO samples (
    sample_pk,
    biological_identity_hash,
    organism,
    organism_taxid,
    tissue,
    tissue_ontology,
    cell_type,
    disease,
    disease_ontology,
    sex,
    age_value,
    age_unit,
    individual_id,
    sample_source_type,
    has_multiple_versions,
    version_count,
    total_cell_count,
    data_source_count
) VALUES (
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',  -- sample_pk
    'b8f9c2d1e3a4f5b6c7d8e9f0a1b2c3d4',       -- MD5(Homo sapiens:liver:HCC001:hepatocellular carcinoma:adult)
    'Homo sapiens',
    9606,
    'liver',
    'UBERON:0002107',
    NULL,  -- 原始数据还没有细胞类型注释
    'hepatocellular carcinoma',
    'MONDO:0007256',
    'male',
    '55',
    'year',
    'HCC001',
    'tissue',
    false,
    1,
    0,  -- 原始数据还不知道细胞数
    1
);
```

### 2.2 projects表 - 创建项目记录

```sql
-- GEO项目记录
INSERT INTO projects (
    project_pk,
    project_id,
    project_id_type,
    title,
    description,
    organism,
    pmid,
    citation_count,
    publication_date,
    data_availability,
    access_link,
    sample_count,
    source_database,
    source_url
) VALUES (
    'p1111111-2222-3333-4444-555555555555',
    'GSE200001',
    'geo_series',
    'Single cell RNA-seq of hepatocellular carcinoma',
    'We performed scRNA-seq on 6 HCC patient tumor samples...',
    'Homo sapiens',
    '37012345',
    12,
    '2023-03-15',
    'open',
    'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE200001',
    6,
    'geo',
    'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE200001'
);

-- SRA/BioProject记录（同一研究）
INSERT INTO projects (
    project_pk,
    project_id,
    project_id_type,
    title,
    pmid,
    source_database,
    canonical_project_fk  -- 指向GEO记录作为规范版本
) VALUES (
    'p6666666-7777-8888-9999-000000000000',
    'PRJNA800001',
    'bioproject',
    'Single cell RNA-seq of hepatocellular carcinoma',
    '37012345',
    'ncbi_sra',
    'p1111111-2222-3333-4444-555555555555'  -- 关联到GEO记录
);
```

### 2.3 experiments表 - 记录测序实验

```sql
INSERT INTO experiments (
    experiment_pk,
    sample_fk,
    project_fk,
    experiment_id,
    experiment_id_type,
    library_strategy,
    library_source,
    library_layout,
    platform,
    platform_ontology,
    instrument_model,
    single_cell_platform,
    run_count,
    total_spots,
    total_bases,
    raw_files,
    source_database
) VALUES (
    'e1111111-2222-3333-4444-555555555555',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',  -- sample_fk
    'p6666666-7777-8888-9999-000000000000',  -- project_fk (SRA)
    'SRX9000001',
    'srx',
    'RNA-Seq',
    'TRANSCRIPTOMIC',
    'PAIRED',
    'ILLUMINA',
    'EFO:0002699',
    'Illumina NovaSeq 6000',
    '10x Genomics 3\' v3',
    1,
    284500000,
    85750000000,
    '[
        {"file_name": "SRR10000001_1.fastq.gz", "size": 2147483648, "md5": "abc123..."},
        {"file_name": "SRR10000001_2.fastq.gz", "size": 2147483648, "md5": "def456..."}
    ]'::jsonb,
    'ncbi_sra'
);
```

### 2.4 datasets表 - 创建raw数据集

```sql
INSERT INTO datasets (
    dataset_pk,
    sample_fk,
    project_fk,
    dataset_id,
    dataset_id_type,
    dataset_type,
    dataset_version,
    root_dataset_fk,
    version_depth,
    version_path,
    assay,
    assay_ontology,
    cell_count,
    gene_count,
    files,
    source_database
) VALUES (
    'd1111111-2222-3333-4444-555555555555',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'p6666666-7777-8888-9999-000000000000',
    'GSE200001_GSM6000001',
    'geo_superset',
    'raw',
    '1.0',
    'd1111111-2222-3333-4444-555555555555',  -- root指向自己
    0,
    ARRAY['d1111111-2222-3333-4444-555555555555']::UUID[],
    '10x 3\' v3',
    'EFO:0009922',
    0,  -- raw数据还不知道确切细胞数
    0,
    '[
        {"file_type": "fastq", "format": "FASTQ", "url": "ftp://...", "size": 4294967296}
    ]'::jsonb,
    'geo'
);
```

### 2.5 entity_links表 - 建立关联

```sql
-- sample -> project (GEO)
INSERT INTO entity_links (
    source_type, source_pk, target_type, target_pk,
    relationship_type, relationship_confidence, source_database
) VALUES ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
          'project', 'p1111111-2222-3333-4444-555555555555',
          'belongs_to', 'high', 'geo');

-- sample -> experiment (SRA)
INSERT INTO entity_links (
    source_type, source_pk, target_type, target_pk,
    relationship_type, relationship_confidence, source_database
) VALUES ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
          'experiment', 'e1111111-2222-3333-4444-555555555555',
          'has_experiment', 'high', 'ncbi_sra');

-- sample -> dataset
INSERT INTO entity_links (
    source_type, source_pk, target_type, target_pk,
    relationship_type, relationship_confidence, source_database
) VALUES ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
          'dataset', 'd1111111-2222-3333-4444-555555555555',
          'has_dataset', 'high', 'geo');
```

### 2.6 id_mappings表 - ID映射

```sql
-- 样本ID映射
INSERT INTO id_mappings (entity_type, entity_pk, id_type, id_value, is_canonical, confidence, id_source_database)
VALUES 
    ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'gsm', 'GSM6000001', false, 'high', 'geo'),
    ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'biosample', 'SAMN15000001', true, 'high', 'ncbi'),
    ('sample', 'a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'individual_id', 'HCC001', false, 'high', 'geo');

-- 项目ID映射
INSERT INTO id_mappings (entity_type, entity_pk, id_type, id_value, is_canonical, confidence, id_source_database)
VALUES
    ('project', 'p1111111-2222-3333-4444-555555555555', 'geo_series', 'GSE200001', true, 'high', 'geo'),
    ('project', 'p6666666-7777-8888-9999-000000000000', 'bioproject', 'PRJNA800001', false, 'high', 'ncbi'),
    ('project', 'p1111111-2222-3333-4444-555555555555', 'pmid', '37012345', false, 'high', 'pubmed');
```

---

## Step 3: 作者处理后上传到CellXGene

**时间点**: 2023-06-20
**事件**: 研究者使用Seurat处理数据后上传到CellXGene

### CellXGene记录
```json
{
  "dataset_id": "hcc-2023-001-liver",
  "collection_id": "hcc-atlas-2023",
  "title": "HCC Patient 1 Tumor - Processed",
  "organisms": ["Homo sapiens"],
  "tissues": ["liver", "liver tumor"],
  "diseases": ["hepatocellular carcinoma"],
  "cell_types": ["hepatocyte", "T cell", "macrophage", "tumor cell"],
  "assays": ["10x 3' v3"],
  "cell_count": 8523,
  "sexes": ["male"],
  "development_stages": ["55-year-old stage"],
  "asset_h5ad_url": "https://datasets.cellxgene.cziscience.com/hcc-2023-001-liver.h5ad"
}
```

### 数据库更新

```sql
-- 更新samples表（增加统计信息）
UPDATE samples SET
    cell_type = 'hepatocyte',
    cell_type_ontology = 'CL:0000182',
    total_cell_count = 8523,
    has_multiple_versions = true,
    version_count = 2,
    last_updated = NOW()
WHERE sample_pk = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

-- 添加CellXGene项目记录
INSERT INTO projects (
    project_pk, project_id, project_id_type, title,
    organism, pmid, doi, source_database, source_url, canonical_project_fk
) VALUES (
    'pccccccc-dddd-eeee-ffff-000000000000',
    'hcc-atlas-2023',
    'cellxgene_collection',
    'HCC Atlas 2023',
    'Homo sapiens',
    '37012345',
    '10.1234/hcc.2023.001',
    'cellxgene',
    'https://cellxgene.cziscience.com/collections/hcc-atlas-2023',
    'p1111111-2222-3333-4444-555555555555'
);

-- 添加新数据集（作者处理版本）
INSERT INTO datasets (
    dataset_pk, sample_fk, project_fk, dataset_id, dataset_id_type,
    dataset_type, dataset_version, processing_pipeline,
    parent_dataset_fk, root_dataset_fk, version_depth, version_path,
    assay, cell_count, gene_count, quality_score, files, source_database
) VALUES (
    'dccccccc-dddd-eeee-ffff-000000000000',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'pccccccc-dddd-eeee-ffff-000000000000',
    'hcc-2023-001-liver',
    'cellxgene_dataset',
    'author_processed',
    '1.0',
    'Seurat v4',
    'd1111111-2222-3333-4444-555555555555',  -- 指向raw数据集
    'd1111111-2222-3333-4444-555555555555',  -- root还是raw
    1,  -- 深度+1
    ARRAY['d1111111-2222-3333-4444-555555555555', 'dccccccc-dddd-eeee-ffff-000000000000']::UUID[],
    '10x 3\' v3',
    8523,
    33546,
    0.92,
    '[
        {"file_type": "h5ad", "format": "H5AD", "url": "https://...", "size": 154857600}
    ]'::jsonb,
    'cellxgene'
);

-- 添加ID映射
INSERT INTO id_mappings (entity_type, entity_pk, id_type, id_value, is_canonical, confidence, id_source_database)
VALUES ('dataset', 'dccccccc-dddd-eeee-ffff-000000000000', 'cellxgene_dataset', 'hcc-2023-001-liver', false, 'high', 'cellxgene');
```

---

## Step 4: CellXGene官方重处理

**时间点**: 2024-01-10
**事件**: CellXGene官方使用统一pipeline重新处理数据

```sql
-- 添加官方处理版本
INSERT INTO datasets (
    dataset_pk, sample_fk, project_fk, dataset_id, dataset_id_type,
    dataset_type, dataset_version, processing_pipeline,
    parent_dataset_fk, root_dataset_fk, version_depth, version_path,
    assay, cell_count, gene_count, quality_score, files, source_database
) VALUES (
    'd7777777-8888-9999-aaaa-bbbbbbbbbbbb',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'pccccccc-dddd-eeee-ffff-000000000000',
    'hcc-2023-001-liver-cxg-v2',
    'cellxgene_dataset',
    'db_processed',
    '2.0',
    'CellXGene Standard Pipeline v2',
    'dccccccc-dddd-eeee-ffff-000000000000',  -- 指向作者处理版本
    'd1111111-2222-3333-4444-555555555555',  -- root仍是raw
    2,  -- 深度+1
    ARRAY['d1111111-2222-3333-4444-555555555555', 
          'dccccccc-dddd-eeee-ffff-000000000000',
          'd7777777-8888-9999-aaaa-bbbbbbbbbbbb']::UUID[],
    '10x 3\' v3',
    8125,  -- 质控后细胞数减少
    36542,
    0.95,  -- 质量评分更高
    '[
        {"file_type": "h5ad", "format": "H5AD", "url": "https://...", "size": 148576000},
        {"file_type": "rds", "format": "RDS", "url": "https://...", "size": 198576000}
    ]'::jsonb,
    'cellxgene'
);

-- 更新samples统计
UPDATE samples SET
    version_count = 3,
    last_updated = NOW()
WHERE sample_pk = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
```

---

## Step 5: 第三方重分析上传到Zenodo

**时间点**: 2024-03-05
**事件**: 另一研究团队下载数据后使用不同方法重分析并分享

```sql
-- 添加第三方处理版本
INSERT INTO datasets (
    dataset_pk, sample_fk, project_fk, dataset_id, dataset_id_type,
    dataset_type, dataset_version, processing_pipeline,
    parent_dataset_fk, root_dataset_fk, version_depth, version_path,
    assay, cell_count, gene_count, quality_score, files, source_database
) VALUES (
    'd9999999-0000-1111-2222-333333333333',
    'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    'p9999999-0000-1111-2222-333333333333',  -- 新项目
    '10.5281/zenodo.1234567',
    'doi_dataset',
    'third_party',
    '1.0',
    'Scanpy + scVI',
    'd1111111-2222-3333-4444-555555555555',  -- 直接从raw派生
    'd1111111-2222-3333-4444-555555555555',
    1,  -- 深度1（不同于官方版本链）
    ARRAY['d1111111-2222-3333-4444-555555555555', 
          'd9999999-0000-1111-2222-333333333333']::UUID[],
    '10x 3\' v3',
    9234,
    31245,
    0.88,
    '[
        {"file_type": "h5ad", "format": "H5AD", "url": "https://zenodo.org/...", "size": 162857600}
    ]'::jsonb,
    'zenodo'
);

-- 更新samples统计
UPDATE samples SET
    version_count = 4,
    data_source_count = 4,  -- GEO, SRA, CellXGene, Zenodo
    last_updated = NOW()
WHERE sample_pk = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
```

---

## Step 6: 统一视图呈现

### 查询统一视图

```sql
SELECT 
    sample_pk,
    organism,
    tissue,
    cell_type,
    disease,
    sex,
    age_value,
    individual_id,
    version_count,
    total_cell_count,
    jsonb_pretty(projects) AS projects,
    jsonb_pretty(datasets) AS datasets,
    jsonb_pretty(version_chains) AS version_chains,
    jsonb_pretty(recommended_dataset) AS recommended_dataset,
    metadata_completeness_score
FROM unified_single_cell_view
WHERE individual_id = 'HCC001';
```

### 预期输出结果

```json
{
  "sample_pk": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "organism": "Homo sapiens",
  "tissue": "liver",
  "cell_type": "hepatocyte",
  "disease": "hepatocellular carcinoma",
  "sex": "male",
  "age_value": "55",
  "individual_id": "HCC001",
  "version_count": 4,
  "total_cell_count": 25882,
  "data_source_count": 4,
  
  "projects": [
    {
      "project_pk": "p1111111-2222-3333-4444-555555555555",
      "project_id": "GSE200001",
      "project_id_type": "geo_series",
      "title": "Single cell RNA-seq of hepatocellular carcinoma",
      "pmid": "37012345",
      "doi": null,
      "citation_count": 12,
      "publication_date": "2023-03-15",
      "source_database": "geo",
      "source_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE200001"
    },
    {
      "project_pk": "pccccccc-dddd-eeee-ffff-000000000000",
      "project_id": "hcc-atlas-2023",
      "project_id_type": "cellxgene_collection",
      "title": "HCC Atlas 2023",
      "pmid": "37012345",
      "doi": "10.1234/hcc.2023.001",
      "citation_count": 12,
      "publication_date": "2023-03-15",
      "source_database": "cellxgene",
      "source_url": "https://cellxgene.cziscience.com/collections/hcc-atlas-2023"
    }
  ],
  
  "datasets": [
    {
      "dataset_pk": "d1111111-2222-3333-4444-555555555555",
      "dataset_id": "GSE200001_GSM6000001",
      "dataset_type": "raw",
      "dataset_version": "1.0",
      "processing_pipeline": null,
      "assay": "10x 3' v3",
      "cell_count": 0,
      "gene_count": 0,
      "quality_score": null,
      "files": [{"file_type": "fastq", "format": "FASTQ", "url": "ftp://...", "size": 4294967296}],
      "source_database": "geo",
      "version_depth": 0
    },
    {
      "dataset_pk": "dccccccc-dddd-eeee-ffff-000000000000",
      "dataset_id": "hcc-2023-001-liver",
      "dataset_type": "author_processed",
      "dataset_version": "1.0",
      "processing_pipeline": "Seurat v4",
      "assay": "10x 3' v3",
      "cell_count": 8523,
      "gene_count": 33546,
      "quality_score": 0.92,
      "files": [{"file_type": "h5ad", "format": "H5AD", "url": "https://...", "size": 154857600}],
      "source_database": "cellxgene",
      "version_depth": 1
    },
    {
      "dataset_pk": "d7777777-8888-9999-aaaa-bbbbbbbbbbbb",
      "dataset_id": "hcc-2023-001-liver-cxg-v2",
      "dataset_type": "db_processed",
      "dataset_version": "2.0",
      "processing_pipeline": "CellXGene Standard Pipeline v2",
      "assay": "10x 3' v3",
      "cell_count": 8125,
      "gene_count": 36542,
      "quality_score": 0.95,
      "files": [
        {"file_type": "h5ad", "format": "H5AD", "url": "https://...", "size": 148576000},
        {"file_type": "rds", "format": "RDS", "url": "https://...", "size": 198576000}
      ],
      "source_database": "cellxgene",
      "version_depth": 2
    },
    {
      "dataset_pk": "d9999999-0000-1111-2222-333333333333",
      "dataset_id": "10.5281/zenodo.1234567",
      "dataset_type": "third_party",
      "dataset_version": "1.0",
      "processing_pipeline": "Scanpy + scVI",
      "assay": "10x 3' v3",
      "cell_count": 9234,
      "gene_count": 31245,
      "quality_score": 0.88,
      "files": [{"file_type": "h5ad", "format": "H5AD", "url": "https://zenodo.org/...", "size": 162857600}],
      "source_database": "zenodo",
      "version_depth": 1
    }
  ],
  
  "version_chains": [
    {
      "root_dataset": {
        "dataset_pk": "d1111111-2222-3333-4444-555555555555",
        "dataset_id": "GSE200001_GSM6000001",
        "source_database": "geo"
      },
      "versions": [
        {
          "dataset_pk": "d1111111-2222-3333-4444-555555555555",
          "dataset_id": "GSE200001_GSM6000001",
          "dataset_type": "raw",
          "version_depth": 0,
          "processing_pipeline": null,
          "cell_count": 0,
          "files": [{"file_type": "fastq", ...}]
        },
        {
          "dataset_pk": "dccccccc-dddd-eeee-ffff-000000000000",
          "dataset_id": "hcc-2023-001-liver",
          "dataset_type": "author_processed",
          "version_depth": 1,
          "processing_pipeline": "Seurat v4",
          "cell_count": 8523,
          "files": [{"file_type": "h5ad", ...}]
        },
        {
          "dataset_pk": "d7777777-8888-9999-aaaa-bbbbbbbbbbbb",
          "dataset_id": "hcc-2023-001-liver-cxg-v2",
          "dataset_type": "db_processed",
          "version_depth": 2,
          "processing_pipeline": "CellXGene Standard Pipeline v2",
          "cell_count": 8125,
          "files": [{"file_type": "h5ad", ...}, {"file_type": "rds", ...}]
        }
      ]
    },
    {
      "root_dataset": {
        "dataset_pk": "d1111111-2222-3333-4444-555555555555",
        "dataset_id": "GSE200001_GSM6000001",
        "source_database": "geo"
      },
      "versions": [
        {
          "dataset_pk": "d1111111-2222-3333-4444-555555555555",
          "dataset_id": "GSE200001_GSM6000001",
          "dataset_type": "raw",
          "version_depth": 0,
          "processing_pipeline": null,
          "cell_count": 0,
          "files": [{"file_type": "fastq", ...}]
        },
        {
          "dataset_pk": "d9999999-0000-1111-2222-333333333333",
          "dataset_id": "10.5281/zenodo.1234567",
          "dataset_type": "third_party",
          "version_depth": 1,
          "processing_pipeline": "Scanpy + scVI",
          "cell_count": 9234,
          "files": [{"file_type": "h5ad", ...}]
        }
      ]
    }
  ],
  
  "recommended_dataset": {
    "dataset_pk": "d7777777-8888-9999-aaaa-bbbbbbbbbbbb",
    "dataset_id": "hcc-2023-001-liver-cxg-v2",
    "dataset_type": "db_processed",
    "source_database": "cellxgene",
    "quality_score": 0.95,
    "cell_count": 8125,
    "files": [
      {"file_type": "h5ad", "format": "H5AD", "url": "https://...", "size": 148576000},
      {"file_type": "rds", "format": "RDS", "url": "https://...", "size": 198576000}
    ]
  },
  
  "metadata_completeness_score": 95
}
```

---

## Step 7: 用户查询场景

### 场景1: 研究者寻找肝癌单细胞数据

```sql
-- 查询所有肝癌数据，按质量评分排序
SELECT 
    sample_pk,
    organism,
    tissue,
    cell_type,
    disease,
    jsonb_pretty(recommended_dataset) AS best_dataset,
    metadata_completeness_score
FROM unified_single_cell_view
WHERE disease ILIKE '%hepatocellular carcinoma%'
  AND organism = 'Homo sapiens'
ORDER BY 
    (recommended_dataset->>'quality_score')::float DESC,
    metadata_completeness_score DESC
LIMIT 10;
```

### 场景2: 查找数据的完整历史

```sql
-- 查找特定样本的所有版本链
SELECT 
    sample_pk,
    individual_id,
    jsonb_pretty(version_chains) AS complete_history
FROM unified_single_cell_view
WHERE individual_id = 'HCC001';
```

### 场景3: 跨数据库查找同一数据

```sql
-- 通过BioSample ID查找所有关联记录
WITH target_samples AS (
    SELECT entity_pk AS sample_pk
    FROM id_mappings
    WHERE id_type = 'biosample' AND id_value = 'SAMN15000001'
)
SELECT 
    s.sample_pk,
    s.individual_id,
    s.tissue,
    s.disease,
    jsonb_agg(DISTINCT im.id_type || ':' || im.id_value) AS all_identifiers,
    jsonb_agg(DISTINCT d.source_database) AS available_in_databases
FROM samples s
JOIN target_samples t ON s.sample_pk = t.sample_pk
JOIN id_mappings im ON im.entity_pk = s.sample_pk AND im.entity_type = 'sample'
JOIN entity_links el ON el.source_pk = s.sample_pk 
    AND el.source_type = 'sample' 
    AND el.target_type = 'dataset'
JOIN datasets d ON el.target_pk = d.dataset_pk
GROUP BY s.sample_pk, s.individual_id, s.tissue, s.disease;
```

### 场景4: 数据血缘查询

```sql
-- 查询数据的完整血缘
SELECT * FROM get_data_lineage('a1b2c3d4-e5f6-7890-abcd-ef1234567890');

-- 预期输出:
-- level | entity_type | entity_id                | entity_name                      | relationship         | source_database
-- -------+-------------+--------------------------+----------------------------------+----------------------+----------------
--     0 | sample      | a1b2c3d4-...             | HCC001                           | root                 | unified
--     1 | experiment  | SRX9000001               | Illumina NovaSeq 6000            | sequenced_by         | ncbi_sra
--     1 | dataset     | GSE200001_GSM6000001     | raw                              | raw_data             | geo
--     2 | dataset     | hcc-2023-001-liver       | author_processed                 | processed_by_author  | cellxgene
--     3 | dataset     | hcc-2023-001-liver-cxg-v2| db_processed                     | processed_by_db      | cellxgene
--     2 | dataset     | 10.5281/zenodo.1234567   | third_party                      | derived              | zenodo
```

---

## 验证总结

这个示例验证了我们设计的Schema能够：

✅ **多表存储**: 数据分散在samples/projects/datasets/experiments表中，避免冗余

✅ **统一视图呈现**: 通过unified_single_cell_view将多表数据聚合为一条完整记录

✅ **版本追踪**: 清晰展示数据从raw → author_processed → db_processed的演变过程

✅ **跨数据库关联**: 通过id_mappings和entity_links建立GEO/SRA/CellXGene/Zenodo的关联

✅ **智能推荐**: 基于quality_score和dataset_type自动推荐最佳数据集

✅ **血缘追溯**: 通过version_chains和get_data_lineage函数追踪数据完整历史

