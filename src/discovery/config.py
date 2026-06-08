"""Configuration management for the discovery sub-agent.

This is the namespaced configuration block for the cross-database
discovery component. Component-specific knobs are prefixed ``DISCOVERY_*``
so they cannot collide with the main agent's LLM and DB settings. The
**shared secrets** (``KIMI_API_KEY``, ``ANTHROPIC_API_KEY``,
``OPENAI_API_KEY``, ``NCBI_API_KEY``) are read from their *un-prefixed*
names — matching the rest of agent_v3 — via per-field ``validation_alias``
(which overrides ``env_prefix`` for those fields). They ALSO accept the
``DISCOVERY_*`` form as a secondary override.

History / WHY this is explicit now: before Phase 39, ``env_prefix`` was
applied to every field including ``kimi_api_key``, so pydantic looked for
``DISCOVERY_KIMI_API_KEY`` (never set) and the un-prefixed ``KIMI_API_KEY``
in ``.env`` was silently ignored. The alias validator below never fired,
``openai_api_key`` stayed ``None``, and the whole discovery agent ran
**LLM-less** (rule-only intent parse + no synthesis) without any signal.
Use :meth:`llm_active` / :meth:`effective_llm_summary` to assert the live
state so that failure mode cannot recur unnoticed.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscoverySettings(BaseSettings):
    """Discovery sub-agent settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="DISCOVERY_",
    )

    # ── Shared secrets ──
    # validation_alias overrides env_prefix: these read the UN-prefixed name
    # first (shared with the rest of agent_v3), then the DISCOVERY_ form.
    ncbi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NCBI_API_KEY", "DISCOVERY_NCBI_API_KEY"),
    )
    ncbi_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NCBI_EMAIL", "DISCOVERY_NCBI_EMAIL"),
    )
    ncbi_rate_limit: int = 3
    ncbi_rate_limit_with_key: int = 10
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "DISCOVERY_ANTHROPIC_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "DISCOVERY_OPENAI_API_KEY"),
    )
    # ``KIMI_API_KEY`` is the agent_v3 alias for an OpenAI-compatible LLM.
    # We honour it as the fallback for openai_api_key when the explicit
    # value is unset, so users only have to configure one key.
    kimi_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("KIMI_API_KEY", "DISCOVERY_KIMI_API_KEY"),
    )

    # LLM (prefixed DISCOVERY_LLM_* so they don't collide with the main
    # agent's LLM settings). The discovery agent deliberately uses a FAST
    # non-thinking model (moonshot-v1-8k) for intent parsing + synthesis:
    # the live cross-DB fan-out already costs 7-17s, and a thinking model
    # (kimi-k2.6, ~20-40s/call) would dominate latency. k2.6 remains
    # available as a quality-vs-latency ablation by setting DISCOVERY_LLM_MODEL.
    llm_provider: str = "openai"
    llm_model: str = "moonshot-v1-8k"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 512
    llm_base_url: str | None = "https://api.moonshot.cn/v1"

    # Timeouts (prefixed DISCOVERY_*).
    adapter_timeout: float = 30.0
    http_timeout: float = 30.0
    global_timeout: float = 45.0
    llm_timeout: float = 20.0

    # Results.
    max_results_per_source: int = 20
    cellxgene_cache_ttl_seconds: int = 3600

    # Request-level discovery cache (set ttl=0 to disable).
    discover_cache_ttl_seconds: int = 600
    discover_cache_max_size: int = 256

    # Re-ranker backend. Default is ``none`` (source-native order) on the
    # EVIDENCE that re-ranking does not beat it: on the expert-corrected GT
    # v2.1 (Phase 40), A8 intent_feature vs A4 no-rerank gave Hit@10 Δ+0.000,
    # MRR Δ-0.044, nDCG Δ+0.001, Wilcoxon p=0.97 — no gain, slight MRR
    # regression, +~2s latency; the upstream EXP-20260512-02 ablation found the
    # same. Per the project's "ship a change only if Δ>0 and p<0.05" rule the
    # reranker is not justified as a default. ``intent_feature`` (deterministic
    # feature scorer), ``lexical`` (legacy), and ``llm`` remain available for
    # ablation and can be re-enabled via SCEQTL/DISCOVERY env if a future
    # cross-source rank-fusion (RRF / learned cross-encoder) proves Δ>0.
    rerank_backend: str = "none"

    # Synonym expansion.
    synonym_expansion_enabled: bool = True

    # Concurrency guard for in-process discovery requests (FastAPI route
    # uses an asyncio.Semaphore initialised from this).
    concurrency_limit: int = 8

    # Log level for the discovery sub-package only.
    log_level: str = "info"

    @model_validator(mode="after")
    def _resolve_kimi_alias(self) -> "DiscoverySettings":
        """Treat KIMI_API_KEY as an alias for OPENAI_API_KEY.

        The main agent_v3 deployment uses Kimi as its OpenAI-compatible
        LLM. The discovery sub-agent was written against ``openai_api_key``;
        we let it transparently see the Kimi key by aliasing here so users
        don't have to set two env vars to the same value.
        """
        if not self.openai_api_key and self.kimi_api_key:
            self.openai_api_key = self.kimi_api_key
        return self

    # ── Live-state introspection (guards against silent LLM-off regressions) ──
    @property
    def llm_active(self) -> bool:
        """True iff an LLM intent-parse/synthesis path is actually reachable.

        When False, the discovery agent runs rule-only (fallback intent
        parser + programmatic synthesis). Callers/tests/eval should assert
        this is True in any run that is meant to exercise the LLM.
        """
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return bool(self.openai_api_key)

    def effective_llm_summary(self) -> dict[str, object]:
        """Compact, secret-free description of the resolved LLM/rerank state.

        Surfaced at app startup (logs) and on ``/discover/health`` so an
        operator can see at a glance whether the agent is running with its
        full capability set or degraded to rules.
        """
        return {
            "llm_active": self.llm_active,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model if self.llm_active else None,
            "llm_base_url": self.llm_base_url if self.llm_active else None,
            "rerank_backend": self.rerank_backend,
            "ncbi_key": bool(self.ncbi_api_key),
            "synonym_expansion": self.synonym_expansion_enabled,
        }


# Backwards-compatible alias for code copied verbatim from the upstream
# api-routing-agent (it referred to ``Settings``).
Settings = DiscoverySettings


@lru_cache
def get_settings() -> DiscoverySettings:
    return DiscoverySettings()
