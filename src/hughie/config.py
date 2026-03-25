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
        "Seja conciso e direto. Responda em português.\n\n"
        "## Memória\n"
        "- Use save_brain_note para registrar preferências, fatos, projetos ou padrões do usuário.\n"
        "- Use search_brain_notes para lembrar informações sobre o usuário.\n"
        "- Use consolidate_memory quando o usuário compartilhar algo complexo e importante.\n\n"
        "## Sistema\n"
        "- Use shell_exec para executar comandos bash na máquina local.\n"
        "- Use read_file, write_file, list_dir, find_files para acessar o sistema de arquivos.\n"
        "- Sempre use essas ferramentas quando o usuário pedir para listar, ler, criar ou executar algo local.\n\n"
        "## Web\n"
        "- Use web_search para buscar informações atuais na internet.\n"
        "- Prefira buscar na web quando a pergunta exigir dados recentes ou específicos."
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
