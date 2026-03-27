# 单细胞元数据库 - 完整架构设计文档

## 1. 系统架构总览

### 1.1 架构设计原则

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           设计原则                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. 分层架构: 存储层 → 处理层 → 服务层 → 应用层（将在后续集成ai系统，目前主要任务是设计合理的端口和服务）                              │
│ 2. 可扩展性: 插件式数据源接入，支持横向扩展                                  │
│ 3. 数据一致性: 事件溯源 + CQRS模式                                          │
│ 4. 高性能: 读写分离 + 缓存 + 索引优化                                       │
│ 5. 容错性: 幂等处理 + 重试机制 + 死信队列                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              应用层 (Application)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Web UI     │  │   REST API   │  │ GraphQL API  │  │   Admin      │    │
│  │  (React/Vue) │  │   (FastAPI)  │  │   (可选)     │  │   Panel      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              服务层 (Service)                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      API Gateway (Kong/Nginx)                        │   │
│  │  - 认证授权  - 限流熔断  - 请求路由  - 日志记录                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │Query Service│  │Import Service│  │Search Service│  │Stats Service│       │
│  │  (查询服务)  │  │ (导入服务)  │  │  (搜索服务)  │  │ (统计服务)  │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              处理层 (Processing)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Message Queue (RabbitMQ/Kafka)                   │   │
│  │  - 数据导入队列  - 处理任务队列  - 通知队列                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ ETL Worker  │  │Link Worker  │  │Index Worker │  │Notify Worker│       │
│  │ (ETL工作器)  │  │(关联工作器) │  │(索引工作器) │  │(通知工作器) │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              存储层 (Storage)                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   PostgreSQL    │  │ Elasticsearch   │  │     Redis       │             │
│  │   (主数据库)     │  │   (搜索引擎)    │  │    (缓存)       │             │
│  │  - 结构化数据   │  │  - 全文搜索    │  │  - 会话缓存    │             │
│  │  - 关系数据     │  │  - 聚合分析    │  │  - 热点数据    │             │
│  │  - 事务支持     │  │  - 日志分析    │  │  - 队列缓存    │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│  ┌─────────────────┐  ┌─────────────────┐                                  │
│  │   MinIO/S3      │  │   ClickHouse    │                                  │
│  │   (对象存储)    │  │   (分析数据库)  │                                  │
│  │  - 原始数据文件 │  │  - 大规模统计  │                                  │
│  │  - 备份归档     │  │  - 时序分析    │                                  │
│  └─────────────────┘  └─────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据源层 (Data Sources)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │CellXGene │  │   GEO    │  │   SRA    │  │   EBI    │  │   HCA    │     │
│  │(标准化)  │  │(原始数据)│  │(测序数据)│  │(欧洲库)  │  │(Atlas)   │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │  HTAN    │  │  SCP     │  │  CNGB    │  │  Zenodo  │                     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. 数据流程设计

### 2.1 ETL流程架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          数据导入流程 (ETL Pipeline)                         │
└─────────────────────────────────────────────────────────────────────────────┘

Phase 1: Extract (数据提取)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Data Source                                                                │
│       │                                                                     │
│       ├──► [Adapter Layer] ──► [Data Validator] ──► Raw Data Queue        │
│              │                    │                                         │
│              │                    └──► Validation Error Log                │
│              │                                                              │
│       Source Adapters (可扩展):                                             │
│       - CellXGeneAdapter                                                    │
│       - GEOAdapter                                                          │
│       - SRAAdapter                                                          │
│       - CustomAdapter (用户自定义)                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 2: Transform (数据转换)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Raw Data Queue                                                             │
│       │                                                                     │
│       ├──► [Schema Mapper] ──► [Data Normalizer] ──► [Deduplication]      │
│              │                      │                      │               │
│              │                      │                      └──► Identity   │
│              │                      │                           Hash Gen   │
│              │                      │                                      │
│              │                      └──► Ontology Mapper                   │
│              │                             - UBERON (组织)                 │
│              │                             - CL (细胞类型)                 │
│              │                             - MONDO (疾病)                  │
│              │                             - EFO (实验)                    │
│              │                                                              │
│              └──► Cross-Reference Resolver                                  │
│                    - PMID匹配                                               │
│                    - DOI匹配                                                │
│                    - 特征匹配                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 3: Load (数据加载)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Transformed Data                                                           │
│       │                                                                     │
│       ├──► [Batch Processor] ──► [Conflict Resolver] ──► [DB Writer]      │
│              │                        │                      │             │
│              │                        └──► Merge Strategy    │             │
│              │                             - Insert New      │             │
│              │                             - Update Exist    │             │
│              │                             - Create Version  │             │
│              │                                                              │
│              └──► Event Store (CDC - Change Data Capture)                  │
│                    - Import Events                                          │
│                    - Merge Events                                           │
│                    - Error Events                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
Phase 4: Post-Processing (后处理)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Database                                                                   │
│       │                                                                     │
│       ├──► [Index Builder] ──► [Search Index] (Elasticsearch)             │
│       │                                                                     │
│       ├──► [Cache Warmer] ──► [Redis Cache]                               │
│       │                                                                     │
│       └──► [Stats Aggregator] ──► [ClickHouse/Materialized View]          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据去重流程详解

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          智能去重流程 (Deduplication Flow)                   │
└─────────────────────────────────────────────────────────────────────────────┘

