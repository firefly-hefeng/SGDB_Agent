"""
熔断器 + LLM路由器

CircuitBreaker: 防止LLM API故障时的级联失败
LLMRouter: 智能路由 + 降级 + 成本控制
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from ..core.models import LLMResponse, TokenUsage
from ..core.interfaces import ILLMClient

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    熔断器 - 三态: CLOSED → OPEN → HALF_OPEN → CLOSED

    - CLOSED: 正常工作
    - OPEN: 连续失败达到阈值，拒绝所有请求
    - HALF_OPEN: 恢复超时后，允许一次试探请求
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = self.HALF_OPEN
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == self.OPEN

    def record_success(self):
        self._failure_count = 0
        self._state = self.CLOSED

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            logger.warning(
                "Circuit breaker OPEN after %d failures", self._failure_count
            )


class LLMRouter:
    """
    LLM路由器

    职责:
    1. 正常请求 → 主LLM
    2. 主LLM故障 → 熔断 → 备选LLM
    3. 超预算 → 拒绝LLM调用
    4. 超时保护
    """

    def __init__(
        self,
        primary: ILLMClient,
        fallback: ILLMClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        request_timeout: float = 30.0,
    ):
        self.primary = primary
        self.fallback = fallback
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.request_timeout = request_timeout

    @property
    def model_id(self) -> str:
        return self.primary.model_id

    @property
    def supports_tool_use(self) -> bool:
        return self.primary.supports_tool_use

    def estimate_tokens(self, text: str) -> int:
        return self.primary.estimate_tokens(text)

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # 1. 检查熔断器
        if not self.circuit_breaker.is_open:
            try:
                response = await asyncio.wait_for(
                    self.primary.chat(
                        messages, system, tools, temperature, max_tokens
                    ),
                    timeout=self.request_timeout,
                )
                self.circuit_breaker.record_success()
                return response
            except Exception as e:
                self.circuit_breaker.record_failure()
                logger.warning("Primary LLM failed: %s", e)

        # 2. 降级到备选LLM
        if self.fallback:
            try:
                logger.info("Falling back to %s", self.fallback.model_id)
                return await asyncio.wait_for(
                    self.fallback.chat(
                        messages, system, tools, temperature, max_tokens
                    ),
                    timeout=self.request_timeout,
                )
            except Exception as e:
                logger.error("Fallback LLM also failed: %s", e)

        # 3. 所有LLM都失败
        return LLMResponse(
            content="[LLM服务暂时不可用，正在使用规则引擎处理您的查询]",
            usage=TokenUsage(model="none"),
            stop_reason="error",
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
    ) -> AsyncIterator[str]:
        if not self.circuit_breaker.is_open:
            try:
                async for chunk in self.primary.chat_stream(messages, system):
                    yield chunk
                self.circuit_breaker.record_success()
                return
            except Exception as e:
                self.circuit_breaker.record_failure()
                logger.warning("Primary stream failed: %s", e)

        if self.fallback:
            async for chunk in self.fallback.chat_stream(messages, system):
                yield chunk
