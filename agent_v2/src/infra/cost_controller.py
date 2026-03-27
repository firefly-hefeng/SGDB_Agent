"""
LLM成本控制器

跟踪每日LLM API调用成本，在超预算时自动降级。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..core.models import TokenUsage

logger = logging.getLogger(__name__)


# Token定价 (USD per 1M tokens, 2026-03)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # 本地/免费
    "none": {"input": 0.0, "output": 0.0},
}


@dataclass
class CostRecord:
    """单次调用成本记录"""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: float


class CostController:
    """
    LLM调用成本控制

    功能:
    - 跟踪每日累计成本
    - 超预算时拒绝LLM调用
    - 基于复杂度和预算选择模型
    - 输出成本报告
    """

    def __init__(self, daily_budget_usd: float = 50.0):
        self.daily_budget = daily_budget_usd
        self._daily_spend = 0.0
        self._reset_time = self._next_midnight()
        self._records: list[CostRecord] = []

    @property
    def daily_spend(self) -> float:
        self._check_reset()
        return self._daily_spend

    @property
    def remaining_budget(self) -> float:
        return max(0.0, self.daily_budget - self.daily_spend)

    def has_budget(self) -> bool:
        return self.remaining_budget > 0

    def select_model(self, complexity: str, preferred_model: str = "") -> str:
        """
        根据复杂度和剩余预算选择最优模型

        Returns:
            模型ID, 如果预算不足返回空字符串表示应使用规则引擎
        """
        self._check_reset()

        remaining = self.remaining_budget

        # 预算<$1: 只用最便宜的
        if remaining < 1.0:
            return "claude-haiku-4-5" if remaining > 0.01 else ""

        # 预算<$5: 简单任务用Haiku，复杂任务也尝试Haiku
        if remaining < 5.0:
            return "claude-haiku-4-5"

        # 预算充足: 按复杂度选择
        if preferred_model:
            return preferred_model

        model_map = {
            "simple": "claude-haiku-4-5",
            "moderate": "claude-haiku-4-5",
            "complex": "claude-sonnet-4-6",
            "ambiguous": "claude-sonnet-4-6",
        }
        return model_map.get(complexity, "claude-haiku-4-5")

    def record_usage(self, usage: TokenUsage) -> float:
        """记录一次调用的成本，返回本次成本"""
        cost = self.estimate_cost(usage.model, usage.input_tokens, usage.output_tokens)
        self._daily_spend += cost
        self._records.append(CostRecord(
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
            timestamp=time.time(),
        ))

        if self._daily_spend >= self.daily_budget * 0.8:
            logger.warning(
                "LLM cost at %.0f%% of daily budget ($%.2f / $%.2f)",
                (self._daily_spend / self.daily_budget) * 100,
                self._daily_spend,
                self.daily_budget,
            )

        return cost

    @staticmethod
    def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """估算单次调用成本 (USD)"""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING.get("claude-haiku-4-5", {}))
        return (
            input_tokens * pricing.get("input", 0)
            + output_tokens * pricing.get("output", 0)
        ) / 1_000_000

    def get_report(self) -> dict:
        """获取成本报告"""
        self._check_reset()
        by_model: dict[str, dict] = {}
        for r in self._records:
            if r.model not in by_model:
                by_model[r.model] = {"calls": 0, "cost": 0.0, "tokens": 0}
            by_model[r.model]["calls"] += 1
            by_model[r.model]["cost"] += r.cost_usd
            by_model[r.model]["tokens"] += r.input_tokens + r.output_tokens

        return {
            "daily_budget": self.daily_budget,
            "daily_spend": round(self._daily_spend, 4),
            "remaining": round(self.remaining_budget, 4),
            "total_calls": len(self._records),
            "by_model": by_model,
        }

    def _check_reset(self):
        """午夜自动重置"""
        now = time.time()
        if now >= self._reset_time:
            logger.info("Daily cost reset: $%.2f spent yesterday", self._daily_spend)
            self._daily_spend = 0.0
            self._records.clear()
            self._reset_time = self._next_midnight()

    @staticmethod
    def _next_midnight() -> float:
        import datetime
        now = datetime.datetime.now()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow += datetime.timedelta(days=1)
        return tomorrow.timestamp()
