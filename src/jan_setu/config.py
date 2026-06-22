import logging
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://chatbot:chatbot@localhost:5432/chatbot"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    whatsapp_verify_token: str = "dev_verify_token"
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_graph_api_version: str = "v20.0"
    request_timeout_seconds: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("whatsapp_app_secret", "whatsapp_access_token", mode="before")
    @classmethod
    def empty_secret_to_none(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        return None if value == "" else value

    @field_validator("whatsapp_phone_number_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )