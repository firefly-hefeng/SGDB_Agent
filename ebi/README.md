# ArrayExpress Human scRNA-seq Raw Data Collector

从 EBI 公共数据源收集原始元数据。

## 文件说明

| 文件 | 说明 |
|------|------|
| `ebi_collector.py` | 主采集程序 |
| `tqdm.py` | 进度条模块（本地替代） |
| `start_collector.sh` | 启动采集器（后台运行） |
| `stop_collector.sh` | 停止采集器 |
| `check_status.sh` | 查看运行状态和数据进度 |
| `view_logs.sh` | 实时查看日志 |

## 使用方法

### 1. 启动采集器（后台运行，不受终端影响）
```bash
./start_collector.sh
```

### 2. 查看运行状态
```bash
./check_status.sh
```

### 3. 实时查看日志
```bash
./view_logs.sh
```
- 按 `Ctrl+C` 退出日志查看（不会停止采集器）

### 4. 停止采集器
```bash
./stop_collector.sh
```

## 输出目录结构

```
collected_data/
├── raw_biostudies/          # BioStudies 原始数据
│   └── {accession}.json
├── raw_ena/                 # ENA 原始数据
│   └── {accession}.json
├── raw_biosamples/          # BioSamples 原始数据
│   └── {accession}.json
├── raw_scea.json            # SCEA 目录
├── collected_accessions.json # 主访问号列表
├── progress.json            # 断点续传检查点
└── collector.log            # 运行日志
```

## 特性

- ✅ 后台运行（使用 `nohup`），关闭终端不影响
- ✅ 支持断点续传（通过 `progress.json`）
- ✅ 实时日志记录
- ✅ 自动重试机制（网络错误时）
- ✅ 并发下载（BioSamples 阶段）