输入: New Sample Data
       │
       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 1: ID-based Lookup (基于ID的查找)                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Extract External IDs from new data:                                │   │
│  │    - biosample (SAMNxxxx)                                           │   │
│  │    - gsm (GSMxxxx)                                                  │   │
│  │    - samea (SAMEAxxxx)                                              │   │
│  │    - geo_series (GSExxxx)                                           │   │
│  │                                                                     │   │
│  │  Query: SELECT entity_pk FROM id_mappings                           │   │
│  │          WHERE id_type = ? AND id_value = ?                         │   │
│  │                                                                     │   │
│  │  Result: Found? ──► YES ──► Return Existing Sample (高置信度)       │   │
│  │                    NO  ──► Continue to Step 2                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ NO
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 2: Identity Hash Lookup (身份哈希查找)                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Generate Identity Hash:                                            │   │
│  │    hash_input = f"{organism}:{tissue}:{individual_id}:             │   │
│  │                   {disease}:{dev_stage}"                            │   │
│  │    identity_hash = MD5(hash_input.lower())                          │   │
│  │                                                                     │   │
│  │  Query: SELECT * FROM samples                                       │   │
│  │          WHERE biological_identity_hash = ?                         │   │
│  │                                                                     │   │
│  │  Result: Found? ──► YES ──► Return Existing Sample (中置信度)       │   │
│  │                    NO  ──► Continue to Step 3                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ NO
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 3: Similarity Matching (相似度匹配)                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Calculate similarity with existing samples:                        │   │
│  │                                                                     │   │
│  │  Candidate Selection (缩小候选范围):                                │   │
│  │    WHERE organism = ? AND tissue LIKE ? AND disease LIKE ?          │   │
│  │                                                                     │   │
│  │  Similarity Algorithm:                                              │   │
│  │    - tissue_match:        30%                                       │   │
│  │    - individual_id_match: 40% (权重最高)                            │   │
│  │    - disease_match:       20%                                       │   │
│  │    - age_match:           10%                                       │   │
│  │                                                                     │   │
│  │  Result: score > 0.9? ──► YES ──► Return Potential Match (低置信度) │   │
│  │                      NO  ──► Create New Sample                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Step 4: Merge Strategy (合并策略)                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  IF existing_sample.source_database == new_sample.source_database:  │   │
│  │     # 同库数据                                                       │   │
│  │     - Increment version_count                                       │   │
│  │     - Update has_multiple_versions = true                           │   │
│  │     - Create new dataset record                                     │   │
│  │                                                                     │   │
│  │  ELSE:                                                              │   │
│  │     # 跨库数据                                                       │   │
│  │     - Increment data_source_count                                   │   │
│  │     - Create cross-reference link                                   │   │
│  │     - Merge metadata (保留更丰富的字段)                              │   │
│  │                                                                     │   │
│  │  Create ID Mapping record for new external IDs                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3. 核心Schema设计

