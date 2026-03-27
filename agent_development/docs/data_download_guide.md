# 数据下载功能使用指南

> 本文档介绍如何使用SCDB-Agent的数据下载功能，从各大单细胞数据库一键获取原始数据。

---

## 功能概述

SCDB-Agent支持从以下数据库下载原始数据：

| 数据库 | 支持格式 | 下载方式 |
|--------|---------|---------|
| **GEO** | .h5ad, .h5, .mtx, .txt.gz | FTP/HTTP直接下载 |
| **CellxGene** | .h5ad, .rds | API下载 |
| **SRA** | .fastq | sra-toolkit脚本 |
| **CNGBdb** | 多种格式 | HTTP下载 |

---

## 快速开始

### 1. 查询并预览可下载数据

```bash
# 启动交互式模式
python run.py

# 执行查询
🔍 > 查找肺癌相关的开放单细胞数据

# 预览可下载的数据
🔍 > download-preview
```

输出示例：
```
📦 数据下载预览
================================================================================
总计记录数: 50
数据库分布:
  • GEO: 35 条
  • CellxGene: 15 条

前 5 条记录预览:
[1] GSE123456 (GEO)
    标题: Lung cancer single cell RNA-seq study
    文件类型: h5ad
    访问链接: https://ftp.ncbi.nlm.nih.gov/geo/series/...

[2] SCP123 (CellxGene)
    标题: Human Lung Cell Atlas
    文件类型: h5ad
    访问链接: https://api.cellxgene.cziscience.com/...

================================================================================
提示: 使用 'download' 命令开始下载
      使用 'download-script' 命令生成批量下载脚本
```

### 2. 下载数据

```bash
# 基本下载（下载表达矩阵）
🔍 > download

# 下载包含原始数据
🔍 > download --raw

# 下载包含元数据
🔍 > download --metadata

# 指定输出目录
🔍 > download --output /path/to/save

# 同时生成下载脚本
🔍 > download --script
```

下载过程显示：
```
================================================================================
⬇️  开始数据下载
================================================================================
文件类型: matrix
记录数量: 10
输出目录: data/downloads
同时生成: 下载脚本

确认开始下载? (y/n): y

  [abc12345] 45.2% @ 2.35 MB/s
```

### 3. 生成批量下载脚本

对于大量数据的下载，建议生成脚本后台执行：

```bash
🔍 > download-script

# 或指定保存路径
🔍 > download-script /path/to/save/download.sh
```

输出示例：
```
================================================================================
📝 生成批量下载脚本
================================================================================
记录数量: 100

✅ 脚本已生成: data/downloads/download_batch_20260101_120000.sh

使用方法:
  1. 查看脚本内容: cat data/downloads/download_batch_20260101_120000.sh
  2. 执行下载: bash data/downloads/download_batch_20260101_120000.sh
  3. 后台执行: nohup bash data/downloads/download_batch_20260101_120000.sh > download.log 2>&1 &

提示:
  • 脚本支持断点续传（使用wget -c）
  • 建议先在测试环境验证脚本
  • 大量数据下载建议使用后台运行
================================================================================
```

---

## 高级用法

### 命令行模式直接下载

```bash
# 查询并导出下载列表
python run.py -q "肺癌10x数据" -o results/lung_cancer.csv

# 后续使用下载脚本处理
python -c "
from src.cli import CLI
cli = CLI()
import pandas as pd
results = pd.read_csv('results/lung_cancer.csv')
cli.query_engine.generate_download_script(results, 'downloads/lung_cancer.sh')
cli.cleanup()
"
```

### 程序化使用下载功能

```python
from src.config_manager import ConfigManager
from src.query_engine import QueryEngine

# 初始化
config = ConfigManager('config/config.yaml')
engine = QueryEngine(config)
engine.initialize()

# 执行查询
result = engine.execute_query("肺癌相关单细胞数据", limit=50)
records = result['results']

# 创建下载任务
tasks = engine.create_download_tasks(
    records,
    file_types=['matrix'],  # 或 ['matrix', 'raw', 'metadata']
    output_dir='my_downloads'
)

# 定义进度回调
def on_progress(task_id, progress, speed):
    print(f"[{task_id}] {progress:.1f}% @ {speed/1024/1024:.2f} MB/s")

# 开始下载
stats = engine.start_download(tasks, progress_callback=on_progress)
print(f"下载完成: 成功 {stats['completed']}, 失败 {stats['failed']}")

# 生成脚本
script_path = engine.generate_download_script(records, 'download.sh')
print(f"脚本已保存: {script_path}")

# 清理
engine.cleanup()
```

