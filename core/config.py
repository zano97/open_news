"""Configurazione centralizzata (variabili d'ambiente, prefisso nessuno).

Ogni valore ha un default che funziona in sviluppo locale; lo stack compose
li imposta esplicitamente. Nessun servizio a pagamento: le uniche destinazioni
di rete ammesse sono elencate in `core.net.ALLOWED_EGRESS_SUFFIXES` più i
domini delle fonti del catalogo.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

METHOD_VERSION = "0.1.0"
"""Versione della metodologia: compare accanto a ogni valore calcolato."""

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


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
    # Il formato "Mozilla/5.0 (compatible; Nome; +url)" è la convenzione dei
    # crawler dichiarati (è quello di Googlebot): molti WAF rifiutano a
    # prescindere gli User-Agent fuori standard. L'identità resta esplicita.
    user_agent: str = (
        "Mozilla/5.0 (compatible; OpenNewsBot/0.1; +https://github.com/zano97/open_news)"
    )
    # Token con cui i siti possono indirizzarci in robots.txt
    # ("User-agent: OpenNewsBot"): è questo che usiamo per le regole.
    robots_user_agent: str = "OpenNewsBot"
    rate_limit_seconds: float = 2.0
    http_timeout_seconds: float = 20.0
    # Un feed che fallisce ripetutamente viene riprovato con calma, non a
    # ogni ciclo: dopo `feed_backoff_failures` errori consecutivi si attende
    # `feed_backoff_hours` prima del tentativo successivo.
    feed_backoff_failures: int = 3
    feed_backoff_hours: int = 6

    # Clustering. La soglia è calibrata sul backend attivo con
    # scripts/calibrate_threshold.py (set: data/seeds/calibration_pairs.yaml).
    # Con hashing-ngram-v2: 0.18 (pairwise: precisione 0.86 / richiamo 0.51
    # monolingua; il richiamo effettivo del clustering è più alto perché basta
    # che UNA variante superi la soglia). Il criterio è doppio (centroide E
    # membro più vicino) per evitare la concatenazione di eventi diversi.
    # Con backend e5 ricalibrare (valori tipici ~0.85) e impostare via env.
    cluster_window_hours: int = 72
    cluster_similarity_threshold: float = 0.18
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
