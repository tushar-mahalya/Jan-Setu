import io
import json
import logging

from fastapi.testclient import TestClient

from jan_setu.config import NOISY_LIBRARY_LOGGERS, configure_logging, get_settings
from jan_setu.main import app


def test_configure_logging_can_emit_json_with_extra_fields():
    root_logger = logging.getLogger()
    old_handlers = root_logger.handlers[:]
    old_level = root_logger.level
    stream = io.StringIO()

    try:
        configure_logging("INFO", log_format="json", stream=stream)
        logging.getLogger("jan_setu.test").info(
            "request_completed",
            extra={"request_id": "req-123", "status_code": 200},
        )
    finally:
        root_logger.handlers = old_handlers
        root_logger.setLevel(old_level)

    log = json.loads(stream.getvalue())
    assert log["level"] == "INFO"
    assert log["logger"] == "jan_setu.test"
    assert log["message"] == "request_completed"
    assert log["request_id"] == "req-123"
    assert log["status_code"] == 200


def test_http_requests_get_request_id_header_and_log(caplog):
    get_settings.cache_clear()

    with caplog.at_level(logging.INFO, logger="jan_setu.app"):
        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "req-123"})

    assert response.headers["X-Request-ID"] == "req-123"
    assert any(
        record.message == "request_completed"
        and record.request_id == "req-123"
        and record.status_code == 200
        for record in caplog.records
    )


def test_noisy_library_loggers_are_quieted_at_info():
    # fpdf2 subsets the packaged Noto fonts on every PDF and fontTools narrates
    # each table -- ~400 INFO lines per complaint, which buried the worker log.
    configure_logging("INFO", stream=io.StringIO())
    for name in NOISY_LIBRARY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_noisy_library_loggers_are_restored_at_debug():
    # Must be idempotent in both directions: an earlier INFO run cannot leave a
    # later DEBUG run silenced, or font debugging becomes impossible.
    configure_logging("INFO", stream=io.StringIO())
    configure_logging("DEBUG", stream=io.StringIO())
    for name in NOISY_LIBRARY_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET


def test_text_format_renders_extra_fields():
    # LOG_FORMAT defaults to "text"; a plain logging.Formatter renders only
    # asctime/level/name/message, so every extra={...} in the codebase would be
    # silently dropped in the default config.
    stream = io.StringIO()
    root_logger = logging.getLogger()
    old_handlers = root_logger.handlers[:]
    try:
        configure_logging("INFO", log_format="text", stream=stream)
        logging.getLogger("jan_setu.test").info(
            "dispatch_sent",
            extra={"grievance_id": "g-1", "duration_ms": 42.1, "address": None},
        )
    finally:
        root_logger.handlers = old_handlers

    line = stream.getvalue()
    assert "dispatch_sent" in line
    assert "grievance_id=g-1" in line
    assert "duration_ms=42.1" in line
    assert "address" not in line  # None-valued fields stay out of the line
    # super().format() stamps message/asctime onto the record; they must not echo
    assert "message=" not in line
    assert "asctime=" not in line
