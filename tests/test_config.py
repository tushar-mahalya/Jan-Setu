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

    assert settings.sqlalchemy_database_url == "postgresql+asyncpg://override:secret@db.example.com:5432/prod"
