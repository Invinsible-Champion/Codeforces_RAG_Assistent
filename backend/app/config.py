from pydantic_settings import BaseSettings
from functools import lru_cache
import os
from pathlib import Path


def _find_env_file() -> str:
    """Find .env file — check CWD first, then project root (parent of backend/)."""
    cwd = Path.cwd()
    for candidate in [cwd / ".env", cwd.parent / ".env"]:
        if candidate.exists():
            return str(candidate)
    return ".env"


class Settings(BaseSettings):
    # Database — defaults to SQLite for zero-config dev
    # Switch to PostgreSQL by updating DATABASE_URL in .env
    database_url: str = "sqlite+aiosqlite:///./data/codeforces_rag.db"
    database_url_sync: str = "sqlite:///./data/codeforces_rag.db"

    # OpenAI
    openai_api_key: str = ""

    # FAISS
    faiss_index_path: str = "./data/faiss_index.bin"
    faiss_id_map_path: str = "./data/faiss_id_map.json"

    # Embedding
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # LLM
    llm_model: str = "gpt-4o-mini"

    # App
    cors_origins: str = "http://localhost:3000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000"

    # Scraping
    scrape_delay: float = 2.0  # seconds between requests
    max_problems_per_ingest: int = 100  # limit per ingestion run

    model_config = {"env_file": _find_env_file(), "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
