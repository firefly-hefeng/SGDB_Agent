# 统一单细胞元数据库 (Unified Single-Cell Metadata Database)

## 概览

将 12 个异构数据源的元数据统一为 4 层标准化 Schema，支持跨库查询、ID 映射和去重。

```
数据库文件: unified_metadata.db (SQLite, 1.1 GB)
总项目数:   23,123
总样本数:   756,579
细胞类型:   378,029 条注释
跨库链接:   9,966 条（高置信度）
去重候选:   100,000 条
```

---

## Schema 架构

### 4 层实体表

```
L1  unified_projects   ─── 研究项目 (GSE, PRJNA, Collection, E-MTAB...)
    │
L2  unified_series     ─── 数据系列 (SRP, Dataset, SCEA Experiment...)
    │
L3  unified_samples    ─── 生物样本 (GSM, BioSample SAMN/SAMEA, Donor...)
    │
L4  unified_celltypes  ─── 细胞类型注释 (B cell, T cell, macrophage...)
```

### 3 关系表

```
id_mappings         ─── 跨库 ID 映射 (GSM↔SAMN, PRJNA↔GSE, DOI↔PMID...)
entity_links        ─── 实体关系 (same_as, linked_via_pmid, linked_via_doi)
dedup_candidates    ─── 去重候选 (identity hash 匹配，待审核)
```

### 辅助

```
etl_run_log               ─── ETL 执行日志
v_sample_with_hierarchy   ─── 便捷视图（样本 + 系列 + 项目 三表 JOIN）
```

---

## 各表字段说明

### unified_projects (23,123 行)

| 字段 | 类型 | 说明 |
|------|------|------|
| `pk` | INTEGER PK | 自增主键 |
| `project_id` | TEXT | 原始 ID (GSE*, PRJNA*, UUID, E-MTAB*...) |
| `project_id_type` | TEXT | ID 类型 (geo_series, bioproject, cellxgene_collection...) |
| `source_database` | TEXT | 来源库 (cellxgene, ncbi, geo, ebi, ega, htan...) |
| `title` | TEXT | 项目标题 |
| `description` | TEXT | 项目描述 |
| `organism` | TEXT | 物种 (已标准化: Homo sapiens, Mus musculus...) |
| `pmid` | TEXT | PubMed ID |
| `doi` | TEXT | DOI (裸字符串，无 URL 前缀) |
| `citation_count` | INTEGER | 引用次数 |
| `publication_date` | TEXT | 发表日期 (YYYY-MM-DD) |
| `journal` | TEXT | 期刊名 |
| `contact_name/email` | TEXT | 联系人 |
| `sample_count` | INTEGER | 样本数 |
| `total_cells` | INTEGER | 总细胞数 |
| `data_availability` | TEXT | 数据可用性 (open, controlled) |
| `access_url` | TEXT | 访问链接 |
| `raw_metadata` | TEXT(JSON) | 原始元数据完整保留 |
| | | **UNIQUE(project_id, source_database)** |

### unified_series (15,968 行)

