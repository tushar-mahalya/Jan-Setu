from jan_setu.config import Settings


def test_settings_build_database_url_from_postgres_fields():
    settings = Settings(
        _env_file=None,
        database_url=None,
        postgres_host="postgres",
        postgres_port=5433,
        postgres_db="jan_setu",
        postgres_user="jan_setu_app",
        postgres_password="jan_setu_dev_password",
    )

    assert (
        settings.sqlalchemy_database_url
        == "postgresql+asyncpg://jan_setu_app:jan_setu_dev_password@postgres:5433/jan_setu"
    )


def test_settings_database_url_override_wins():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://override:secret@db.example.com:5432/prod",
        postgres_host="postgres",
        postgres_db="jan_setu",
        postgres_user="jan_setu_app",
        postgres_password="jan_setu_dev_password",
    )

    assert (
        settings.sqlalchemy_database_url
        == "postgresql+asyncpg://override:secret@db.example.com:5432/prod"
    )


def test_worker_and_reply_settings_have_defaults():
    settings = Settings(_env_file=None)

    assert settings.auto_reply_enabled is False
    assert settings.worker_poll_seconds == 2.0
    assert settings.worker_batch_size == 10


def test_local_default_jwt_secret_is_at_least_32_bytes():
    settings = Settings(_env_file=None)

    assert len(settings.jwt_secret.get_secret_value().encode("utf-8")) >= 32


def test_short_jwt_secret_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="at least 32 bytes"):
        Settings(_env_file=None, jwt_secret="too-short")


def test_staging_rejects_local_jwt_default():
    import pytest

    with pytest.raises(ValueError, match="local development default"):
        Settings(_env_file=None, environment="staging")


def test_test_environment_accepts_local_jwt_default():
    settings = Settings(_env_file=None, environment="test")

    assert settings.jwt_secret.get_secret_value() == "jan_setu_local_jwt_secret_only_change_me_32"
