# Single Cell Portal Metadata Collection

人源单细胞 RNA-seq 元数据收集项目 - 从 Broad Institute Single Cell Portal 收集的公开研究数据。

## 📋 项目概览

- **数据来源**: Broad Institute Single Cell Portal
- **API 地址**: https://singlecell.broadinstitute.org/single_cell/api/v1
- **收集时间**: 2026-02-26
- **研究数量**: 576 个人源研究
- **细胞总数**: 41,679,609

## 📁 目录结构

```
single_cell_portal_collected/
├── src/                    # 源代码
│   └── collector.py        # 主收集器
├── data/                   # 数据
│   ├── processed/          # 处理后数据
│   │   ├── human_studies_*.json
│   │   └── human_studies_*.csv
│   └── archive/            # 数据备份
├── docs/                   # 文档
│   └── schema.md           # 数据模式说明
├── logs/                   # 日志
├── scripts/                # 辅助脚本
│   └── run.sh              # 运行脚本
├── requirements.txt        # 依赖列表
└── README.md               # 本文档
```

## 📊 数据统计

| 指标 | 数值 |
|------|------|
| 总研究数 | 968 |
| 人源研究 | 576 (59.5%) |
| 含文件信息 | 365 (63.4%) |
| 含完整描述 | 367 (63.7%) |
| 含出版物 | 62 (10.8%) |
| 文件总数 | 3,916 |
| 细胞总数 | 41,679,609 |

## 📖 数据字段

### Study 级别字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `accession` | string | 研究唯一标识符 (SCPxxx) |
| `name` | string | 研究名称 |
| `description` | string | 简短描述 |
| `full_description` | string | 完整 HTML 描述 |
| `public` | boolean | 是否公开 |
| `detached` | boolean | 分离状态 |
| `species` | string | 物种学名 |
| `species_common` | string | 物种常用名 |
| `cell_count` | integer | 细胞数量 |
| `gene_count` | integer | 基因数量 |
| `study_files` | array | 文件列表 |
| `directory_listings` | array | 目录列表 |
| `external_resources` | array | 外部资源链接 |
| `publications` | array | 出版物列表 |

### Study File 字段

| 字段 | 说明 |
|------|------|
| `name` | 文件名 |
| `file_type` | 文件类型 (Expression Matrix, Metadata, etc.) |
| `description` | 文件描述 |
| `bucket_location` | 存储位置 |
| `upload_file_size` | 文件大小 (bytes) |
| `download_url` | 下载链接 |
| `media_url` | 媒体链接 |

### Publication 字段

| 字段 | 说明 |
|------|------|
| `title` | 标题 |
| `journal` | 期刊 |
| `url` | 文章链接 |
| `pmcid` | PubMed Central ID |
| `pmid` | PubMed ID |
| `doi` | DOI |
| `citation` | 引用格式 |
| `preprint` | 是否预印本 |

## 🚀 使用

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行收集器

```bash
# 前台运行
python src/collector.py

# 后台运行
./scripts/run.sh daemon

# 查看状态
./scripts/run.sh status
```

### 查看数据

```python
import json

# 加载 JSON 数据
with open('data/processed/human_studies_v2_20260226_171029.json') as f:
    data = json.load(f)

print(f"Total studies: {len(data['studies'])}")

# 查看第一个研究
study = data['studies'][0]
print(f"Accession: {study['accession']}")
print(f"Name: {study['name']}")
print(f"Files: {len(study['study_files'])}")
```

## 📚 数据示例

```json
{
  "accession": "SCP10",
  "name": "Glioblastoma intra-tumor heterogeneity",
  "description": "Single-cell RNA-seq highlights intratumoral heterogeneity...",
  "species": "Homo sapiens",
  "cell_count": 430,
  "gene_count": 5948,
  "study_files": [
    {
      "name": "Glioblastoma_expressed_genes.txt",
      "file_type": "Expression Matrix",
      "upload_file_size": 19845324,
      "download_url": "https://singlecell.broadinstitute.org/..."
    }
  ],
  "publications": [
    {
      "title": "Single-cell RNA-seq highlights intratumoral heterogeneity...",
      "journal": "Science",
      "url": "https://doi.org/10.1126/science.1254257"
    }
  ]
}
```

## 🔍 特性

- ✅ 异步并发请求
- ✅ 自动错误重试（指数退避）
- ✅ 断点续传
- ✅ 人源自动筛选
- ✅ 完整字段收集（含文件下载链接）
- ✅ JSON + CSV 双格式输出

## 📄 许可证

数据来源于 Broad Institute Single Cell Portal 公开接口，遵循其使用条款。

## 🙏 致谢

- Broad Institute Single Cell Portal
- 所有贡献数据的研究者