| 字段 | 类型 | 说明 |
|------|------|------|
| `pk` | INTEGER PK | 自增主键 |
| `series_id` | TEXT | 原始 ID (SRP*, dataset_id UUID, GSE*...) |
| `series_id_type` | TEXT | sra_study, cellxgene_dataset, geo_series, scea_experiment |
| `project_pk` | INTEGER FK | → unified_projects.pk |
| `assay` | TEXT | 测序技术 (10x 3' v3, Smart-seq2...) |
| `assay_ontology_term_id` | TEXT | EFO 本体 ID |
| `cell_count` | INTEGER | 细胞数 |
| `has_h5ad / has_rds` | INTEGER | 是否有 H5AD/RDS 文件 |
| `asset_h5ad_url` | TEXT | H5AD 下载链接 |
| `citation_count` | INTEGER | 引用次数 |
| `raw_metadata` | TEXT(JSON) | 原始元数据 |
| | | **UNIQUE(series_id, source_database)** |

### unified_samples (756,579 行)

| 字段 | 类型 | 说明 |
|------|------|------|
| `pk` | INTEGER PK | 自增主键 |
| `sample_id` | TEXT | 原始 ID (GSM*, SAMN*, {dataset_id}:{donor}...) |
| `sample_id_type` | TEXT | gsm, biosample, cellxgene_sample, ebi_biosample... |
| `series_pk` | INTEGER FK | → unified_series.pk |
| `project_pk` | INTEGER FK | → unified_projects.pk |
| **生物学特征** | | |
| `organism` | TEXT | 物种 (已标准化) |
| `tissue` | TEXT | 组织 |
| `tissue_ontology_term_id` | TEXT | UBERON 本体 ID |
| `tissue_general` | TEXT | 组织大类 |
| `cell_type` | TEXT | 主要细胞类型 |
| `disease` | TEXT | 疾病 |
| `disease_ontology_term_id` | TEXT | MONDO 本体 ID |
| `sex` | TEXT | 性别 (male, female, unknown, mixed) |
| `age` | TEXT | 年龄 |
| `development_stage` | TEXT | 发育阶段 |
| `ethnicity` | TEXT | 种族 |
| `individual_id` | TEXT | 供体/患者 ID |
| `biological_identity_hash` | TEXT | 生物学特征 MD5 哈希 (用于去重) |
| `n_cells` | INTEGER | 细胞数量 |
| `raw_metadata` | TEXT(JSON) | 原始元数据 |
| | | **UNIQUE(sample_id, source_database)** |

### id_mappings (1,321,292 行)

| 字段 | 说明 |
|------|------|
| `entity_type` | project, series, sample |
| `entity_pk` | 指向对应表的 pk |
| `id_type` | gsm, samn, srs, samea, ers, prjna, gse, srp, pmid, doi, e_mtab, erp... |
| `id_value` | 具体 ID 值 |
| `is_primary` | 是否为该实体的主 ID |

### entity_links (9,966 行)

| 字段 | 说明 |
|------|------|
| `source_entity_type/pk` | 源实体 |
| `target_entity_type/pk` | 目标实体 |
| `relationship_type` | same_as, linked_via_pmid, linked_via_doi |
| `confidence` | high, medium, low |
| `link_method` | 建立方式 (bioproject_xml_geo_center_id, pmid_match, doi_match) |
| `link_evidence` | 证据描述 |

---

## 数据质量

### 各源字段完整度

| 数据源 | 样本数 | tissue | disease | sex | identity_hash |
|--------|--------|--------|---------|-----|---------------|
| CellXGene | 33,984 | 100.0% | 100.0% | 100.0% | 100.0% |
| NCBI/SRA | 217,513 | 96.9% | 22.0% | 35.7% | 97.9% |
| GEO | 342,368 | 100.0% | 12.5% | 10.7% | 100.0% |
| EBI | 160,135 | 90.6% | 59.4% | 70.7% | 97.2% |
| HTAN | 942 | 96.3% | 96.3% | 99.4% | 100.0% |
| PsychAD | 1,494 | 100.0% | 100.0% | 100.0% | 100.0% |
| HCA | 143 | 0.0% | 86.0% | 93.0% | 100.0% |

### 跨库链接统计

| 链接类型 | 方向 | 数量 | 置信度 |
|---------|------|------|--------|
| PRJNA↔GSE (same_as) | NCBI→GEO | 4,142 | 高 |
| PubMed ID 共享 | NCBI→GEO | 5,756 | 高 |
| DOI 共享 | CellXGene→NCBI | 68 | 高 |
| identity hash 去重 | NCBI↔GEO | 100,000 | 低（候选） |

---

## 使用方式

### 命令行

```bash
# 查看质量报告
python run_pipeline.py --verify

# 完整重建
python run_pipeline.py --phase all

# 分阶段
python run_pipeline.py --phase phase1   # CellXGene
python run_pipeline.py --phase phase2   # NCBI + GEO + 链接 + 索引
python run_pipeline.py --phase phase3   # EBI + 小型源 + 去重 + 视图

# 单步执行
python run_pipeline.py --step cellxgene
python run_pipeline.py --step ncbi
python run_pipeline.py --step geo
python run_pipeline.py --step links
python run_pipeline.py --step indexes
python run_pipeline.py --step ebi
python run_pipeline.py --step small
python run_pipeline.py --step dedup
python run_pipeline.py --step view
```

### 常用查询示例

```sql
-- 1. 按疾病搜索项目
SELECT project_id, source_database, title, pmid, citation_count
FROM unified_projects
WHERE title LIKE '%Alzheimer%'
ORDER BY citation_count DESC NULLS LAST;

-- 2. 查看某项目的所有样本
SELECT s.sample_id, s.tissue, s.disease, s.sex, s.n_cells
FROM unified_samples s
JOIN unified_projects p ON s.project_pk = p.pk
WHERE p.project_id = 'GSE200001';

-- 3. 通过层级视图查询（自动 JOIN 项目+系列+样本）
SELECT sample_id, tissue, disease, sex, assay, project_title, citation_count
FROM v_sample_with_hierarchy
WHERE tissue = 'liver' AND disease != 'normal'
LIMIT 20;

-- 4. 查找跨库关联的项目
SELECT el.link_evidence,
       np.project_id as ncbi_id, np.title,
       gp.project_id as geo_id, gp.title
FROM entity_links el
JOIN unified_projects np ON el.source_pk = np.pk
JOIN unified_projects gp ON el.target_pk = gp.pk
WHERE el.relationship_type = 'same_as'
LIMIT 10;

-- 5. 通过 ID 跨库查找（如 BioSample → 所有关联实体）
SELECT im.entity_type, im.id_type, im.id_value
FROM id_mappings im
WHERE im.entity_pk IN (
    SELECT entity_pk FROM id_mappings
    WHERE id_type = 'samn' AND id_value = 'SAMN15000001'
);

-- 6. 统计各组织的样本数
SELECT tissue, COUNT(*) as cnt
FROM unified_samples
WHERE tissue IS NOT NULL
GROUP BY tissue
ORDER BY cnt DESC
LIMIT 20;

-- 7. 查看去重候选
SELECT dc.confidence_score,
       a.sample_id, a.source_database, a.tissue, a.disease,
       b.sample_id, b.source_database, b.tissue, b.disease
FROM dedup_candidates dc
JOIN unified_samples a ON dc.entity_a_pk = a.pk
JOIN unified_samples b ON dc.entity_b_pk = b.pk
WHERE dc.confidence_score >= 0.7
LIMIT 20;
```

### Python API 方式

```python
import sqlite3
import json

conn = sqlite3.connect('unified_metadata.db')
conn.row_factory = sqlite3.Row

# 查询某组织的所有 CellXGene 样本
rows = conn.execute("""
    SELECT sample_id, tissue, disease, sex, n_cells, raw_metadata
    FROM unified_samples
    WHERE source_database = 'cellxgene' AND tissue = 'brain'
""").fetchall()

for r in rows:
    meta = json.loads(r['raw_metadata'])
    print(f"{r['sample_id']}: {r['tissue']}, {r['disease']}, cells={r['n_cells']}")
```

---

## ETL 模块说明

| 模块 | 数据源 | 输入 | 记录数 | 耗时 |
|------|--------|------|--------|------|
| `cellxgene_etl.py` | CellXGene | 3 个 CSV | 35K | ~35s |
| `ncbi_sra_etl.py` | NCBI/SRA | 6 个 CSV | 237K | ~2min |
| `geo_etl.py` | GEO | 1 个 CSV (378K 行) | 348K | ~3.5min |
| `ebi_etl.py` | EBI | 162K 个 JSON | 163K | ~15min |
| `small_sources_etl.py` | 8 个小型源 | xlsx/tsv/csv/json | 7K | ~8s |
| `id_linker.py` | 跨库链接 | 数据库内查询 | 10K links | ~3s |
| `dedup.py` | 去重候选 | 数据库内查询 | 100K | ~28s |

### ETL 基类 (`base.py`) 提供的通用工具

- `batch_insert()` — 批量插入 + 冲突处理
- `compute_identity_hash()` — 生物学特征 MD5 哈希
- `normalize_organism()` — 物种名标准化
- `normalize_sex()` — 性别标准化
- `parse_age_from_dev_stage()` — 从发育阶段提取年龄
- `float_to_int_str()` — GEO PubMed ID 类型转换
- `clean_str()` — NaN/None/空值统一处理
- `safe_json_dumps()` — 安全 JSON 序列化
- `log_progress()` — 进度日志（每 10K 条）

---

## 已知问题与后续工作

### 数据质量待改进
- GEO Characteristics 解析率有限（disease 12.5%、sex 10.7%），需要更多候选 key 或 NLP 方法
- EBI BioSample 组织字段 (`organism part`) 未统一到标准本体
- identity hash 在缺少关键字段时可能产生假碰撞（仅 organism + tissue 相同就命中）

### 功能待扩展
- 去重候选的人工审核 / AI 审核流程
- 增量更新机制（目前为全量重建）
- 版本追踪 (version_tree) — 已设计未实现
- PostgreSQL 迁移（用于生产环境高并发）
- REST API / GraphQL 查询接口
- 与 AI Agent 的集成接口

### 技术债务
- 断点续传机制（大数据源 ETL 中断后需全量重跑）
- EBI BioSample 160K 文件 I/O 性能优化（可用多进程）
- GEO Excel→CSV 转换应在采集阶段完成
