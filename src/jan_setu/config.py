import json
import logging
import sys
from datetime import datetime, timezone
from functools import lru_cache
from typing import TextIO

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_RECORD_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"
    log_format: str = "text"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jan_setu"
    postgres_user: str = "jan_setu_app"
    postgres_password: SecretStr = SecretStr("jan_setu_dev_password")
    database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10

    whatsapp_verify_token: str = "dev_verify_token"
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_api_version: str = "v20.0"
    request_timeout_seconds: float = 10.0

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("whatsapp_app_secret", "whatsapp_access_token", "api_key", mode="before")
    @classmethod
    def empty_secret_to_none(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        return None if value == "" else value

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_to_none(cls, value: str | None) -> str | None:
        return None if value == "" else value

    @field_validator("whatsapp_phone_number_id", mode="before")
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

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)