### 3.1 实体关系图 (ER Diagram)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          核心实体关系图                                       │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                                    samples                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PK │ sample_pk              │ UUID    │                             │   │
│  │ UQ │ biological_identity_hash│ STRING │                             │   │
│  │    │ organism                │ STRING │ ◄──────┐                    │   │
│  │    │ tissue                  │ STRING │        │                    │   │
│  │    │ cell_type               │ STRING │        │                    │   │
│  │    │ disease                 │ STRING │        │                    │   │
│  │    │ individual_id           │ STRING │        │                    │   │
│  │    │ sex                     │ STRING │        │                    │   │
│  │    │ age_value               │ STRING │        │                    │   │
│  │    │ developmental_stage     │ STRING │        │                    │   │
│  │    │ ethnicity               │ STRING │        │                    │   │
│  │    │ has_multiple_versions   │ BOOL   │        │                    │   │
│  │    │ version_count           │ INT    │        │                    │   │
│  │    │ total_cell_count        │ BIGINT │        │                    │   │
│  │    │ data_source_count       │ INT    │        │                    │   │
│  │    │ source_database         │ STRING │        │                    │   │
│  │    │ raw_metadata            │ JSONB  │        │                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      │ 1:N                                   │
│                                      ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                           datasets                                   │   │
│  │ PK │ dataset_pk              │ UUID    │                             │   │
│  │ FK │ sample_fk               │ UUID    │ ───────┐                    │   │
│  │ FK │ project_fk              │ UUID    │        │                    │   │
│  │    │ dataset_id              │ STRING  │        │                    │   │
│  │    │ dataset_type            │ STRING  │ ◄──────┤                    │   │
│  │    │ dataset_version         │ STRING  │        │                    │   │
│  │    │ root_dataset_fk         │ UUID    │ ───────┤                    │   │
│  │    │ parent_dataset_fk       │ UUID    │        │                    │   │
│  │    │ version_depth           │ INT     │        │                    │   │
│  │    │ version_path            │ UUID[]  │        │                    │   │
│  │    │ assay                   │ STRING  │        │                    │   │
│  │    │ cell_count              │ INT     │        │                    │   │
│  │    │ quality_score           │ FLOAT   │        │                    │   │
│  │    │ files                   │ JSONB   │        │                    │   │
│  │    │ source_database         │ STRING  │        │                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      │ N:1                                   │
│                                      ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                           projects                                   │   │
│  │ PK │ project_pk              │ UUID    │                             │   │
│  │    │ project_id              │ STRING  │                             │   │
│  │    │ title                   │ TEXT    │                             │   │
│  │    │ pmid                    │ STRING  │                             │   │
│  │    │ doi                     │ STRING  │                             │   │
│  │    │ citation_count          │ INT     │                             │   │
│  │    │ canonical_project_fk    │ UUID    │ ───────► projects.self    │   │
│  │    │ source_database         │ STRING  │                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
└──────────────────────────────────────┼───────────────────────────────────────┘
                                       │
                                       │ N:M (通过entity_links)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          entity_links (关联表)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PK │ link_pk                │ UUID    │                             │   │
│  │    │ source_type             │ STRING  │ ───────┐                    │   │
│  │    │ source_pk               │ UUID    │        │                    │   │
│  │    │ target_type             │ STRING  │ ───────┤                    │   │
│  │    │ target_pk               │ UUID    │        │                    │   │
│  │    │ relationship_type       │ STRING  │ ───────┤                    │   │
│  │    │ relationship_confidence │ STRING  │        │                    │   │
│  │         - belongs_to         │         │        │                    │   │
│  │         - has_dataset        │         │        │                    │   │
│  │         - has_experiment     │         │        │                    │   │
│  │         - derived_from       │         │        │                    │   │
│  │         - version_of         │         │        │                    │   │
│  │         - same_as            │         │ ◄──────┘                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ 1:N
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          id_mappings (ID映射表)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ PK │ mapping_pk             │ UUID    │                             │   │
│  │    │ entity_type             │ STRING  │                             │   │
│  │    │ entity_pk               │ UUID    │                             │   │
│  │    │ id_type                 │ STRING  │                             │   │
│  │         - biosample          │         │                             │   │
│  │         - gsm                │         │                             │   │
│  │         - samea              │         │                             │   │
│  │         - geo_series         │         │                             │   │
│  │         - pmid               │         │                             │   │
│  │         - doi                │         │                             │   │
│  │    │ id_value                │ STRING  │                             │   │
│  │    │ is_canonical            │ BOOL    │                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 版本追踪设计

```
版本链示例:

原始测序数据 (raw)
    │
    ├──► 作者处理版本 (author_processed)
    │       ├── CellRanger输出
    │       └── Seurat对象
    │
    └──► 数据库重处理版本 (db_processed)
            ├── CellXGene标准化版本
            ├── 质量提升
            └── 统一注释

数据库表示:

┌─────────────────────────────────────────────────────────────────────────────┐
│ dataset_pk │ type                │ root │ parent │ depth │ path            │
├─────────────────────────────────────────────────────────────────────────────┤
│ uuid-1     │ raw                 │ 1    │ null   │ 0     │ [1]             │
│ uuid-2     │ author_processed    │ 1    │ 1      │ 1     │ [1,2]           │
│ uuid-3     │ db_processed        │ 1    │ 2      │ 2     │ [1,2,3]         │
└─────────────────────────────────────────────────────────────────────────────┘

查询版本链:
WITH RECURSIVE version_tree AS (
    SELECT * FROM datasets WHERE dataset_pk = root_id
    UNION ALL
    SELECT d.* FROM datasets d
    JOIN version_tree vt ON d.parent_dataset_fk = vt.dataset_pk
)
SELECT * FROM version_tree ORDER BY version_depth;
```

## 4. 可扩展性设计

### 4.1 数据源适配器架构

