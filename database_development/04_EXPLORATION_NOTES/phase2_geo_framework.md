# Phase 2: GEO 数据导入探索

## 探索目标
构建支持大数据量（378K样本）的流式导入框架

## 数据情况
- **来源**: GEO (Gene Expression Omnibus)
- **规模**: 378,773 samples, 5,666 series
- **格式**: Excel (76.76MB)
- **特点**: 原始数据，需大量清洗

## 关键发现

### 1. 数据分布
```
Top 5 Series (按样本数):
- GSE146026: 10,906 samples
- GSE98887: 9,600 samples
- GSE118723: 7,584 samples
- GSE146264: 7,304 samples
- GSE115978: 7,106 samples
```

### 2. 字段复杂度
**Characteristics字段**:
```python
# 示例值（Python字典字符串）
"{'developmental_stage': 'Blastocyst', 
  'embryo_number': 'Cas9 Injected control 2', 
  'sample_type': 'Single cell'}"

# 需要ast.literal_eval解析
```

**字段映射复杂性**:
```
GEO字段 -> 标准化字段
Characteristics:age -> age_value
Characteristics:sex -> sex
Source_name -> tissue
```

### 3. 数据质量问题
| 问题 | 比例 | 处理策略 |
|------|------|----------|
| Treatment_protocol缺失 | 60% | 允许NULL |
| Growth_protocol缺失 | 55% | 允许NULL |
| Citation_count缺失 | 46% | 设为NULL |
| PubMed_ID缺失 | 12% | 重要，需关联 |

## 流式处理框架（参考）

### 核心设计
```python
class GEOExtractor:
    """GEO数据提取器 - 流式处理"""
    
    def __init__(self, file_path: str, chunksize: int = 10000):
        self.file_path = Path(file_path)
        self.chunksize = chunksize
    
    def extract_stream(self) -> Iterator[Dict[str, Any]]:
        """
        流式提取，避免内存溢出
        
        Yields:
            单条记录
        """
        # Excel分批读取
        skiprows = 0
        while True:
            chunk = pd.read_excel(
                self.file_path,
                skiprows=skiprows,
                nrows=self.chunksize
            )
            
            if len(chunk) == 0:
                break
            
            for _, row in chunk.iterrows():
                yield self._transform_record(row)
            
            skiprows += self.chunksize
            logger.info(f"Processed {skiprows} records...")
```

### Characteristics解析
```python
def _parse_characteristics(self, char_str: str) -> Dict[str, Any]:
    """解析GEO的Characteristics字段"""
    if not char_str:
        return {}
    
    try:
        # 解析Python字典字符串
        char_dict = ast.literal_eval(char_str)
        
        # 标准化键名
        return {
            k.strip().lower().replace(' ', '_'): str(v).strip()
            for k, v in char_dict.items()
            if v is not None
        }
    except (SyntaxError, ValueError):
        logger.warning(f"Failed to parse: {char_str[:100]}")
        return {}
```

### 批量写入策略
```python
def batch_import(self, batch_size: int = 5000):
    """批量导入，定期提交"""
    batch = []
    
    for record in self.extract_stream():
        processed = self.process_record(record)
        batch.append(processed)
        
        if len(batch) >= batch_size:
            self._write_batch(batch)
            batch = []
    
    # 处理剩余
    if batch:
        self._write_batch(batch)

def _write_batch(self, batch: List[Dict]):
    """批量写入数据库"""
    with get_db_session() as db:
        for record in batch:
            db.add(record)
        db.commit()
```

## 技术挑战

### 挑战1: Excel读取性能
**问题**: pandas读取76MB Excel文件极慢（>5分钟）
**解决**: 
1. 转换为CSV格式（读取时间<30秒）
2. 或使用`openpyxl`的read_only模式

### 挑战2: 数据类型推断
**问题**: pandas自动推断导致PMID变为float
**解决**:
```python
df = pd.read_excel(file, dtype={'Series_PubMed_ID': str})
```

### 挑战3: 内存管理
**问题**: 378K记录 × 35字段 ≈ 100MB内存
**解决**: 
1. 只加载必要字段
2. 及时删除已处理数据
3. 使用生成器避免全部驻留内存

## 跨库关联策略

### 通过PMID关联
```python
def link_by_pmid(self, pmid: str):
    """通过PubMed ID关联项目"""
    projects = db.query(Project).filter(Project.pmid == pmid).all()
    
    if len(projects) < 2:
        return
    
    # 选择最老的作为canonical
    canonical = min(projects, key=lambda p: p.created_at)
    
    for proj in projects:
        if proj != canonical:
            proj.canonical_project_fk = canonical.project_pk
            create_link(proj, canonical, 'same_as')
```

### 通过BioSample ID关联
```python
# 在导入时检查
existing_mapping = db.query(IdMapping).filter(
    IdMapping.id_type == 'biosample',
    IdMapping.id_value == biosample_id
).first()

if existing_mapping:
    # 找到跨库同一样本
    return existing_sample
```

## 性能预估

| 操作 | 预估时间 | 说明 |
|------|----------|------|
| 读取Excel | 5-10分钟 | 建议使用CSV |
| 处理378K记录 | 30-60分钟 | 流式处理 |
| 数据库写入 | 20-40分钟 | 批量提交 |
| **总计** | **1-2小时** | 完整导入 |

## 经验教训

### ✅ 成功
1. 流式架构有效，内存占用恒定
2. Characteristics解析策略可行
3. 批量提交大幅提升写入性能

### ⚠️ 教训
1. Excel不适合大数据，应预处理为CSV
2. 需要更 robust 的错误处理
3. 需要支持断点续传（记录处理位置）

## 未完成工作

1. 完整导入测试（仅测试了10K样本）
2. 跨库关联验证
3. 性能优化（COPY命令）
4. 增量更新机制

## 下一步建议

1. 将Excel转换为CSV预处理
2. 实现断点续传机制
3. 使用PostgreSQL COPY命令加速写入
4. 添加并行处理（多进程）
