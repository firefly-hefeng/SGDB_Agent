# 改进计划与讨论

## 测试总结

经过全面的功能测试和边界探索，系统总体运行良好，但发现了若干需要改进的问题。

---

## 🔴 高优先级问题 (需要尽快修复)

### 1. 模糊查询性能问题

**现象**: 标题/摘要的LIKE查询需要3-5秒
- `title LIKE "%cancer%"` → 4.59秒
- `summary LIKE "%single cell%"` → 4.53秒

**影响**: 自然语言查询体验差

**解决方案对比**:

| 方案 | 实现难度 | 性能提升 | 维护成本 | 推荐度 |
|-----|---------|---------|---------|-------|
| A. FTS5全文索引 | 中 | 10-100x | 低 | ⭐⭐⭐⭐⭐ |
| B. 预计算缓存 | 低 | 5-10x | 中 | ⭐⭐⭐⭐ |
| C. 分词索引 | 高 | 50x | 高 | ⭐⭐⭐ |

**建议采用方案A - FTS5全文索引**:

```sql
-- 创建FTS5虚拟表
CREATE VIRTUAL TABLE std_fts USING fts5(
    title, 
    summary, 
    disease_standardized,
    tissue_standardized,
    content='std',
    content_rowid='rowid'
);

-- 插入数据
INSERT INTO std_fts(rowid, title, summary, disease_standardized, tissue_standardized)
SELECT rowid, title, summary, disease_standardized, tissue_standardized FROM std;

-- 使用FTS5查询 (性能提升10-100倍)
SELECT * FROM std_fts WHERE std_fts MATCH 'cancer';
```

**需要您的决策**:
- [ ] 是否接受添加FTS5虚拟表？（增加约500MB存储）
- [ ] 是否需要实时同步更新？

---

### 2. 标准化字段覆盖率低

**关键问题数据**:

| 字段 | 当前覆盖率 | 目标覆盖率 | 差距 |
|-----|-----------|-----------|-----|
| sex_standardized | 9.1% | >80% | -70.9% |
| sample_type_standardized | 14.0% | >80% | -66.0% |
| ethnicity_standardized | 0.6% | >50% | -49.4% |

**解决方案 - AI批量推断**:

```python
# 实现思路
class BatchStandardizer:
    """批量标准化缺失值"""
    
    def standardize_sex(self, sample_size=1000):
        """
        使用AI推断缺失的性别信息
        基于: sample_id, title, summary, tissue等信息
        """
        # 1. 从原始sex字段学习映射规则
        # 2. 从其他元信息推断（如某些组织特异性）
        # 3. 批量推断缺失值
        pass
    
    def standardize_sample_type(self):
        """
        推断样本类型
        基于: disease, tissue, title等信息
        """
        pass
```

**工作量估计**: 2-3天

**需要您的决策**:
- [ ] 是否优先实现sex_standardized的批量推断？
- [ ] 是否接受AI推断可能存在的误差（估计准确率>90%）？

---

## 🟡 中优先级问题

### 3. 日期格式不一致

**问题**: 147万条记录日期格式为 `2025/09/10` 而非标准 `2025-09-01`

**解决方案**:

```python
# 在setup_database.py中添加
import pandas as pd

def normalize_date(date_str):
    """标准化日期格式"""
    if pd.isna(date_str) or date_str == '':
        return None
    
    formats = ['%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y']
    for fmt in formats:
        try:
            return pd.to_datetime(date_str, format=fmt).strftime('%Y-%m-%d')
        except:
            continue
    return None

# 应用到数据导入
df['publication_date'] = df['publication_date'].apply(normalize_date)
```

**工作量**: 半天

---

### 4. 重复样本问题

**问题**: 125,250条重复sample_uid

**建议**:
```sql
-- 创建去重视图
CREATE VIEW std_unique AS
SELECT * FROM std
WHERE is_duplicate = 0 OR is_duplicate IS NULL;

-- 修改默认查询使用该视图
```

**工作量**: 2小时

---

## 🟢 低优先级优化

### 5. 现有测试用例更新

现有的测试用例 (`test_field_expansion.py`, `test_query_accuracy.py`) 使用的是旧字段名，需要更新：

```python
# 需要更新的字段映射
OLD_FIELDS = {
    'disease': 'disease_standardized',
    'disease_general': 'disease_category',
    'sequencing_platform': 'platform_standardized',
    'sex': 'sex_standardized',
    'source_database': 'database_standardized',
}
```

**工作量**: 半天

---

## 📋 推荐的实施顺序

### 第一周
1. **修复日期格式** (0.5天)
2. **添加去重视图** (0.5天)
3. **实现FTS5全文索引** (2天)

### 第二周
4. **AI批量推断sex_standardized** (2天)
5. **AI批量推断sample_type_standardized** (2天)

### 第三周
6. **更新测试用例** (0.5天)
7. **性能优化和测试** (1.5天)

---

## 💰 成本与收益分析

| 改进项 | 开发时间 | 存储成本 | 性能收益 | 用户体验提升 |
|-------|---------|---------|---------|-------------|
| FTS5全文索引 | 2天 | +500MB | 10-100x | ⭐⭐⭐⭐⭐ |
| 批量标准化 | 4天 | 无 | - | ⭐⭐⭐⭐ |
| 日期修复 | 0.5天 | 无 | - | ⭐⭐⭐ |
| 去重视图 | 0.5天 | 无 | - | ⭐⭐⭐ |

---

## 🤔 需要您决策的问题

1. **FTS5全文索引**
   - 是否接受增加约500MB存储空间？
   - 是否需要支持中文分词？

2. **AI批量推断**
   - 是否接受约5-10%的推断误差？
   - 是否需要在推断结果中标记置信度？

3. **优先级调整**
   - 是否有其他更紧急的需求？
   - 是否需要先完成某个特定功能？

4. **测试环境**
   - 是否有测试环境可以验证改进效果？
   - 是否需要A/B测试对比？

---

## 📎 附件

- `comprehensive_test.py` - 综合功能测试
- `test_ai_retrieval.py` - AI检索测试
- `demo_standardized_fields.py` - 标准化字段演示
- `TEST_REPORT.md` - 完整测试报告

---

**报告时间**: 2026-02-02  
**建议下次评审**: 完成高优先级修复后
