from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


def _database_path() -> Path:
    configured = Path(os.getenv("KORA_DATABASE_PATH", "data/kora.db")).expanduser()
    return configured if configured.is_absolute() else (BACKEND_ROOT / configured).resolve()


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    database_path: Path = _database_path()
    allowed_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("KORA_ALLOWED_ORIGINS", "http://localhost:4173").split(",")
        if origin.strip()
    )
    manual_baseline_minutes: float = float(
        os.getenv("KORA_MANUAL_BASELINE_MINUTES", "12")
    )


settings = Settings()
