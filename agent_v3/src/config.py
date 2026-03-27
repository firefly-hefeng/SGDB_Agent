"""SCeQTL-Agent V2 配置管理"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class DatabaseConfig:
    """数据库配置"""
    # unified_metadata.db 的路径
    db_path: str = ""
    # 只读模式 (Agent查询不需要写入主库)
    read_only: bool = True
    # 连接池大小 (读连接)
    pool_size: int = 5
    # 查询超时 (秒)
    query_timeout: float = 30.0

    def __post_init__(self):
        if not self.db_path:
            # 默认路径: 从项目结构推导
            project_root = Path(__file__).parent.parent.parent
            default = project_root / "database_development" / "unified_db" / "unified_metadata.db"
            if default.exists():
                self.db_path = str(default)


@dataclass
class LLMConfig:
    """LLM配置"""
    # 主模型 (默认 Kimi)
    primary_provider: str = "kimi"
    primary_model: str = "kimi-k2-turbo-preview"
    # Kimi/Moonshot
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    # Anthropic Claude (备选)
    anthropic_api_key: str = ""
    fallback_provider: str = "anthropic"
    fallback_model: str = "claude-sonnet-4-6"
    # 轻量模型 (用于简单任务)
    fast_model: str = "moonshot-v1-32k"
    # OpenAI (第三备选)
    openai_api_key: str = ""
    # 成本控制
    daily_budget_usd: float = 50.0
    # 超时
    request_timeout: float = 30.0
    # 温度
    temperature: float = 0.0
    max_tokens: int = 4096

    def __post_init__(self):
        if not self.kimi_api_key:
            self.kimi_api_key = os.environ.get("KIMI_API_KEY", "")
        if not self.anthropic_api_key:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.openai_api_key:
            self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")


@dataclass
class CacheConfig:
    """缓存配置"""
    # Working Memory
    session_cache_size: int = 20
    global_hot_cache_size: int = 100
    session_timeout_seconds: int = 1800  # 30分钟
    # SQL结果缓存
    sql_cache_enabled: bool = True
    sql_cache_db_path: str = ""  # 默认 :memory:
    sql_cache_ttl_search: int = 3600       # 1小时
    sql_cache_ttl_stats: int = 21600       # 6小时
    sql_cache_ttl_ontology: int = 604800   # 7天
    # LLM响应缓存
    llm_cache_enabled: bool = True


@dataclass
class OntologyConfig:
    """本体配置"""
    cache_db_path: str = ""
    # 本体源文件目录
    source_dir: str = ""
    # 层级扩展默认深度
    default_expansion_depth: int = 2
    # 最大扩展深度
    max_expansion_depth: int = 4


@dataclass
class ServerConfig:
    """Web服务配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    websocket_heartbeat_seconds: int = 30


@dataclass
class AgentConfig:
    """Agent总配置"""
    # ReAct循环最大步数
    max_steps: int = 8
    # SQL候选数量
    sql_candidates: int = 3
    # SQL单候选超时 (秒)
    sql_candidate_timeout: float = 0.5
    # 默认结果限制
    default_limit: int = 20
    # 熔断器
    circuit_breaker_threshold: int = 3
    circuit_breaker_recovery_seconds: int = 60


@dataclass
class KnowledgeConfig:
    """Schema Knowledge 配置"""
    schema_path: str = "data/schema_knowledge.yaml"
    use_llm_parser: bool = True


@dataclass
class Settings:
    """全局配置入口"""
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    ontology: OntologyConfig = field(default_factory=OntologyConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)

    @classmethod
    def from_env(cls) -> Settings:
        """从环境变量加载配置"""
        return cls(
            database=DatabaseConfig(
                db_path=os.environ.get("SCEQTL_DB_PATH", ""),
            ),
            llm=LLMConfig(
                kimi_api_key=os.environ.get("KIMI_API_KEY", ""),
                anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                daily_budget_usd=float(os.environ.get("SCEQTL_DAILY_BUDGET", "50")),
            ),
            server=ServerConfig(
                host=os.environ.get("SCEQTL_HOST", "0.0.0.0"),
                port=int(os.environ.get("SCEQTL_PORT", "8000")),
                debug=os.environ.get("SCEQTL_DEBUG", "").lower() in ("1", "true"),
            ),
        )


# 全局单例
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
