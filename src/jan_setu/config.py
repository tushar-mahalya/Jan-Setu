import json
import logging
import sys
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal, TextIO

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jan_setu.logctx import RequestIdFilter

LOG_RECORD_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

Environment = Literal["development", "test", "staging", "production"]

DEV_POSTGRES_PASSWORD = "jan_setu_dev_password"
DEV_VERIFY_TOKEN = "dev_verify_token"
DEV_JWT_SECRET = "dev_jwt_secret_change_me"


class Settings(BaseSettings):
    environment: Environment = "development"
    log_level: str = "INFO"
    log_format: str = "text"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jan_setu"
    postgres_user: str = "jan_setu_app"
    postgres_password: SecretStr = SecretStr(DEV_POSTGRES_PASSWORD)
    database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10

    whatsapp_verify_token: str = DEV_VERIFY_TOKEN
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_api_version: str = "v25.0"
    request_timeout_seconds: float = 10.0
    # Digits-only WhatsApp Business number (no +) for wa.me/<number> deep links.
    # Distinct from whatsapp_phone_number_id, which is Meta's internal Graph id.
    public_wa_number: str | None = None

    api_key: SecretStr | None = None

    auto_reply_enabled: bool = False
    worker_poll_seconds: float = 2.0
    worker_batch_size: int = 10

    # Reverse geocoding. The PUBLIC Nominatim endpoint is dev-only: its usage
    # policy caps at 1 req/s and forbids app/bulk traffic, so production must
    # point nominatim_base_url at a self-hosted Nominatim/Photon or a paid
    # provider. https://operations.osmfoundation.org/policies/nominatim/
    geocoder_provider: str = "nominatim"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "JanSetu/0.1 (+https://github.com/tushar-mahalya/Jan-Setu)"
    geocoder_timeout_seconds: float = 3.0
    geocoder_min_interval_seconds: float = 1.0
    geocoder_language: str = "hi,en"

    # Conversation engine. service_window_hours is Meta's 24h customer-service
    # window (free-form sends only inside it); conversation_ttl_hours is how long
    # an unfinished chat may be resumed before it is expired and restarted.
    conversation_ttl_hours: int = 168
    service_window_hours: int = 24

    # Speech-to-text (Sarvam saaras:v3, mode=translate -> English transcripts).
    sarvam_api_key: SecretStr | None = None
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_model: str = "saaras:v3"
    sarvam_min_interval_seconds: float = 1.0
    sarvam_timeout_seconds: float = 30.0

    # LLM classification (OpenRouter). Free models rotate, so the chain is
    # config-driven; classify.py falls through it and degrades gracefully.
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = (
        "google/gemma-4-26b-a4b-it:free,"
        "openai/gpt-oss-120b:free,"
        "nvidia/nemotron-3-nano-30b-a3b:free"
    )
    openrouter_min_interval_seconds: float = 3.0
    openrouter_timeout_seconds: float = 30.0

    # Dedup window for non-priority complaints; priority categories skip it.
    dedup_window_hours: int = 24
    dedup_radius_m: float = 300.0
    image_recheck_cap: int = 2

    # Department dispatch. The Protocol in dispatchers.py is the swap seam for
    # real municipal APIs later; both impls here are demo-grade.
    dispatcher: Literal["mock_api", "smtp"] = "mock_api"
    mock_api_base_url: str = "http://localhost:8000"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "no-reply@jan-setu.local"

    # File uploads (voice clips, photos, generated PDFs).
    upload_dir: str = "./data/uploads"
    max_audio_bytes: int = 10 * 1024 * 1024
    max_image_bytes: int = 5 * 1024 * 1024

    # Auth: reverse OTP over WhatsApp + JWT access / rotating refresh cookie.
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    verification_code_ttl_minutes: int = 10
    verification_max_per_hour: int = 3

    # Web frontend.
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator(
        "whatsapp_app_secret",
        "whatsapp_access_token",
        "api_key",
        "sarvam_api_key",
        "openrouter_api_key",
        mode="before",
    )
    @classmethod
    def empty_secret_to_none(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        return None if value == "" else value

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_to_none(cls, value: str | None) -> str | None:
        return None if value == "" else value

    @field_validator("whatsapp_phone_number_id", "public_wa_number", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        return None if value == "" else value

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def openrouter_model_chain(self) -> list[str]:
        return [model.strip() for model in self.openrouter_models.split(",") if model.strip()]

    def insecure_production_defaults(self) -> list[str]:
        """Dev-default secrets still active. Checked once at startup and logged
        as a warning (not fail-fast: the per-request checks in api.py already
        gate the endpoints that actually need these secrets)."""
        if self.environment != "production":
            return []
        issues = []
        if self.postgres_password.get_secret_value() == DEV_POSTGRES_PASSWORD:
            issues.append("POSTGRES_PASSWORD is the dev default")
        if self.whatsapp_verify_token == DEV_VERIFY_TOKEN:
            issues.append("WHATSAPP_VERIFY_TOKEN is the dev default")
        if self.jwt_secret.get_secret_value() == DEV_JWT_SECRET:
            issues.append("JWT_SECRET is the dev default")
        if self.whatsapp_app_secret is None:
            issues.append("WHATSAPP_APP_SECRET is not set")
        if self.api_key is None:
            issues.append("API_KEY is not set")
        return issues


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in LOG_RECORD_RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(
    level: str,
    *,
    log_format: str = "text",
    stream: TextIO | None = None,
) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(stream or sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)
