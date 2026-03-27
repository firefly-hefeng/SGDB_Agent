"""
SCeQTL-Agent V2 核心数据模型

所有模块共享的数据结构定义。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ========== 枚举 ==========

class QueryIntent(enum.Enum):
    """查询意图"""
    SEARCH = "search"
    COMPARE = "compare"
    STATISTICS = "statistics"
    EXPLORE = "explore"
    DOWNLOAD = "download"
    LINEAGE = "lineage"


class QueryComplexity(enum.Enum):
    """查询复杂度"""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class QueryStrategy(enum.Enum):
    """查询策略等级 (渐进降级)"""
    EXACT = "exact"
    STANDARD = "standard"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"


# ========== 查询理解输出 ==========

@dataclass
class BioEntity:
    """生物学实体"""
    text: str                               # 用户原始文本 e.g. "大脑"
    entity_type: str                        # "tissue" | "disease" | "cell_type" | "organism" | "assay"
    normalized_value: str | None = None     # 初步标准化 e.g. "brain"
    ontology_id: str | None = None          # 本体ID (待resolve_ontology填充)
    negated: bool = False                   # 否定条件 e.g. "非癌症"


@dataclass
class QueryFilters:
    """结构化过滤条件"""
    organisms: list[str] = field(default_factory=list)
    tissues: list[str] = field(default_factory=list)
    diseases: list[str] = field(default_factory=list)
    cell_types: list[str] = field(default_factory=list)
    assays: list[str] = field(default_factory=list)
    sex: str | None = None
    age_range: tuple[float, float] | None = None
    development_stages: list[str] = field(default_factory=list)
    source_databases: list[str] = field(default_factory=list)
    # ID类
    project_ids: list[str] = field(default_factory=list)
    sample_ids: list[str] = field(default_factory=list)
    pmids: list[str] = field(default_factory=list)
    dois: list[str] = field(default_factory=list)
    # 数值
    min_cells: int | None = None
    min_citation_count: int | None = None
    has_h5ad: bool | None = None
    # 时间
    published_after: str | None = None
    published_before: str | None = None
    # 自由文本 (无法结构化的部分)
    free_text: str | None = None


@dataclass
class AggregationSpec:
    """聚合规格"""
    group_by: list[str]
    metric: str = "count"  # "count" | "sum" | "avg"


@dataclass
class OrderingSpec:
    """排序规格"""
    field: str
    direction: str = "desc"  # "asc" | "desc"


@dataclass
class ParsedQuery:
    """查询理解的完整输出"""
    intent: QueryIntent
    sub_intent: str = ""
    complexity: QueryComplexity = QueryComplexity.SIMPLE
    entities: list[BioEntity] = field(default_factory=list)
    filters: QueryFilters = field(default_factory=QueryFilters)
    target_level: str = "sample"  # "project" | "series" | "sample" | "celltype"
    aggregation: AggregationSpec | None = None
    ordering: OrderingSpec | None = None
    limit: int = 20
    original_text: str = ""
    language: str = "en"
    confidence: float = 1.0
    parse_method: str = "rule"  # "rule" | "llm"


# ========== 本体解析输出 ==========

@dataclass
class OntologyTerm:
    """本体术语"""
    ontology_id: str
    ontology_source: str        # "UBERON", "MONDO", "CL", "EFO"
    label: str
    synonyms: list[str] = field(default_factory=list)
    definition: str = ""
    parent_ids: list[str] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)


@dataclass
class DBValueMatch:
    """数据库值匹配"""
    raw_value: str              # 数据库中的实际值
    ontology_id: str = ""       # 对应的本体ID
    field_name: str = ""        # 匹配的字段名
    count: int = 0              # 出现次数
    match_type: str = "exact"   # "exact" | "synonym" | "hierarchy"


@dataclass
class ResolvedEntity:
    """本体解析后的实体"""
    original: BioEntity
    ontology_term: OntologyTerm | None = None
    expanded_terms: list[OntologyTerm] = field(default_factory=list)
    db_values: list[DBValueMatch] = field(default_factory=list)
    total_sample_count: int = 0


# ========== SQL生成与执行 ==========

@dataclass
class JoinClause:
    """JOIN子句"""
    join_type: str      # "LEFT JOIN" | "INNER JOIN"
    table: str
    alias: str = ""
    condition: str = ""


@dataclass
class JoinPlan:
    """JOIN计划"""
    base_table: str
    joins: list[JoinClause] = field(default_factory=list)
    use_view: bool = False

    def to_sql_from(self) -> str:
        if self.use_view:
            return f"FROM {self.base_table}"
        parts = [f"FROM {self.base_table}"]
        for j in self.joins:
            alias = f" AS {j.alias}" if j.alias else ""
            parts.append(f"{j.join_type} {j.table}{alias} ON {j.condition}")
        return "\n".join(parts)


@dataclass
class SQLCandidate:
    """SQL候选"""
    sql: str
    params: list[Any] = field(default_factory=list)
    method: str = "rule"  # "template" | "rule" | "llm"
    cost: float = 0.0     # LLM调用成本


@dataclass
class ValidationResult:
    """SQL验证结果"""
    is_valid: bool = True
    issue: str = ""
    suggestion: str = ""
    note: str = ""


@dataclass
class ExecutionResult:
    """SQL执行结果"""
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    sql: str = ""
    params: list[Any] = field(default_factory=list)
    method: str = ""
    exec_time_ms: float = 0.0
    row_count: int = 0
    validation: ValidationResult = field(default_factory=ValidationResult)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def empty(cls, errors: list[str] | None = None) -> ExecutionResult:
        return cls(
            validation=ValidationResult(
                is_valid=False,
                issue="all_candidates_failed",
                note="; ".join(errors or []),
            )
        )


# ========== 跨库融合 ==========

@dataclass
class FusedRecord:
    """融合后的记录"""
    data: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    source_count: int = 0
    all_ids: dict = field(default_factory=dict)
    records_merged: int = 1
    quality_score: float = 0.0


# ========== 答案合成 ==========

@dataclass
class Suggestion:
    """后续操作建议"""
    type: str           # "refine" | "expand" | "compare" | "download" | "related"
    text: str
    action_query: str
    reason: str = ""


@dataclass
class ChartSpec:
    """可视化规格 (供前端渲染)"""
    type: str           # "bar" | "pie" | "line"
    title: str
    data: dict | list = field(default_factory=dict)


@dataclass
class ProvenanceInfo:
    """数据血缘"""
    original_query: str = ""
    parsed_intent: str = ""
    ontology_expansions: list[dict] = field(default_factory=list)
    sql_executed: str = ""
    sql_method: str = ""
    strategy_level: str = ""
    fusion_stats: dict = field(default_factory=dict)
    data_sources: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


@dataclass
class QualityReport:
    """数据质量报告"""
    field_completeness: dict[str, float] = field(default_factory=dict)
    cross_validation_score: float = 0.0
    source_coverage: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Agent最终输出"""
    summary: str = ""
    results: list[FusedRecord] = field(default_factory=list)
    total_count: int = 0
    displayed_count: int = 0
    provenance: ProvenanceInfo = field(default_factory=ProvenanceInfo)
    quality_report: QualityReport = field(default_factory=QualityReport)
    suggestions: list[Suggestion] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    error: str | None = None


# ========== LLM相关 ==========

@dataclass
class TokenUsage:
    """Token用量"""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMToolCall:
    """LLM工具调用"""
    tool_name: str
    tool_input: dict
    tool_id: str = ""


@dataclass
class LLMResponse:
    """LLM响应"""
    content: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str = ""

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


# ========== 查询结果 ==========

@dataclass
class QueryResult:
    """统一查询结果 (DAL层输出)"""
    rows: list[dict] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    total_count: int = 0
    returned_count: int = 0
    execution_time_ms: float = 0.0
    sql: str = ""
    source: str = ""  # "view" | "table" | "raw"


@dataclass
class FieldStats:
    """字段统计信息"""
    table_name: str
    field_name: str
    total_count: int = 0
    non_null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0
    top_values: list[tuple[str, int]] = field(default_factory=list)
    semantic_type: str = ""  # "tissue" | "disease" | "id" | "metric" | ...


# ========== 会话上下文 ==========

@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str = ""
    turns: list[dict] = field(default_factory=list)
    active_filters: QueryFilters | None = None
    last_result_count: int = 0
    created_at: float = 0.0
    last_active_at: float = 0.0
    recent_queries: list = field(default_factory=list)  # recent ParsedQuery objects
