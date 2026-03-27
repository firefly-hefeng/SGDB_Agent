# CellxGene元数据收集 - 使用说明

## 一键运行

```bash
cd cellxgene_metadata_collection
bash scripts/run_full_collection.sh
```

## 分步运行

### 1. 安装依赖
```bash
pip install pandas requests cellxgene-census
```

### 2. 完整收集
```bash
python run_collection.py
```

### 3. 仅收集元数据（不访问Census）
```bash
python run_collection.py --skip-samples --skip-citations
```

### 4. 仅更新引用数据
```bash
python run_collection.py --skip-collections --skip-datasets --skip-samples
```

## 输出文件

收集完成后在 `data/processed/` 目录：

```
data/processed/
├── collections.csv      # 269 collections
├── datasets.csv         # 1,086 datasets (with citations)
├── samples.csv          # 34,000 samples
└── hierarchy.json       # 完整层级结构
```

## 数据字段

### 核心字段
- `collection_id/dataset_id/sample_id`: 唯一标识
- `citation_count`: 论文引用数（DOI精确匹配）
- `n_cells`: 细胞数
- `cell_type_list`: 细胞类型

### 引用数据来源
- `openalex_doi`: 实时API查询
- `doi_cached`: 缓存数据
- `no_doi_available`: 无DOI（未发表）

## 常见问题

**Q: 收集需要多长时间？**
A: 约3-5小时，其中Census查询占主要时间。

**Q: 如何只更新引用数据？**
A: 使用 `--skip-collections --skip-datasets --skip-samples` 参数。

**Q: 可以中断后继续吗？**
A: 可以，使用 `--skip-xxx` 参数跳过已完成的步骤。

**Q: 引用数据准确吗？**
A: 100%通过DOI精确匹配OpenAlex API，无标题搜索误差。
