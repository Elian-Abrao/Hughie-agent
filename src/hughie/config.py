from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HUGHIE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "postgresql://hughie:hughie@localhost:5432/hughie"
    google_api_key: str = ""
    bridge_url: str = "http://127.0.0.1:47831"
    bridge_model: str = "gpt-5.4"
    bridge_timeout: float = 120.0
    recursion_limit: int = 80
    context_history_limit: int = 12
    context_rag_top_k: int = 6
    context_timeout_seconds: float = 2.5

    consolidation_provider: str = "codex"
    consolidation_model: str = "gpt-5.4"
    consolidation_broker_timeout: float = 90.0
    consolidation_api_fallback_model: str = "gemini-2.0-flash"
    consolidation_batch_size: int = 10
    consolidation_context_turns: int = 3
    maintenance_interval_seconds: int = 86400

    local_machine_host: str = "tree-dev"
    local_machine_path_prefixes: list[str] = ["/home/elian/", "/dados/"]
    host_agent_url: str = ""
    host_agent_token: str = ""
    host_agent_timeout: float = 10.0

    system_prompt: str = Field(
        default="",
        description="System prompt override. Leave empty to load from prompts/system.md.",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
