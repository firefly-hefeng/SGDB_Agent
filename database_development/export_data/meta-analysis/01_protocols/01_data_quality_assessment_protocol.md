# 单细胞元数据库质量评估与科学复核方案书
## Single-Cell Metadata Database Quality Assessment & Scientific Validation Protocol

**版本**: v1.0  
**日期**: 2026-03-26  
**编制**: 生物信息学数据分析团队  

---

## 1. 项目背景与目标

### 1.1 项目背景
本数据库整合了来自多个国际主流单细胞数据库（CellXGene、GEO、NCBI SRA、EBI等）的元数据，涵盖23,123个项目、756,579个样本和378,029个细胞类型记录。作为多源异构数据的集成产物，数据质量和一致性是后续科学分析的基础。

### 1.2 复核目标
1. **数据完整性评估**: 识别缺失数据模式和系统偏差
2. **跨数据库一致性验证**: 检测不同数据源的标准化差异
3. **数据可信度评估**: 评估关键生物学注释的准确性
4. **数据关系验证**: 确认层级关系（project-series-sample-celltype）的正确性

### 1.3 预期产出
- 数据质量评估报告（含可视化）
- 数据问题清单与改进建议
- 各数据源的适用性评估

---

## 2. 评估维度与指标体系

### 2.1 数据完整性维度 (Data Completeness)

| 评估指标 | 计算方法 | 阈值标准 | 优先级 |
|---------|---------|---------|-------|
| 字段填充率 | 非空值比例 | ≥90%为优秀，≥70%为可接受 | 高 |
| 关键字段缺失率 | organism, tissue, cell_type等 | <5%为优秀 | 高 |
| 层级关系完整性 | 孤儿记录比例（无parent的sample/celltype） | <1%为优秀 | 高 |
| 跨库关联完整度 | entity_links覆盖率 | ≥95%为优秀 | 中 |

### 2.2 数据一致性维度 (Data Consistency)

| 评估指标 | 计算方法 | 阈值标准 | 优先级 |
|---------|---------|---------|-------|
| 词汇标准化程度 | 唯一值数量/总记录数 | 越低越好 | 高 |
| Ontology使用比例 | 有ontology_id的字段比例 | ≥80%为优秀 | 高 |
| 数值范围合理性 | 异常值检测（n_cells等） | IQR法则 | 中 |
| 跨库重复检测 | 相同生物学样本的重复比例 | 需人工判断 | 中 |

### 2.3 数据准确性维度 (Data Accuracy)

| 评估指标 | 计算方法 | 验证方式 | 优先级 |
|---------|---------|---------|-------|
| 物种名称标准化 | 与NCBI Taxonomy比对 | 自动比对 | 中 |
| 组织-细胞类型一致性 | liver样本不应出现neuron等 | 规则验证 | 中 |
| 文献信息有效性 | PMID/DOI可解析性 | 抽样验证 | 低 |
| 数据可用性标注 | access_url有效性 | 抽样验证 | 低 |

---

## 3. 复核流程设计

### 3.1 阶段一：基础统计与完整性扫描

**任务1.1: 全局数据画像**
- 各表记录数统计
- 各数据源贡献度分析
- 时间分布（publication_date）

**任务1.2: 字段级完整性分析**
```
对每个关键字段：
  - 计算填充率
  - 识别缺失模式（随机缺失/系统缺失）
  - 按数据源分层分析
  
关键字段列表：
  - 样本标识: sample_id, individual_id, biological_identity_hash
  - 生物学信息: organism, tissue, cell_type, disease
  - 个体信息: sex, age, developmental_stage, ethnicity
  - 技术信息: assay, n_cells
  - 文献信息: pmid, doi, publication_date
```

**任务1.3: 层级关系完整性验证**
```
验证规则：
  - 每个sample应有对应的series（允许部分缺失）
  - 每个celltype必须关联到有效的sample
  - project-series-sample的引用完整性
```

### 3.2 阶段二：跨数据库一致性分析

**任务2.1: 词汇标准化评估**
```
分析维度：
  - organism的标准化（Homo sapiens vs human vs H. sapiens）
  - tissue名称的变体（liver vs hepatic tissue）
  - cell_type命名规范
  - disease术语差异
```

**任务2.2: Ontology覆盖率分析**
```
评估内容：
  - 各字段的ontology ID填充率
  - ontology ID与文本值的一致性
  - 不同数据源的ontology使用情况差异
```

**任务2.3: 数值字段对比**
```
分析指标：
  - n_cells的分布差异（by source_database）
  - citation_count的数据质量问题
  - 数值范围的合理性（如age的异常值）
```

### 3.3 阶段三：数据可信度评估

**任务3.1: 重复数据检测**
```
检测策略：
  - 基于biological_identity_hash的精确重复
  - 基于sample_id的跨库重复
  - 基于(individual_id, tissue, disease)的模糊重复
```

**任务3.2: 生物学合理性检查**
```
验证规则：
  - 组织-细胞类型匹配（如brain样本不应有hepatocyte）
  - 疾病-组织关联（如liver cancer应在liver组织）
  - 物种-组织合理性
```

**任务3.3: 引用数据质量**
```
分析内容：
  - PMID/DOI的格式规范性
  - 高引论文的数据代表性
  - 未发表数据的比例
```

### 3.4 阶段四：综合质量评分

**质量评分模型：**
```
总评分 = Σ(维度得分 × 权重)

维度权重：
  - 完整性: 40%
  - 一致性: 35%
  - 准确性: 25%

数据源分级：
  - A级（优秀）: 总分 ≥ 85
  - B级（良好）: 70 ≤ 总分 < 85
  - C级（可接受）: 60 ≤ 总分 < 70
  - D级（需改进）: 总分 < 60
```

---

## 4. 可视化方案

### 4.1 完整性可视化
- 缺失值热力图（字段 × 数据源）
- 字段填充率条形图
- 层级关系完整性饼图

### 4.2 一致性可视化
- 词汇标准化程度词云/条形图
- Ontology覆盖雷达图
- 数值分布箱线图（按数据源）

### 4.3 质量评估可视化
- 数据源质量评分条形图
- 数据问题分类饼图
- 时间趋势折线图（数据增长与质量关系）

---

## 5. 实施计划

| 阶段 | 任务 | 预计时间 | 产出 |
|-----|------|---------|------|
| 阶段一 | 基础统计与完整性扫描 | 2h | 完整性报告 |
| 阶段二 | 跨数据库一致性分析 | 3h | 一致性报告 |
| 阶段三 | 数据可信度评估 | 2h | 可信度报告 |
| 阶段四 | 综合评分与可视化 | 2h | 质量评估报告 |

---

## 6. 附录

### 6.1 数据源编码
- cellxgene: CellXGene Census
- geo: NCBI GEO
- ncbi_sra: NCBI SRA
- ebi: EBI ArrayExpress
- cngb: 国家基因库
- scp: Single Cell Portal

### 6.2 关键字段定义
详见 `02_DATABASE_SCHEMA.md`

### 6.3 参考标准
- MIABIS (Minimum Information About BIobank data Sharing)
- HCA (Human Cell Atlas) metadata standards
- FAIR principles
