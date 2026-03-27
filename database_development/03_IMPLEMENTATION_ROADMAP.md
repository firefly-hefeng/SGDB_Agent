# 单细胞元数据库实施路线图

## 已完成阶段

```
Phase 1 : 基础设施 + CellXGene 导入                          ✅ 已完成
    │
    ├── ✅ SQLite 数据库环境搭建 (schema.sql, create_db.py)
    ├── ✅ 4 层核心表创建 (projects, series, samples, celltypes)
    ├── ✅ 3 关系表创建 (entity_links, id_mappings, dedup_candidates)
    ├── ✅ BaseETL 框架 (batch_insert, identity_hash, normalization)
    └── ✅ CellXGene 数据导入 (269 projects, 1086 series, 33984 samples, 378K celltypes)

Phase 2 : NCBI/SRA + GEO 整合 + 跨库关联                    ✅ 已完成
    │
    ├── ✅ NCBI BioProject → projects (10,828)
    ├── ✅ NCBI SRA Studies → series (8,833)
    ├── ✅ NCBI BioSamples → samples (217,513)
    ├── ✅ GEO Series/Samples → projects + series + samples (5,666 + 342,368)
    ├── ✅ GEO Characteristics 自由文本解析器
    ├── ✅ BioProject XML 解析提取 GSE 交叉引用 (8,528 条)
    ├── ✅ 硬链接构建: PRJNA↔GSE (4,142), PMID (5,756), DOI (68)
    └── ✅ 索引创建 (26 个索引)

Phase 3 : EBI + 小型数据源 + 去重                            ✅ 已完成
    │
    ├── ✅ EBI BioStudies → projects (2,005)
    ├── ✅ EBI SCEA → series (383)
    ├── ✅ EBI BioSamples → samples (160,135)
    ├── ✅ 8 个小型数据源导入 (HCA, HTAN, EGA, PsychAD, BISCP, KPMP, Zenodo, Figshare)
    ├── ✅ 去重候选生成 (identity hash 跨库匹配, 100K 候选)
    ├── ✅ 统一视图创建 (v_sample_with_hierarchy)
    └── ✅ 质量验证报告
```

## 最终数据规模

```
unified_projects    :  23,123 条 (12 个数据源)
unified_series      :  15,968 条
unified_samples     : 756,579 条
unified_celltypes   : 378,029 条
id_mappings         : 1,321,292 条
entity_links        :   9,966 条
dedup_candidates    : 100,000 条
数据库大小          :   1.1 GB
```

## 后续规划

```
Phase 4 : 去重审核 + 数据质量提升                            ⬜ 待实施
    │
    ├── 去重候选人工 / AI 审核流程
    ├── GEO Characteristics 解析增强 (NLP / LLM)
    ├── 本体术语标准化 (UBERON, CL, MONDO 映射)
    └── 增量更新机制

Phase 5 : 生产化 + API 开发                                  ⬜ 待实施
    │
    ├── PostgreSQL 迁移
    ├── REST API / GraphQL 接口
    ├── 版本追踪 (version_tree) 实现
    └── AI Agent 集成接口
```

---

## 代码位置

所有已实现的代码位于 `database_development/unified_db/`，详见 [`unified_db/README.md`](unified_db/README.md)。
