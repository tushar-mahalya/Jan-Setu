import io
import json
import logging

from fastapi.testclient import TestClient

from jan_setu.config import configure_logging, get_settings
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
