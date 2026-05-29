"""
EnhancedJoinResolver — 增强版JOIN解析器

支持:
1. 自动推导任意表间JOIN路径 (BFS图算法)
2. 基于数据分布选择最优JOIN类型
3. 视图优化判断
4. 可通过 SchemaConfig 动态构建 JoinGraph
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.schema_config import SchemaConfig

logger = logging.getLogger(__name__)


class JoinType(Enum):
    INNER = "INNER JOIN"
    LEFT = "LEFT JOIN"
    EXISTS = "EXISTS"


@dataclass
class JoinEdge:
    """表间连接边"""
    from_table: str
    to_table: str
    join_type: JoinType
    from_field: str
    to_field: str
    cardinality: str = "many_to_one"  # one_to_one, one_to_many, many_to_many


@dataclass
class JoinGraph:
    """数据库表连接图"""
    tables: set[str] = field(default_factory=set)
    edges: list[JoinEdge] = field(default_factory=list)

    def find_path(self, start: str, end: str) -> Optional[list[JoinEdge]]:
        """BFS查找两表间最短路径"""
        if start == end:
            return []

        queue: deque[tuple[str, list[JoinEdge]]] = deque([(start, [])])
        visited = {start}

        while queue:
            current, path = queue.popleft()

            for edge in self.edges:
                # 正向
                if edge.from_table == current and edge.to_table not in visited:
                    new_path = path + [edge]
                    if edge.to_table == end:
                        return new_path
                    visited.add(edge.to_table)
                    queue.append((edge.to_table, new_path))

                # 反向 (无向图)
                elif edge.to_table == current and edge.from_table not in visited:
                    reverse = JoinEdge(
                        from_table=edge.to_table,
                        to_table=edge.from_table,
                        join_type=edge.join_type,
                        from_field=edge.to_field,
                        to_field=edge.from_field,
                        cardinality=edge.cardinality,
                    )
                    new_path = path + [reverse]
                    if edge.from_table == end:
                        return new_path
                    visited.add(edge.from_table)
                    queue.append((edge.from_table, new_path))

        return None


@dataclass
class EnhancedJoinPlan:
    """JOIN执行计划"""
    base_table: str
    base_alias: str = ""
    joins: list[JoinEdge] = field(default_factory=list)
    use_view: bool = False

    def to_from_clause(self) -> str:
        if self.use_view:
            return f"FROM {self.base_table}"

        alias = f" {self.base_alias}" if self.base_alias else ""
        parts = [f"FROM {self.base_table}{alias}"]

        # 用于生成唯一别名
        alias_map = {self.base_table: self.base_alias or self.base_table}
        seen_tables = {self.base_table}

        for edge in self.joins:
            if edge.to_table in seen_tables:
                continue
            seen_tables.add(edge.to_table)

            # 生成别名
            to_alias = _table_alias(edge.to_table)
            alias_map[edge.to_table] = to_alias

            from_ref = alias_map.get(edge.from_table, edge.from_table)
            condition = f"{from_ref}.{edge.from_field} = {to_alias}.{edge.to_field}"
            parts.append(f"{edge.join_type.value} {edge.to_table} {to_alias} ON {condition}")

        return "\n".join(parts)


_DEFAULT_TABLE_ALIASES: dict[str, str] = {
    "unified_samples": "s",
    "unified_series": "sr",
    "unified_projects": "p",
    "unified_celltypes": "ct",
}


def _table_alias(table: str, alias_map: dict[str, str] | None = None) -> str:
    """生成表别名"""
    m = alias_map if alias_map is not None else _DEFAULT_TABLE_ALIASES
    return m.get(table, table[:2])


# 视图包含的字段 (默认值)
_DEFAULT_VIEW_FIELDS = {
    "sample_pk", "sample_id", "sample_id_type", "sample_source",
    "organism", "tissue", "tissue_ontology_term_id", "tissue_general",
    "disease", "disease_ontology_term_id",
    "sex", "age", "age_unit", "development_stage", "ethnicity",
    "individual_id", "n_cells", "n_cell_types", "biological_identity_hash",
    # Standardized fields
    "tissue_standard", "tissue_system",
    "disease_standard", "disease_category",
    "organism_normalized", "organism_common",
    "sex_normalized", "sample_type",
    # Phase 38: canonical anatomical / lineage roll-ups (now exposed by the view)
    "tissue_standard_l1", "tissue_standard_leaf",
    "disease_standard_l1", "cell_type_standard", "cell_type_lineage",
    # Series
    "series_pk", "series_id", "series_title", "assay",
    "series_cell_count",
    # Projects
    "project_pk", "project_id", "project_title",
    "pmid", "doi", "citation_count",
}

# 保持向后兼容
VIEW_FIELDS = _DEFAULT_VIEW_FIELDS


class EnhancedJoinResolver:
    """
    增强版JOIN解析器

    相比原JoinPathResolver:
    - 支持任意表间路径推导 (BFS)
    - 支持反向查询 (samples→celltypes)
    - 自动判断是否可用视图
    - 可通过 SchemaConfig 动态构建 JoinGraph
    """

    # 默认 JOIN 边 — 当无 SchemaConfig 时使用
    _DEFAULT_EDGES = [
        ("unified_samples", "unified_series", JoinType.LEFT, "series_pk", "pk", "many_to_one"),
        ("unified_samples", "unified_projects", JoinType.LEFT, "project_pk", "pk", "many_to_one"),
        ("unified_celltypes", "unified_samples", JoinType.INNER, "sample_pk", "pk", "many_to_one"),
        ("unified_series", "unified_projects", JoinType.LEFT, "project_pk", "pk", "many_to_one"),
    ]

    _DEFAULT_TABLES = {
        "unified_samples", "unified_series",
        "unified_projects", "unified_celltypes",
    }

    def __init__(self, *, schema_config: SchemaConfig | None = None):
        self._schema_config = schema_config

        if schema_config is not None:
            self._main_table = schema_config.main_table
            self._main_view = schema_config.main_view or "v_sample_with_hierarchy"
            self._view_fields = set(schema_config.view_fields) if schema_config.view_fields else set(_DEFAULT_VIEW_FIELDS)
            self._graph = self._build_graph_from_schema(schema_config)
        else:
            self._main_table = "unified_samples"
            self._main_view = "v_sample_with_hierarchy"
            self._view_fields = set(_DEFAULT_VIEW_FIELDS)
            self._graph = self._build_default_graph()

    def _build_default_graph(self) -> JoinGraph:
        graph = JoinGraph()
        graph.tables = set(self._DEFAULT_TABLES)
        graph.edges = [
            JoinEdge(ft, tt, jt, ff, tf, c)
            for ft, tt, jt, ff, tf, c in self._DEFAULT_EDGES
        ]
        return graph

    @staticmethod
    def _build_graph_from_schema(schema_config: SchemaConfig) -> JoinGraph:
        """从 SchemaConfig 的外键关系动态构建 JoinGraph。"""
        graph = JoinGraph()
        graph.tables = set(schema_config.get_table_names(include_views=False))

        for fk in schema_config.foreign_keys:
            # 推断 JOIN 类型: celltype 表用 INNER, 其余用 LEFT
            if "celltype" in fk.from_table.lower() or "cell_type" in fk.from_table.lower():
                join_type = JoinType.INNER
            else:
                join_type = JoinType.LEFT

            graph.edges.append(JoinEdge(
                from_table=fk.from_table,
                to_table=fk.to_table,
                join_type=join_type,
                from_field=fk.from_field,
                to_field=fk.to_field,
                cardinality="many_to_one",
            ))

        return graph

    def resolve(
        self,
        target_table: str,
        needed_tables: set[str],
        needed_fields: set[str] | None = None,
    ) -> EnhancedJoinPlan:
        """
        解析最优JOIN计划

        Args:
            target_table: 主查询表
            needed_tables: 需要JOIN的表集合
            needed_fields: 需要的字段集合 (用于判断是否可用视图)
        """
        # 检查是否可用视图
        if target_table == self._main_table and needed_fields:
            # 获取 celltype 表名 (动态)
            ct_tables = {
                t for t in self._graph.tables
                if "celltype" in t.lower() or "cell_type" in t.lower()
            }
            if needed_fields.issubset(self._view_fields) and not (needed_tables & ct_tables):
                return EnhancedJoinPlan(
                    base_table=self._main_view, use_view=True,
                )

        needed_tables.discard(target_table)
        if not needed_tables:
            return EnhancedJoinPlan(
                base_table=target_table,
                base_alias=_table_alias(target_table),
            )

        # BFS查找JOIN路径
        join_edges: list[JoinEdge] = []
        for needed in sorted(needed_tables):
            path = self._graph.find_path(target_table, needed)
            if path:
                join_edges.extend(path)
            else:
                logger.warning("No JOIN path from %s to %s", target_table, needed)

        # 去重
        seen = set()
        unique_edges = []
        for edge in join_edges:
            key = (edge.from_table, edge.to_table)
            if key not in seen:
                seen.add(key)
                unique_edges.append(edge)

        return EnhancedJoinPlan(
            base_table=target_table,
            base_alias=_table_alias(target_table),
            joins=unique_edges,
        )
