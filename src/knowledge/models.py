"""
Dynamic Knowledge Layer — Data Models

数据统计、基数估计、查询反馈循环所需的数据结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FieldStats:
    """字段级统计信息"""
    field_name: str
    table_name: str
    data_type: str = "TEXT"
    semantic_type: str = "metadata"  # tissue, disease, cell_type, organism, id, metric, metadata

    total_count: int = 0
    non_null_count: int = 0
    null_pct: float = 0.0
    distinct_count: int = 0

    histogram: list[tuple[str, int]] = field(default_factory=list)  # Top-N (value, count)
    min_value: Any = None
    max_value: Any = None
    avg_value: float = 0.0

    selectivity: float = 1.0  # distinct_count / total_count
    last_updated: datetime = field(default_factory=datetime.now)
    sample_size: int = 0


@dataclass
class TableStats:
    """表级统计信息"""
    table_name: str
    total_rows: int = 0
    indexes: list[dict] = field(default_factory=list)
    field_stats: dict[str, FieldStats] = field(default_factory=dict)


@dataclass
class SelectivityEstimate:
    """选择性估计结果"""
    table: str
    field: str
    pattern: str
    estimated_selectivity: float = 0.5
    confidence: float = 0.3
    based_on: str = "default"  # histogram_exact, histogram_prefix, semantic_default, default

    def estimated_rows(self, total_rows: int) -> int:
        if total_rows <= 0:
            return 0
        return max(1, int(total_rows * self.estimated_selectivity))


@dataclass
class QueryExecutionRecord:
    """查询执行记录"""
    id: int = 0
    query_pattern: str = ""
    sql_template: str = ""
    estimated_rows: int = 0
    actual_rows: int = 0
    estimation_error: float = 0.0
    execution_time_ms: float = 0.0
    filters_used: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class KnowledgeContext:
    """注入SQL生成的知识上下文"""
    field_stats: dict[str, FieldStats] = field(default_factory=dict)
    table_stats: dict[str, TableStats] = field(default_factory=dict)
    selectivity_hints: list[SelectivityEstimate] = field(default_factory=list)
    suggested_limit: int = 20
    warnings: list[str] = field(default_factory=list)
    estimated_result_size: int = 0
