"""
CardinalityEstimator — 基数估计器

基于数据分布统计预估查询结果规模，用于:
1. 自动调整LIMIT
2. 大结果集预警
3. JOIN顺序优化
"""

from __future__ import annotations

import logging
from typing import Optional

from .data_stats import DataStatsAnalyzer

logger = logging.getLogger(__name__)


class CardinalityEstimator:
    """基数估计器"""

    def __init__(self, stats_analyzer: DataStatsAnalyzer):
        self.stats = stats_analyzer

    async def estimate_result_size(
        self,
        table: str,
        filters: dict[str, list[str]],
        operator: str = "AND",
    ) -> int:
        """
        估算查询将返回多少行

        算法: combined_selectivity = sel1 * sel2 * ... * selN (独立性假设)
        """
        total_rows = await self.stats.get_table_row_count(table)
        if not filters:
            return total_rows

        selectivities: list[float] = []
        for field, values in filters.items():
            if not values:
                continue
            # 多值取OR: 选择性之和 (上限1.0)
            field_sel = 0.0
            for value in values:
                est = await self.stats.estimate_selectivity(table, field, value)
                field_sel += est.estimated_selectivity
            field_sel = min(field_sel, 1.0)
            selectivities.append(field_sel)

        if not selectivities:
            return total_rows

        if operator == "AND":
            combined = 1.0
            for s in selectivities:
                combined *= s
        else:  # OR
            combined = 1.0
            for s in selectivities:
                combined *= (1 - s)
            combined = 1 - combined

        return max(1, int(total_rows * combined))

    async def suggest_limit(
        self,
        table: str,
        filters: dict[str, list[str]],
        user_requested_limit: Optional[int] = None,
    ) -> int:
        """
        根据估计结果大小建议LIMIT值

        策略:
        - >100K: 严格限制20条
        - 10K-100K: 限制50条
        - 1K-10K: 限制100条
        - <1K: 放宽到200条或用户指定
        """
        estimated = await self.estimate_result_size(table, filters)

        if estimated > 100000:
            suggested = 20
        elif estimated > 10000:
            suggested = 50
        elif estimated > 1000:
            suggested = 100
        else:
            suggested = 200

        if user_requested_limit and user_requested_limit <= suggested * 2:
            return user_requested_limit
        return suggested

    async def should_warn_large_result(
        self,
        table: str,
        filters: dict[str, list[str]],
        threshold: int = 5000,
    ) -> tuple[bool, int, str]:
        """
        是否应该警告用户结果集过大

        Returns: (should_warn, estimated_size, suggestion_message)
        """
        estimated = await self.estimate_result_size(table, filters)
        if estimated < threshold:
            return False, estimated, ""

        if estimated > 50000:
            msg = f"估计返回约{estimated:,}条结果，建议添加更具体的筛选条件（如疾病类型、细胞类型）"
        elif estimated > 10000:
            msg = f"估计返回约{estimated:,}条结果，已自动限制返回条数"
        else:
            msg = f"估计返回约{estimated:,}条结果"

        return True, estimated, msg