```python
# 插件式数据源架构
from abc import ABC, abstractmethod
from typing import Iterator, Dict, Any

class BaseDataSourceAdapter(ABC):
    """
    数据源适配器基类
    
    所有新的数据源必须继承此类并实现抽象方法
    """
    
    # 数据源标识
    source_name: str = "base"
    source_version: str = "1.0"
    
    # 支持的ID类型
    supported_id_types: List[str] = []
    
    @abstractmethod
    def extract(self, **kwargs) -> Iterator[Dict[str, Any]]:
        """
        提取数据
        
        Yields:
            标准化格式的原始数据记录
        """
        pass
    
    @abstractmethod
    def transform(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        转换为统一Schema格式
        
        Returns:
            {
                'sample': {...},
                'project': {...},
                'dataset': {...},
                'experiment': {...},
                'external_ids': {...}
            }
        """
        pass
    
    @abstractmethod
    def validate(self, record: Dict[str, Any]) -> bool:
        """
        验证记录有效性
        
        Returns:
            True if valid, False otherwise
        """
        pass


# 示例: CellXGene适配器
class CellXGeneAdapter(BaseDataSourceAdapter):
    source_name = "cellxgene"
    source_version = "2.0"
    supported_id_types = ["cellxgene_dataset", "cellxgene_collection"]
    
    def __init__(self, data_dir: str, chunk_size: int = 1000):
        self.data_dir = Path(data_dir)
        self.chunk_size = chunk_size
    
    def extract(self, **kwargs) -> Iterator[Dict[str, Any]]:
        # 实现数据提取逻辑
        pass
    
    def transform(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        # 实现数据转换逻辑
        pass


# 适配器注册表
class AdapterRegistry:
    """数据源适配器注册中心"""
    
    _adapters: Dict[str, Type[BaseDataSourceAdapter]] = {}
    
    @classmethod
    def register(cls, adapter_class: Type[BaseDataSourceAdapter]):
        cls._adapters[adapter_class.source_name] = adapter_class
    
    @classmethod
    def get(cls, source_name: str) -> Type[BaseDataSourceAdapter]:
        return cls._adapters.get(source_name)
    
    @classmethod
    def list_adapters(cls) -> List[str]:
        return list(cls._adapters.keys())


# 使用示例
AdapterRegistry.register(CellXGeneAdapter)
AdapterRegistry.register(GEOAdapter)
AdapterRegistry.register(SRAAdapter)

# 动态加载
adapter_class = AdapterRegistry.get("cellxgene")
adapter = adapter_class(data_dir="/path/to/data")
```

### 4.2 处理管道架构

```python
# 可配置的处理管道
from typing import List, Callable, Any
import logging

class ProcessingPipeline:
    """
    可配置的数据处理管道
    
    支持插件式的处理步骤，便于扩展
    """
    
    def __init__(self, name: str):
        self.name = name
        self.steps: List[Callable[[Any], Any]] = []
        self.error_handlers: List[Callable[[Exception, Any], None]] = []
        self.logger = logging.getLogger(f"pipeline.{name}")
    
    def add_step(self, step: Callable[[Any], Any], name: str = None):
        """添加处理步骤"""
        step.name = name or step.__name__
        self.steps.append(step)
        return self
    
    def add_error_handler(self, handler: Callable[[Exception, Any], None]):
        """添加错误处理器"""
        self.error_handlers.append(handler)
        return self
    
    def execute(self, data: Any) -> Any:
        """执行管道"""
        context = {"pipeline": self.name, "start_time": time.time()}
        
        for step in self.steps:
            try:
                self.logger.debug(f"Executing step: {step.name}")
                data = step(data)
            except Exception as e:
                self.logger.error(f"Error in step {step.name}: {e}")
                for handler in self.error_handlers:
                    handler(e, data)
                raise ProcessingError(f"Step {step.name} failed: {e}") from e
        
        context["duration"] = time.time() - context["start_time"]
        self.logger.info(f"Pipeline completed in {context['duration']:.2f}s")
        
        return data


# 预定义的处理步骤
class StandardizationSteps:
    """标准化处理步骤库"""
    
    @staticmethod
    def normalize_ontology(record: Dict) -> Dict:
        """标准化本体术语"""
        # 实现本体映射
        pass
    
    @staticmethod
    def generate_identity_hash(record: Dict) -> Dict:
        """生成身份哈希"""
        # 实现哈希生成
        pass
    
    @staticmethod
    def validate_required_fields(record: Dict) -> Dict:
        """验证必填字段"""
        # 实现验证逻辑
        pass


# 构建管道
pipeline = ProcessingPipeline("cellxgene_import")
pipeline.add_step(StandardizationSteps.normalize_ontology, "normalize_ontology")
pipeline.add_step(StandardizationSteps.generate_identity_hash, "generate_hash")
pipeline.add_step(StandardizationSteps.validate_required_fields, "validate")
```

---

**本架构设计文档提供了完整的技术蓝图，系统具有高度的可扩展性和可维护性，可根据实际需求逐步实施。**
