# 单细胞元数据库导出文件说明

## 导出时间
2026-03-25

## 数据来源
`unified_db/unified_metadata.db` (SQLite)

## 文件列表

### 合并表（用于复核）

| 文件名 | 记录数 | 大小 | 说明 |
|--------|--------|------|------|
| `00_merged_celltype_level.csv` | 378,029 | 221 MB | **最细粒度合并表**<br>celltypes JOIN samples JOIN series JOIN projects<br>每行代表一个细胞类型记录 |
| `00_merged_sample_level.csv` | 1,007,371 | 441 MB | **样本级别合并表**<br>samples JOIN series JOIN projects<br>注意：由于 LEFT JOIN，一个 sample 可能关联多个 series，导致重复行<br>唯一 sample 数: 756,579 |

### 基础表（单独导出）

| 文件名 | 记录数 | 大小 | 说明 |
|--------|--------|------|------|
| `01_projects.csv` | 23,123 | 3.8 MB | 项目级别数据 (GEO GSE/CellXGene Collection 等) |
| `02_series.csv` | 15,968 | 2.4 MB | 系列级别数据 (CellXGene Dataset 等) |
| `03_samples.csv` | 756,579 | 94 MB | 样本级别数据 (生物学样本信息) |
| `04_celltypes.csv` | 378,029 | 19 MB | 细胞类型数据 (每个样本中的细胞类型) |

## 表关系

```
projects (23K)  ←──  series (16K)  ←──  samples (757K)  ←──  celltypes (378K)
     ↑                    ↑                  ↑                  ↑
   project_pk          series_pk          sample_pk          celltype_pk
```

- **projects**: 最顶层，代表研究项目 (如 GEO GSE)
- **series**: 数据集系列 (如 CellXGene Collection)
- **samples**: 生物学样本 (如 donor1 liver tissue)
- **celltypes**: 样本中的细胞类型列表

## 合并逻辑

### 1. celltype 级别合并 (00_merged_celltype_level.csv)
```sql
SELECT * FROM unified_celltypes ct
LEFT JOIN unified_samples s ON ct.sample_pk = s.pk
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
```

用途：查看每个细胞类型对应的完整层级信息

### 2. sample 级别合并 (00_merged_sample_level.csv)
```sql
SELECT * FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
```

用途：查看每个样本的完整层级信息（不含 celltype 明细）

⚠️ **注意**: 由于一个 sample 可能关联多个 series（数据来自不同数据源），此表存在重复行。
- 总行数: 1,007,371
- 唯一 sample 数: 756,579
- 重复数: 250,792

## 复核建议

1. **数据完整性检查**
   - 检查 samples 表中是否有缺失 series_pk 或 project_pk 的记录
   - 检查 celltypes 表中是否有缺失 sample_pk 的记录

2. **数据一致性检查**
   - 对比不同来源 (source_database) 的数据格式是否一致
   - 检查 organism、tissue、disease 等字段的标准化程度

3. **重复数据检查**
   - 使用 `biological_identity_hash` 检查同一样本是否来自多个数据源
   - 检查相同 project_id 是否来自不同数据库

## 关键字段说明

### 样本识别
- `sample_id`: 原始样本ID
- `biological_identity_hash`: 生物学身份哈希（用于去重）
- `individual_id`: 个体ID (donor/patient)

### 生物学信息
- `organism`: 物种 (Homo sapiens, Mus musculus 等)
- `tissue`: 组织类型
- `cell_type`: 细胞类型
- `disease`: 疾病信息
- `sex`, `age`, `development_stage`, `ethnicity`: 个体信息

### 数据来源
- `source_database`: 数据来源 (cellxgene, geo, ncbi_sra, ebi 等)
- `assay`: 实验技术 (10x Genomics, Smart-seq2 等)
- `n_cells`: 细胞数量

### 文献信息
- `pmid`: PubMed ID
- `doi`: DOI
- `citation_count`: 引用次数
- `publication_date`: 发表日期
- `journal`: 期刊

## 导出脚本

- `export_all.py` - 导出所有基础表和 sample 级别合并表
- `export_celltype_level.py` - 导出 celltype 级别合并表

如需重新导出，运行：
```bash
cd export_data
python3 export_all.py
python3 export_celltype_level.py
```
