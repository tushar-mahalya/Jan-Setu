import hashlib
import hmac
from datetime import datetime, timezone
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from jan_setu.config import get_settings
from jan_setu.main import app
from jan_setu.repositories import store_incoming_messages, upsert_contact
from jan_setu.whatsapp import IncomingWhatsAppMessage, WhatsAppCloudClient, verify_meta_signature


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_webhook_verification_success(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_verify_token")
    with TestClient(app) as client:
        response = client.get(
            "/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test_verify_token",
                "hub.challenge": "challenge-value",
            },
        )

    assert response.status_code == 200
    assert response.text == "challenge-value"


def test_webhook_verification_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_verify_token")
    with TestClient(app) as client:
        response = client.get(
            "/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "challenge-value",
            },
        )

    assert response.status_code == 403


def test_meta_signature_verification_accepts_valid_signature():
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert verify_meta_signature(
        raw_body=body,
        signature_header=f"sha256={digest}",
        app_secret="secret",
    )


def test_upsert_contact_without_profile_name_preserves_existing_name():
    class Result:
        def scalar_one(self):
            return object()

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()

    async def run_upsert():
        await upsert_contact(session, wa_id="911234567890")

    anyio.run(run_upsert)

    compiled = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "profile_name = " not in compiled
    assert "updated_at = " in compiled


def test_whatsapp_client_uses_injected_http_client(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-number-id")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"messages": [{"id": "wamid.test"}]}

    class HTTPClient:
        requests = []

        async def post(self, url, *, headers, json):
            self.requests.append({"url": url, "headers": headers, "json": json})
            return Response()

    async def send_message():
        http_client = HTTPClient()
        client = WhatsAppCloudClient(get_settings(), http_client=http_client)
        response = await client.send_text(to="911234567890", body="Hello")
        return response, http_client.requests

    response, requests = anyio.run(send_message)

    assert response == {"messages": [{"id": "wamid.test"}]}
    assert len(requests) == 1
    assert requests[0]["headers"] == {"Authorization": "Bearer test-token"}


def test_webhook_post_requires_secret_outside_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    with TestClient(app) as client:
        response = client.post("/whatsapp/webhook", json={"entry": []})

    assert response.status_code == 503


def test_webhook_post_rejects_invalid_json(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/whatsapp/webhook",
            content=b"{",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400


def test_webhook_post_rejects_non_object_json(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/whatsapp/webhook", json=[])

    assert response.status_code == 400


def test_duplicate_incoming_message_skips_existing_message_lookup():
    class Contact:
        id = uuid4()

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def scalar_one_or_none(self):
            return self.value

    class Session:
        calls = 0

        async def execute(self, statement):
            self.calls += 1
            if self.calls == 1:
                return Result(Contact())
            if self.calls == 2:
                return Result(None)
            raise AssertionError("duplicate messages should not trigger an existing-row lookup")

    async def store_duplicate():
        session = Session()
        stored = await store_incoming_messages(
            session,
            [
                IncomingWhatsAppMessage(
                    wa_id="911234567890",
                    profile_name="Tushar",
                    meta_message_id="wamid.duplicate",
                    message_type="text",
                    text_body="hello",
                    raw_payload={"id": "wamid.duplicate"},
                    received_at=datetime.now(timezone.utc),
                )
            ],
        )
        return session.calls, stored

    calls, stored = anyio.run(store_duplicate)

    assert calls == 2
    assert stored[0].message is None
    assert stored[0].created is False
