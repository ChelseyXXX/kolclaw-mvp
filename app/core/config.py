from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "kolclaw_demo.sqlite3"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"


def get_env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.lower() in {"1", "true", "yes", "on"}


def get_llm_api_key() -> str:
    return os.getenv("LLM_API_KEY", "")


def get_llm_base_url() -> str:
    return os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
