"""
AggregationBuilder — 增强聚合查询构建器

支持:
1. 多字段GROUP BY
2. HAVING过滤
3. 复杂统计函数 (COUNT, SUM, AVG, MIN, MAX, GROUP_CONCAT)
4. 分布统计查询
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AggFunc(Enum):
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    GROUP_CONCAT = "GROUP_CONCAT"


@dataclass
class AggSpec:
    """聚合规格"""
    group_by: list[str]
    aggregates: list[tuple[AggFunc, str, str]] = field(default_factory=list)  # (func, field, alias)
    having: list[tuple[str, str, Any]] | None = None  # [(expr, op, value)]
    order_by: list[tuple[str, str]] | None = None  # [(field, direction)]
    limit: int | None = None


class AggregationBuilder:
    """增强聚合查询构建器"""

    def build(
        self,
        spec: AggSpec,
        from_clause: str,
        where_clause: str = "1=1",
        where_params: list | None = None,
    ) -> tuple[str, list]:
        """
        构建完整聚合查询

        Returns: (sql, params)
        """
        params = list(where_params or [])

        # SELECT
        select_parts = list(spec.group_by)
        for func, fld, alias in spec.aggregates:
            if fld == "*":
                select_parts.append(f"{func.value}(*) as {alias}")
            else:
                select_parts.append(f"{func.value}({fld}) as {alias}")

        # 如果没有指定聚合函数，默认COUNT
        if not spec.aggregates:
            select_parts.append("COUNT(*) as count")

        select_sql = ", ".join(select_parts)
        group_by_sql = ", ".join(spec.group_by)

        sql = f"SELECT {select_sql}\n{from_clause}\nWHERE {where_clause}\nGROUP BY {group_by_sql}"

        # HAVING
        if spec.having:
            having_parts = []
            for expr, op, value in spec.having:
                having_parts.append(f"{expr} {op} ?")
                params.append(value)
            sql += f"\nHAVING {' AND '.join(having_parts)}"

        # ORDER BY
        if spec.order_by:
            order_parts = [f"{f} {d}" for f, d in spec.order_by]
            sql += f"\nORDER BY {', '.join(order_parts)}"
        elif spec.aggregates:
            # 默认按第一个聚合函数降序
            sql += f"\nORDER BY {spec.aggregates[0][2]} DESC"
        else:
            sql += "\nORDER BY count DESC"

        # LIMIT
        if spec.limit:
            sql += f"\nLIMIT {spec.limit}"

        return sql, params

    def build_distribution(
        self,
        table: str,
        field: str,
        top_n: int = 20,
        min_count: int = 1,
        where_clause: str = "1=1",
        where_params: list | None = None,
    ) -> tuple[str, list]:
        """
        构建分布统计查询

        示例: 各组织的样本分布
        """
        spec = AggSpec(
            group_by=[field],
            aggregates=[
                (AggFunc.COUNT, "*", "count"),
            ],
            having=[("count", ">=", min_count)] if min_count > 1 else None,
            order_by=[("count", "DESC")],
            limit=top_n,
        )
        return self.build(
            spec,
            f"FROM {table}",
            f"{field} IS NOT NULL AND ({where_clause})",
            where_params,
        )

    def build_cross_stats(
        self,
        table: str,
        fields: list[str],
        where_clause: str = "1=1",
        where_params: list | None = None,
        limit: int = 100,
    ) -> tuple[str, list]:
        """
        构建多字段交叉统计

        示例: 组织+疾病的交叉统计
        """
        spec = AggSpec(
            group_by=fields,
            aggregates=[
                (AggFunc.COUNT, "*", "count"),
                (AggFunc.AVG, "n_cells", "avg_cells"),
            ],
            order_by=[("count", "DESC")],
            limit=limit,
        )
        return self.build(spec, f"FROM {table}", where_clause, where_params)
