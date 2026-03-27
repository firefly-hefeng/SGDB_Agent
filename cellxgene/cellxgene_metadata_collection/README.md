# CellxGene Metadata Collection

CellxGene数据库完整元数据收集工具包

## 📋 项目概述

本项目用于收集 [CELLxGENE](https://cellxgene.cziscience.com/) 单细胞数据库的完整元数据，包括：

- **Collections**: 研究项目/论文级别信息
- **Datasets**: 数据集级别信息  
- **Samples**: 样本/Donor级别信息（从Census获取）
- **Citations**: 论文引用数据（从OpenAlex获取）

## 📁 项目结构

```
cellxgene_metadata_collection/
├── README.md                     # 本文件
├── requirements.txt              # Python依赖
├── run_collection.py             # 主收集程序
├── src/                          # 源代码
│   ├── __init__.py
│   ├── utils.py                  # 工具函数
│   ├── collect_collections.py    # Collections收集
│   ├── collect_datasets.py       # Datasets收集
│   ├── collect_samples.py        # Samples收集（Census）
│   ├── collect_citations.py      # 引用数据收集
│   └── merge_data.py             # 数据合并导出
├── scripts/                      # 执行脚本
│   └── run_full_collection.sh    # 完整收集脚本
├── data/                         # 数据目录
│   ├── raw/                      # 原始数据
│   ├── processed/                # 处理后数据
│   └── cache/                    # 缓存数据
├── logs/                         # 日志文件
└── docs/                         # 文档
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

或创建虚拟环境：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. 运行完整收集

```bash
# 使用Python直接运行
python run_collection.py

# 或使用bash脚本
bash scripts/run_full_collection.sh
```

### 3. 分步收集（可选）

```bash
# 仅收集Collections和Datasets（不访问Census）
python run_collection.py --skip-samples --skip-citations

# 跳过已收集的数据，只更新引用
python run_collection.py --skip-collections --skip-datasets --skip-samples

# 使用缓存数据，只重新合并导出
python run_collection.py --skip-collections --skip-datasets --skip-samples --skip-citations
```

## 📊 输出数据

收集完成后，数据保存在 `data/processed/` 目录：

| 文件 | 内容 | 行数（预估） |
|------|------|------------|
| `collections.csv` | Collections元数据 | ~270 |
| `datasets.csv` | Datasets元数据+引用 | ~1,100 |
| `samples.csv` | Samples详细数据 | ~34,000 |
| `hierarchy.json` | 完整层级结构 | - |

### 数据字段说明

#### collections.csv
- `collection_id`: 唯一标识
- `name`: 项目名称
- `doi`: 论文DOI
- `pm_journal`: 发表期刊
- `pm_published_year`: 发表年份
- `n_datasets`: 包含数据集数
- `total_cells`: 总细胞数

#### datasets.csv
- `dataset_id`: 唯一标识
- `title`: 数据集标题
- `collection_id`: 所属Collection
- `cell_count`: 细胞数
- `citation_count`: 论文引用数
- `citation_source`: 引用数据来源
- `organisms/diseases/tissues/assays`: Ontology信息
- `n_samples`: 样本数

#### samples.csv
- `sample_id`: Donor ID
- `dataset_id`: 所属Dataset
- `n_cells`: 细胞数
- `n_cell_types`: 细胞类型数
- `cell_type_list`: 细胞类型列表
- `tissue/disease/sex/development_stage`: 样本属性
- `expr_raw_sum_mean`: 平均表达量

## ⏱️ 运行时间

| 步骤 | 预估时间 | 说明 |
|------|---------|------|
| Collections | ~2 min | API查询 |
| Datasets | ~10 min | API查询 |
| Samples | ~2-4 hours | Census数据库查询 |
| Citations | ~10 min | OpenAlex API查询 |
| **总计** | **~3-5 hours** | - |

## 🔧 高级用法

### 单独运行模块

```python
from src.collect_collections import CollectionCollector
from src.collect_datasets import DatasetCollector
from src.collect_samples import SampleCollector

# 收集Collections
coll_collector = CollectionCollector()
collections = coll_collector.collect()

# 收集Datasets
ds_collector = DatasetCollector()
datasets = ds_collector.collect(collections)

# 收集Samples
sample_collector = SampleCollector()
samples_df = sample_collector.collect(datasets)
```

### 自定义输出路径

```bash
python run_collection.py --data-dir /path/to/output
```

## 📖 数据来源

- **CellxGene API**: https://api.cellxgene.cziscience.com
- **CellxGene Census**: https://cellxgene.cziscience.com/collections
- **OpenAlex API**: https://api.openalex.org (引用数据)

## ⚠️ 注意事项

1. **网络稳定性**: Census查询需要2-4小时，请确保网络稳定
2. **API限制**: OpenAlex API有速率限制，脚本已做处理
3. **内存使用**: 处理大量samples时可能需要4-8GB内存
4. **磁盘空间**: 预计需要500MB-1GB存储空间

## 📝 日志

运行日志保存在 `logs/` 目录，命名格式：`collection_YYYYMMDD_HHMMSS.log`

查看实时进度：
```bash
tail -f logs/collection_*.log
```

## 📄 许可证

MIT License

## 🙏 致谢

- [CELLxGENE](https://cellxgene.cziscience.com/) - 单细胞数据平台
- [OpenAlex](https://openalex.org/) - 开放学术图谱
- [CZ Science](https://chanzuckerberg.com/science/) - 支持CELLxGENE项目
