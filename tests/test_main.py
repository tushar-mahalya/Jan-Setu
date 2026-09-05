"""Tests for jan_setu.main:run() — specifically the reload/environment gate.

Autoreload must never be on when this is the process actually serving
traffic (see main.py), so this pins reload=True only in development/test.
"""

from unittest.mock import patch

from jan_setu.config import get_settings
from jan_setu.main import run

PRODUCTION_JWT_SECRET = "test-production-jwt-secret-at-least-32-bytes"


def test_run_enables_reload_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    try:
        with patch("uvicorn.run") as mock_run:
            run()
        assert mock_run.call_args.kwargs["reload"] is True
    finally:
        get_settings.cache_clear()


def test_run_disables_reload_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", PRODUCTION_JWT_SECRET)
    get_settings.cache_clear()
    try:
        with patch("uvicorn.run") as mock_run:
            run()
        assert mock_run.call_args.kwargs["reload"] is False
    finally:
        get_settings.cache_clear()
