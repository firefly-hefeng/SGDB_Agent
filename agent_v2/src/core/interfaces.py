"""
SCeQTL-Agent V2 核心接口定义 (Protocol)

所有模块通过Protocol接口交互，支持依赖注入和独立测试。
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from .models import (
    AgentResponse,
    BioEntity,
    ExecutionResult,
    FieldStats,
    FusedRecord,
    LLMResponse,
    ParsedQuery,
    QueryFilters,
    QueryResult,
    ResolvedEntity,
    SQLCandidate,
    SessionContext,
    TokenUsage,
)


# ========== LLM接口 ==========

@runtime_checkable
class ILLMClient(Protocol):
    """LLM客户端统一接口 - 供应商无关"""

    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse: ...

    async def chat_stream(
        self,
        messages: list[dict],
        system: str = "",
    ) -> AsyncIterator[str]: ...

    def estimate_tokens(self, text: str) -> int: ...

    @property
    def model_id(self) -> str: ...

    @property
    def supports_tool_use(self) -> bool: ...


# ========== Agent核心模块接口 ==========

@runtime_checkable
class IQueryParser(Protocol):
    """查询理解接口"""

    async def parse(
        self,
        query: str,
        context: SessionContext | None = None,
    ) -> ParsedQuery: ...


@runtime_checkable
class IOntologyResolver(Protocol):
    """本体解析接口"""

    async def resolve(
        self,
        entities: list[BioEntity],
        expand_hierarchy: bool = True,
        max_depth: int = 2,
    ) -> list[ResolvedEntity]: ...


@runtime_checkable
class ISQLGenerator(Protocol):
    """SQL生成接口"""

    async def generate(
        self,
        query: ParsedQuery,
        entities: list[ResolvedEntity],
    ) -> list[SQLCandidate]: ...


@runtime_checkable
class ISQLExecutor(Protocol):
    """SQL执行接口"""

    async def execute(
        self,
        candidates: list[SQLCandidate],
    ) -> ExecutionResult: ...


@runtime_checkable
class IFusionEngine(Protocol):
    """跨库融合接口"""

    def fuse(
        self,
        results: list[dict],
        entity_type: str = "sample",
    ) -> list[FusedRecord]: ...


@runtime_checkable
class IAnswerSynthesizer(Protocol):
    """答案合成接口"""

    async def synthesize(
        self,
        query: ParsedQuery,
        results: list[FusedRecord],
        provenance: dict,
    ) -> AgentResponse: ...


# ========== 数据访问接口 ==========

@runtime_checkable
class IDatabase(Protocol):
    """数据库访问接口"""

    def execute(self, sql: str, params: list | None = None) -> QueryResult: ...

    def get_schema_summary(self) -> dict: ...

    def get_field_stats(
        self, table: str, field: str, top_n: int = 20
    ) -> FieldStats: ...

    def search_samples(
        self,
        filters: QueryFilters,
        fields: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> QueryResult: ...

    def get_entity_by_id(self, id_value: str) -> dict | None: ...


# ========== 记忆系统接口 ==========

@runtime_checkable
class IMemorySystem(Protocol):
    """记忆系统接口"""

    def load_session(self, session_id: str) -> SessionContext: ...

    def save_interaction(
        self,
        session_id: str,
        user_input: str,
        response: AgentResponse,
    ) -> None: ...

    def get_schema_knowledge(self, concept: str) -> list[dict]: ...


# ========== 缓存接口 ==========

@runtime_checkable
class ICache(Protocol):
    """通用缓存接口"""

    def get(self, key: str) -> object | None: ...

    def set(self, key: str, value: object, ttl: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...


# ========== Schema Knowledge接口 ==========

@runtime_checkable
class ISchemaKnowledge(Protocol):
    """Schema Knowledge 只读接口"""

    def format_for_parse_prompt(self) -> str: ...

    def format_for_validation(self, filters: dict) -> str: ...

    def format_for_recovery(self, filters: dict) -> str: ...

    def format_for_sql_generation(self) -> str: ...

    def format_for_suggestions(self) -> str: ...

    def resolve_synonym(self, field: str, term: str) -> str | None: ...

    def get_top_values(self, field: str, n: int = 20) -> list[dict]: ...

    def match_id_pattern(self, text: str) -> dict | None: ...
