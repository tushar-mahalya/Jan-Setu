import hashlib
import hmac

from fastapi.testclient import TestClient

from jan_setu.config import get_settings
from jan_setu.main import app
from jan_setu.whatsapp import verify_meta_signature


def test_webhook_verification_success(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test_verify_token")
    get_settings.cache_clear()
    client = TestClient(app)

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
    get_settings.cache_clear()
    client = TestClient(app)

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