from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


class Settings(BaseModel):
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None
    llm_api_key: str | None = os.getenv("LLM_API_KEY") or None
    model: str | None = os.getenv("MODEL") or None
    mock_api_base_url: str = (
        os.getenv("MOCK_API_BASE_URL")
        or os.getenv("ALDENTE_API_BASE_URL")
        or "https://aldente.yellowtest.it"
    ).rstrip("/")
    mock_api_token: str | None = (
        os.getenv("MOCK_API_TOKEN") or os.getenv("ALDENTE_API_KEY") or None
    )
    public_base_url: str = os.getenv(
        "PUBLIC_BASE_URL", "http://localhost:8000"
    ).rstrip("/")
    request_timeout_seconds: float = 5.0
    llm_timeout_seconds: float = 5.0
    ask_timeout_seconds: float = 28.0
    cache_ttl_seconds: int = 900
    cache_max_entries: int = 512

    @property
    def has_mock_api(self) -> bool:
        return bool(self.mock_api_token)

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
