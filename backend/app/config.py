from __future__ import annotations

import os
from dataclasses import dataclass, field
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


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _mapping(name: str) -> dict[str, str]:
    """Parse ``key:value,key:value`` pairs, e.g. channel address to tenant."""
    pairs: dict[str, str] = {}
    for item in os.getenv(name, "").split(","):
        key, separator, value = item.strip().rpartition(":")
        if separator and key.strip() and value.strip():
            pairs[key.strip().lower()] = value.strip()
    return pairs


_AUTH_MODE = os.getenv("KORA_AUTH_MODE", "demo").strip().lower()


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
    manual_baseline_minutes: float = _float("KORA_MANUAL_BASELINE_MINUTES", 12)
    auth_mode: str = _AUTH_MODE
    default_tenant_id: str = os.getenv("KORA_DEFAULT_TENANT_ID", "tenant-demo")
    # Synthetic demo data is only seeded where it cannot mix with real customers.
    seed_demo_data: bool = _bool("KORA_SEED_DEMO_DATA", _AUTH_MODE == "demo")
    webhook_token: str | None = _optional("KORA_WEBHOOK_TOKEN")
    # Unsigned webhooks are only for local development and automated tests.
    allow_unsigned_webhooks: bool = _bool("KORA_ALLOW_UNSIGNED_WEBHOOKS", False)
    channel_mode: str = os.getenv("KORA_CHANNEL_MODE", "demo").strip().lower()
    # Inbound address or WhatsApp phone-number ID -> tenant. Unmapped traffic
    # falls back to the default tenant.
    email_tenants: dict[str, str] = field(default_factory=lambda: _mapping("KORA_EMAIL_TENANTS"))
    whatsapp_tenants: dict[str, str] = field(default_factory=lambda: _mapping("KORA_WHATSAPP_TENANTS"))
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
    worker_poll_seconds: float = _float("KORA_WORKER_POLL_SECONDS", 1.5)
    worker_enabled: bool = _bool("KORA_WORKER_ENABLED", True)
    # A job left "running" longer than this (e.g. after a redeploy) is retried.
    job_lease_seconds: int = _int("KORA_JOB_LEASE_SECONDS", 300)
    # Abuse protection. Per-client limits apply in every mode; the daily AI cap
    # applies only to the public demo, where every visitor is a manager.
    trust_proxy_headers: bool = _bool("KORA_TRUST_PROXY_HEADERS", False)
    ai_requests_per_minute: int = _int("KORA_AI_REQUESTS_PER_MINUTE", 10)
    write_requests_per_minute: int = _int("KORA_WRITE_REQUESTS_PER_MINUTE", 60)
    demo_daily_ai_limit: int = _int("KORA_DEMO_DAILY_AI_LIMIT", 300)
    demo_proof_case_limit: int = _int("KORA_DEMO_PROOF_CASE_LIMIT", 12)
    proof_concurrency: int = _int("KORA_PROOF_CONCURRENCY", 4)

    @property
    def delivery_ready(self) -> bool:
        """Whether at least one live customer channel can send a response."""
        return self.channel_mode == "live" and (
            bool(self.postmark_server_token and self.postmark_from_email)
            or bool(self.whatsapp_access_token and self.whatsapp_phone_number_id)
        )


DEFAULT_AUTOMATION = {
    "enabled": False,
    "auto_approve_threshold": 95,
    "mandatory_review_threshold": 70,
}


settings = Settings()
