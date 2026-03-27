# database_development/ — 数据库开发目录

## 目录结构

```
database_development/
│
├── unified_db/                       ★ 已实现的统一数据库（核心代码）
│   ├── README.md                     ← 完整使用说明
│   ├── config.py                     │  路径配置
│   ├── schema.sql                    │  建表 DDL
│   ├── create_db.py                  │  初始化脚本
│   ├── run_pipeline.py               │  主编排器
│   ├── unified_metadata.db           │  SQLite 数据库 (1.1 GB)
│   ├── etl/                          │  ETL 模块
│   │   ├── base.py                   │    基类
│   │   ├── cellxgene_etl.py          │    CellXGene
│   │   ├── ncbi_sra_etl.py           │    NCBI/SRA
│   │   ├── geo_etl.py                │    GEO
│   │   ├── ebi_etl.py                │    EBI
│   │   └── small_sources_etl.py      │    8 个小型源
│   └── linker/                       │  关联 & 去重
│       ├── id_linker.py              │    硬链接 + 索引
│       └── dedup.py                  │    去重候选
│
├── 00_README_FOR_DEVELOPERS.md       │  早期设计参考 + 人类专家建议
├── 01_ARCHITECTURE_DESIGN.md         │  架构设计（理论文档）
├── 02_DATABASE_SCHEMA.md             │  Schema 设计（早期草案，已由 unified_db 取代）
├── 03_IMPLEMENTATION_ROADMAP.md      │  实施路线图（含已完成状态）
├── example_data_walkthrough.md       │  数据流转完整示例
│
└── 04_EXPLORATION_NOTES/             │  技术探索笔记
    ├── lessons_learned.md            │    经验教训汇总
    └── phase2_geo_framework.md       │    GEO 流处理框架探索
```

## 文档阅读顺序

1. **`unified_db/README.md`** — 已实现系统的完整说明（Schema、使用方式、查询示例）
2. `03_IMPLEMENTATION_ROADMAP.md` — 路线图与当前进度
3. `00_README_FOR_DEVELOPERS.md` — 设计背景与人类专家建议
4. `example_data_walkthrough.md` — 理解数据如何在系统中流转
5. `01_ARCHITECTURE_DESIGN.md` / `02_DATABASE_SCHEMA.md` — 早期理论设计（供参考）

## 快速开始

```bash
cd unified_db/

# 查看质量报告
python run_pipeline.py --verify

# 完整重建
python run_pipeline.py --phase all
```
