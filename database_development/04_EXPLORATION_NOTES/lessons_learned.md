# 探索阶段经验教训总结

## 技术选型经验

### 数据库选择
**决策**: PostgreSQL vs SQLite

| 场景 | 推荐 | 原因 |
|------|------|------|
| 生产环境 | PostgreSQL | 支持并发、JSONB、分区 |
| 开发测试 | SQLite | 轻量、无需安装 |
| 大数据导入 | PostgreSQL | COPY命令、事务优化 |

**教训**: Demo阶段使用SQLite，但生产必须PostgreSQL

### ORM选择
**决策**: SQLAlchemy 2.0

**优势**:
- 类型提示支持好
- 支持PostgreSQL特有的JSONB
- 成熟的连接池管理

**坑点**:
- Date类型在SQLite和PostgreSQL中行为不同
- 需要显式处理UUID类型

## 数据清洗经验

### 日期解析
**问题**: 各数据库日期格式不统一
```
CellXGene: ISO格式
GEO: 2017/09/21 或 Sep 21 2017
SRA: ISO格式
```

**解决**:
```python
def parse_date(date_str):
    formats = [
        '%Y/%m/%d',
        '%Y-%m-%d', 
        '%b %d %Y',
        '%d %b %Y'
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None
```

### 文本编码
**问题**: 特殊字符导致编码错误
**解决**: 统一使用UTF-8，处理时添加errors='ignore'

### 空值处理
**策略**:
- 必填字段: organism, project_id → 验证失败拒绝
- 可选字段: tissue, disease → 允许NULL
- 推荐字段: pmid, doi → 警告但允许

## 性能优化经验

### 批量写入
**Before**: 逐条INSERT + COMMIT
```python
for record in records:
    db.add(record)
    db.commit()  # 每条都提交，极慢
```

**After**: 批量INSERT
```python
batch = []
for record in records:
    batch.append(record)
    if len(batch) >= 1000:
        db.bulk_save_objects(batch)
        db.commit()
        batch = []
```

**效果**: 速度提升10-100倍

### 索引策略
**创建时机**:
1. 先导入数据（无索引更快）
2. 再创建索引

**关键索引**:
```sql
-- 去重查询
CREATE INDEX idx_samples_identity_hash ON samples(biological_identity_hash);

-- 搜索查询
CREATE INDEX idx_samples_organism_tissue ON samples(organism, tissue);

-- 关联查询
CREATE INDEX idx_datasets_sample_fk ON datasets(sample_fk);
```

## 架构设计经验



### 版本追踪设计
**考虑过**:
1. 简单版本号: v1, v2, v3
   - 问题: 无法表达分支（同一原始数据多个处理流程）

2. 时间戳排序
   - 问题: 时间不准确，且无法表达派生关系

**目前**: 版本链设计
- root_dataset_fk: 追溯源头
- version_path[]: 完整路径
- 支持分支和合并

## 开发工具经验

### 日志记录
**推荐配置**:
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('import.log'),
        logging.StreamHandler()
    ]
)
```

### 进度显示
**tqdm**: 适合已知总量
```python
from tqdm import tqdm
for record in tqdm(records, total=total):
    process(record)
```

**手动日志**: 适合流式处理
```python
if processed % 10000 == 0:
    logger.info(f"Processed {processed}/{estimated}")
```

### 调试技巧
1. 使用`pdb.set_trace()`在异常处断点
2. 保存失败记录到单独文件分析
3. 使用采样（sample 1%数据）快速验证逻辑

## 常见错误

### 错误1: 内存溢出
**现象**: 处理大数据时进程被杀
**原因**: 一次性加载所有数据到内存
**解决**: 使用生成器/迭代器

### 错误2: 数据库锁定
**现象**: SQLite database is locked
**原因**: 多线程写入冲突
**解决**: 
- 单线程写入
- 或使用PostgreSQL

### 错误3: 外键约束失败
**现象**: 插入dataset时失败，找不到sample
**原因**: 插入顺序错误，或事务未提交
**解决**: 
```python
# 确保先插入parent，再插入child
db.add(sample)
db.flush()  # 获取主键
dataset.sample_fk = sample.sample_pk
db.add(dataset)
db.commit()
```

## 团队协作建议

### 代码规范
1. 使用类型提示
2. 写清晰的docstring
3. 添加单元测试

### 数据管理
1. 原始数据只读，不修改
2. 中间结果保存到临时表
3. 重要操作添加审计日志

### 文档维护
1. 架构决策记录(ADR)
2. API变更日志
3. 数据字典维护

## 下一步技术债务

### 高优先级
1. 实现断点续传机制
2. 添加数据质量检查
3. 优化大数据导入性能

### 中优先级
1. 完善错误处理和恢复
2. 添加监控和报警
3. 优化查询性能

### 低优先级
1. 支持更多数据源
2. 添加可视化界面
3. 机器学习增强去重
