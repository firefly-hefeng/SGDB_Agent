"""
LLM客户端实现

支持 Anthropic Claude 和 OpenAI GPT 两种后端，
通过 ILLMClient Protocol 统一接口。
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from ..core.models import LLMResponse, LLMToolCall, TokenUsage

logger = logging.getLogger(__name__)


class ClaudeLLMClient:
    """Anthropic Claude 客户端"""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError:
            raise ImportError("pip install anthropic")
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def supports_tool_use(self) -> bool:
        return True

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4  # 粗略估算

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        # 解析响应
        content_text = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content_text += block.text
            elif block.type == "tool_use":
                tool_calls.append(LLMToolCall(
                    tool_name=block.name,
                    tool_input=block.input,
                    tool_id=block.id,
                ))

        return LLMResponse(
            content=content_text,
            tool_calls=tool_calls,
            usage=TokenUsage(
                model=self._model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason or "",
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
    ) -> AsyncIterator[str]:
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if system:
            kwargs["system"] = system

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAILLMClient:
    """OpenAI-compatible API client (supports OpenAI, Kimi/Moonshot, etc.)"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str | None = None):
        try:
            import openai
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        except ImportError:
            raise ImportError("pip install openai")
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def supports_tool_use(self) -> bool:
        return True

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        kwargs: dict = {
            "model": self._model,
            "messages": oai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        tool_calls = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                tool_calls.append(LLMToolCall(
                    tool_name=tc.function.name,
                    tool_input=json.loads(tc.function.arguments),
                    tool_id=tc.id,
                ))

        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            usage=TokenUsage(
                model=self._model,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            ),
            stop_reason=choice.finish_reason or "",
        )

    async def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
    ) -> AsyncIterator[str]:
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            max_tokens=4096,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @staticmethod
    def _convert_tools(anthropic_tools: list[dict]) -> list[dict]:
        """Anthropic tool格式 → OpenAI function格式"""
        oai_tools = []
        for tool in anthropic_tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return oai_tools
