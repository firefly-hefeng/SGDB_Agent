"""SCeQTL-Agent V3 配置管理

配置加载优先级: 环境变量 > .env 文件 > config/config.yaml > 默认值
"""

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
            db_dir = project_root / "database_development" / "unified_db"
            # 新版优先: human_metadata.db (Phase 16+, 人源单库),
            # 旧版兜底: unified_metadata.db
            for fname in ("human_metadata.db", "unified_metadata.db"):
                cand = db_dir / fname
                if cand.exists():
                    self.db_path = str(cand)
                    break


@dataclass
class LLMConfig:
    """LLM配置"""
    # 主模型 (默认 Kimi). Phase 27: default to the *turbo* variant — k2.6 is a
    # thinking model (~90-150s/call) unusable for an interactive portal; turbo
    # returns equivalent-quality parses in ~1-2s.
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
    default_limit: int = 100
    # 熔断器
    circuit_breaker_threshold: int = 3
    circuit_breaker_recovery_seconds: int = 60
    # Parser mode for the live server. "auto" historically resolved to the
    # ReasoningParser (CoT) when an LLM was present — but that parser makes a
    # long multi-step generation (~2-3 min per query observed in Phase 27) and
    # was *superseded* in quality by V1QueryParser. Phase 40+: default to
    # "cascade" — the eval-grounded LLM-on-demand policy (rule-first, escalate
    # to the V1 LLM parser only on the calibrated confidence/structural gate).
    # On the cr_target gold (kimi-k2.6, clean) the cascade scores 92.4 vs
    # always-LLM "v1" 70.7 and always-rule 86.1, while calling the LLM on only
    # ~30% of queries — so the interactive portal is both more accurate and much
    # faster (fewer 30-150s k2.6 calls). Override via SCEQTL_PARSER_MODE
    # (rule | v1 | reasoning | cascade | auto).
    parser_mode: str = "cascade"


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
        """从 YAML + 环境变量加载配置 (env 覆盖 yaml)"""
        project_root = Path(__file__).parent.parent

        # 1. Load .env file if exists
        env_file = project_root / ".env"
        if env_file.exists():
            _load_dotenv(env_file)

        # 2. Load config.yaml as base
        yaml_cfg: dict = {}
        config_path = project_root / "config" / "config.yaml"
        if config_path.exists():
            try:
                import yaml
                with open(config_path) as f:
                    yaml_cfg = yaml.safe_load(f) or {}
            except Exception:
                pass

        llm_yaml = yaml_cfg.get("llm", {})
        db_yaml = yaml_cfg.get("database", {})
        knowledge_yaml = yaml_cfg.get("knowledge", {})

        # 3. Env overrides YAML
        return cls(
            database=DatabaseConfig(
                db_path=os.environ.get("SCEQTL_DB_PATH", db_yaml.get("db_path", "")),
                pool_size=int(db_yaml.get("pool_size", 5)),
            ),
            llm=LLMConfig(
                kimi_api_key=os.environ.get("KIMI_API_KEY", llm_yaml.get("kimi_api_key", "")),
                primary_model=os.environ.get("KIMI_MODEL", llm_yaml.get("primary_model", "kimi-k2-turbo-preview")),
                kimi_base_url=llm_yaml.get("kimi_base_url", "https://api.moonshot.cn/v1"),
                anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                daily_budget_usd=float(os.environ.get("SCEQTL_DAILY_BUDGET", "50")),
                temperature=float(llm_yaml.get("temperature", 0.0)),
                max_tokens=int(llm_yaml.get("max_tokens", 4096)),
                request_timeout=float(llm_yaml.get("request_timeout", 30.0)),
            ),
            knowledge=KnowledgeConfig(
                schema_path=knowledge_yaml.get("schema_path", "data/schema_knowledge.yaml"),
            ),
            server=ServerConfig(
                host=os.environ.get("SCEQTL_HOST", "0.0.0.0"),
                port=int(os.environ.get("SCEQTL_PORT", "8000")),
                debug=os.environ.get("SCEQTL_DEBUG", "").lower() in ("1", "true"),
            ),
            agent=AgentConfig(
                parser_mode=os.environ.get("SCEQTL_PARSER_MODE", "cascade"),
            ),
        )


# 全局单例
_settings: Settings | None = None


def _load_dotenv(path: Path) -> None:
    """Load .env file into os.environ (simple implementation, no dependency)."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:  # env vars take precedence
                    os.environ[key] = value
    except Exception:
        pass


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
