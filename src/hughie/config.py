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

    flash_model: str = "gemini-2.5-flash-lite"
    consolidation_batch_size: int = 10
    consolidation_context_turns: int = 3

    system_prompt: str = (
        "Você é Hughie, agente pessoal de Elian. "
        "Você tem memória persistente e aprende sobre o usuário ao longo do tempo. "
        "Quando o usuário compartilhar preferências, fatos pessoais, projetos em andamento "
        "ou padrões de comportamento, use a ferramenta save_brain_note para registrar. "
        "Use search_brain_notes quando precisar lembrar algo específico. "
        "Seja conciso e direto nas respostas."
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
