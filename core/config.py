"""Configurazione centralizzata (variabili d'ambiente, prefisso nessuno).

Ogni valore ha un default che funziona in sviluppo locale; lo stack compose
li imposta esplicitamente. Nessun servizio a pagamento: le uniche destinazioni
di rete ammesse sono elencate in `core.net.ALLOWED_EGRESS_SUFFIXES` più i
domini delle fonti del catalogo.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

METHOD_VERSION = "0.1.0"
"""Versione della metodologia: compare accanto a ogni valore calcolato."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Open News"
    environment: str = "dev"
    secret_key: str = "dev-secret-change-me"

    database_url: str = "postgresql+asyncpg://opennews:opennews@localhost:5432/opennews"

    meili_url: str | None = None
    meili_key: str | None = None

    # "hashing": embedding deterministico n-gram, nessun download (default, qualità inferiore).
    # "e5": sentence-transformers intfloat/multilingual-e5-base (extra [ml]).
    embedding_backend: str = "hashing"
    embedding_dim: int = 768

    enable_llm: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Raccolta: identità e cortesia di rete (vedi docs/LEGAL.md).
    user_agent: str = (
        "OpenNewsBot/0.1 (+https://github.com/zano97/open_news; aggregatore open source; "
        "rispettiamo robots.txt; contatti nel repository)"
    )
    rate_limit_seconds: float = 2.0
    http_timeout_seconds: float = 20.0

    # Clustering
    cluster_window_hours: int = 72
    cluster_similarity_threshold: float = 0.83
    flash_min_sources: int = 5
    flash_window_hours: int = 2

    # Bias / segnali
    signal_window_days: int = 30
    blindspot_coverage_pct: float = 0.5

    # Annotazione (livello 4): soglie di pubblicazione
    annotation_min_articles: int = 50
    annotation_min_annotators: int = 3
    annotation_min_alpha: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
