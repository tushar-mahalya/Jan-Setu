"""Shared pytest setup.

The suite must never read the developer's local, untracked `.env`. Settings
declares `env_file=".env"`, so without this every test that builds a Settings
object silently inherits whatever happens to be on the machine -- which makes
results depend on an untracked file and differ between a laptop and CI.
"""

import pytest

from jan_setu.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_settings_from_local_dotenv(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
