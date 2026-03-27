# CellXGene 元数据采集

## 数据来源
CZ CELLxGENE Discover（https://cellxgene.cziscience.com/）

## 目录结构
```
cellxgene/
├── cellxgene_metadata_collection/   # 采集脚本
│   ├── run_collection.py            # 主入口
│   └── src/                         # 模块（collections, datasets, samples, citations）
└── output_v2/                       # 采集输出
    ├── collections_hierarchy.csv    # 269 个 Collection（项目层）
    ├── datasets_hierarchy_final.csv # 1,086 个 Dataset（数据集层）
    └── samples_full.csv             # 33,984 个 Sample（样本层）
```

## 数据规模
- Collections: 269（对应 269 篇论文/项目）
- Datasets: 1,086（每个对应一个 H5AD 文件）
- Samples: 33,984（唯一 donor×tissue×dataset 组合）
- 总细胞数: ~1.1 亿

## 数据质量
最高质量数据源 — 核心字段零空值，所有生物学特征带本体注释（UBERON, CL, MONDO, EFO）。

## 在统一数据库中的映射
- Collection → `unified_projects` (project_id_type='cellxgene_collection')
- Dataset → `unified_series` (series_id_type='cellxgene_dataset')
- Sample → `unified_samples` (sample_id_type='cellxgene_sample', id 格式: `{dataset_id}:{sample_id}`)
- cell_type_list → `unified_celltypes`
