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


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


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
    auth_mode: str = os.getenv("KORA_AUTH_MODE", "demo").strip().lower()
    default_tenant_id: str = os.getenv("KORA_DEFAULT_TENANT_ID", "tenant-demo")
    webhook_token: str | None = _optional("KORA_WEBHOOK_TOKEN")
    channel_mode: str = os.getenv("KORA_CHANNEL_MODE", "demo").strip().lower()
    postmark_server_token: str | None = _optional("POSTMARK_SERVER_TOKEN")
    postmark_from_email: str | None = _optional("POSTMARK_FROM_EMAIL")
    postmark_webhook_username: str | None = _optional("POSTMARK_WEBHOOK_USERNAME")
    postmark_webhook_password: str | None = _optional("POSTMARK_WEBHOOK_PASSWORD")
    whatsapp_access_token: str | None = _optional("WHATSAPP_ACCESS_TOKEN")
    whatsapp_phone_number_id: str | None = _optional("WHATSAPP_PHONE_NUMBER_ID")
    whatsapp_verify_token: str | None = _optional("WHATSAPP_VERIFY_TOKEN")
    whatsapp_app_secret: str | None = _optional("WHATSAPP_APP_SECRET")
    whatsapp_graph_version: str = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0")
    paystack_secret_key: str | None = _optional("PAYSTACK_SECRET_KEY")
    paystack_base_url: str = os.getenv(
        "PAYSTACK_BASE_URL", "https://api.paystack.co"
    ).rstrip("/")
    worker_poll_seconds: float = float(os.getenv("KORA_WORKER_POLL_SECONDS", "1.5"))
    worker_enabled: bool = os.getenv("KORA_WORKER_ENABLED", "true").lower() == "true"


settings = Settings()