---

## 下载脚本示例

生成的下载脚本示例：

```bash
#!/bin/bash
# Auto-generated download script

# GEO downloads (35 tasks)
# GSE123456 - matrix
mkdir -p "data/downloads/GEO/GSE123456"
wget -c -O "data/downloads/GEO/GSE123456/sample_matrix.h5ad" \
    "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE123nnn/GSE123456/suppl/GSE123456_matrix.h5ad"

# SCP123 - matrix
mkdir -p "data/downloads/CellxGene/SCP123"
wget -c -O "data/downloads/CellxGene/SCP123/data.h5ad" \
    "https://api.cellxgene.cziscience.com/dp/v1/datasets/xxx/assets/yyy"

# SRA downloads (需要sra-toolkit)
# SRP12345
mkdir -p "data/downloads/SRA/SRP12345"
echo "请使用 sra-toolkit 下载:"
echo "  prefetch SRP12345"
echo "  fasterq-dump SRP12345 --split-files"

echo 'All downloads completed!'
```

---

## 配置文件

下载相关配置位于 `config/config.yaml`：

```yaml
download:
  # 下载目录
  download_dir: "data/downloads"
  
  # 并发下载设置
  max_concurrent_downloads: 3        # 最大并发下载数
  retry_attempts: 3                  # 失败重试次数
  
  # 下载参数
  timeout: 300                       # 单次下载超时（秒）
  chunk_size: 8192                   # 下载块大小（字节）
  
  # 安全限制
  max_single_file_size: 10737418240  # 单个文件最大10GB
  require_confirmation: true         # 下载前需要确认
  
  # 数据库特定配置
  geo:
    ftp_host: "ftp.ncbi.nlm.nih.gov"
    use_https_fallback: true
  
  cellxgene:
    api_base: "https://api.cellxgene.cziscience.com"
    
  sra:
    prefetch_path: "prefetch"        # sra-toolkit路径
    fasterq_dump_path: "fasterq-dump"
```

---

## 常见问题

### Q1: 为什么有些数据无法直接下载？

某些数据库（如SRA）需要使用专门的命令行工具（sra-toolkit）下载。系统会：
- 生成详细的下载指南
- 提供所需的命令
- 创建README文件说明步骤

### Q2: 下载速度慢怎么办？

1. **使用下载脚本后台运行**：
   ```bash
   nohup bash download_batch.sh > download.log 2>&1 &
   ```

2. **调整并发数**（修改配置文件）：
   ```yaml
   download:
     max_concurrent_downloads: 5  # 增加并发数
   ```

3. **使用断点续传**：脚本已内置 `-c` 参数，支持断点续传

### Q3: 如何只下载特定数据库的数据？

```bash
# 查询时指定数据库
🔍 > 查找来自GEO的肺癌数据

# 或在下载前筛选结果
🔍 > 查找肺癌数据
# 查看结果后，使用download命令只下载当前结果
```

### Q4: 下载的文件格式是什么？

系统自动识别并保存为原始格式：
- `.h5ad` - Anndata格式（Python scanpy）
- `.h5` - HDF5格式
- `.rds` - R数据格式（Seurat）
- `.mtx` - Matrix Market格式
- `.fastq` - 原始测序数据

---

## 安全与限制

1. **下载数量限制**：交互模式下单次最多下载10条记录，大量数据请使用脚本
2. **文件大小限制**：单个文件最大10GB，超大文件会提示手动下载
3. **确认机制**：下载前需要用户确认，避免误操作
4. **断点续传**：支持wget断点续传，网络中断后可恢复

---

## 技术支持

如遇到下载问题，请检查：
1. 网络连接是否正常
2. 目标数据库是否可访问
3. 查看日志文件：`logs/scdb_agent.log`
4. 确认磁盘空间充足

---

*文档版本: v1.0*  
*更新日期: 2026年2月*
