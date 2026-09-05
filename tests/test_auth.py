import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from jan_setu.auth import (
    InvalidRefreshToken,
    RateLimitExceeded,
    build_login_approval_id,
    create_access_token,
    create_verification,
    decode_access_token,
    generate_code,
    get_current_user,
    hash_code,
    issue_tokens,
    normalize_phone,
    parse_login_approval_id,
    rotate_refresh,
    sanitize_browser_label,
    verify_code_from_whatsapp,
)
from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session
from jan_setu.main import app
from jan_setu.whatsapp import copy as msg

_CODE_PATTERN = re.compile(r"^JS-[A-Z0-9]{6}$")
_AMBIGUOUS_CHARS = set("0O1IL")


def test_generate_code_matches_expected_shape():
    for _ in range(50):
        code = generate_code()
        assert _CODE_PATTERN.match(code)
        suffix = code.removeprefix("JS-")
        assert not _AMBIGUOUS_CHARS.intersection(suffix)


def test_hash_code_is_deterministic():
    assert hash_code("JS-AB12CD") == hash_code("JS-AB12CD")


def test_hash_code_is_case_and_whitespace_insensitive():
    assert hash_code("  js-ab12cd  ") == hash_code("JS-AB12CD")


def test_hash_code_differs_for_different_codes():
    assert hash_code("JS-AB12CD") != hash_code("JS-XY99ZZ")


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("7652064884", "917652064884"),
        ("+91 76520 64884", "917652064884"),
        ("917652064884", "917652064884"),
    ],
)
def test_normalize_phone_uses_meta_indian_whatsapp_id(raw_phone, expected):
    assert normalize_phone(raw_phone) == expected


def _settings(secret: str = "test-secret-key-for-jwt-tests-1234567890") -> Settings:
    return Settings(_env_file=None, jwt_secret=secret)


def test_create_and_decode_access_token_round_trips_user_id():
    settings = _settings()
    token = create_access_token(settings, user_id="user-123")

    assert decode_access_token(settings, token) == "user-123"


def test_decode_access_token_with_wrong_secret_raises():
    token = create_access_token(_settings("first-secret-1234567890123456789"), user_id="user-123")
    other_settings = _settings("second-secret-987654321098765432")

    with pytest.raises(jwt.PyJWTError):
        decode_access_token(other_settings, token)


def test_login_approval_button_round_trip():
    challenge_id = "11111111-1111-4111-8111-111111111111"
    verifier = "secure-verifier-value"
    reply_id = build_login_approval_id("login_yes", challenge_id, verifier)
    assert parse_login_approval_id(reply_id) == ("login_yes", challenge_id, verifier)


@pytest.mark.parametrize(
    "reply_id", [None, "yes", "login_maybe:id:verifier", "login_yes:short:tiny"]
)
def test_login_approval_parser_rejects_malformed_ids(reply_id):
    assert parse_login_approval_id(reply_id) is None


def test_browser_label_is_bounded_and_sanitized():
    label = sanitize_browser_label("  Chrome\n on   macOS  " + "x" * 200)
    assert label.startswith("Chrome on macOS")
    assert "\n" not in label
    assert len(label) <= 128


def _run(coro):
    import anyio

    return anyio.run(lambda: coro)


PRODUCTION_JWT_SECRET = "test-production-jwt-secret-at-least-32-bytes"


@pytest.fixture(autouse=True)
def clear_settings_cache_and_overrides():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()


# ===================================================================
# create_verification / verify_code_from_whatsapp (direct unit tests)
# ===================================================================


class TestCreateVerification:
    def test_rate_limit_exceeded_raises(self):
        settings = _settings()
        session = AsyncMock()
        with patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=99)):
            with pytest.raises(RateLimitExceeded):
                _run(create_verification(session, settings, phone="7652064884"))

    def test_success_returns_id_and_code(self):
        settings = _settings()
        session = AsyncMock()
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            verification_id, code = _run(create_verification(session, settings, phone="7652064884"))
        assert verification_id == str(verification.id)
        assert code.startswith("JS-")


class TestVerifyCodeFromWhatsapp:
    def test_unknown_code_returns_invalid_message(self):
        session = AsyncMock()
        with patch(
            "jan_setu.auth.find_pending_verification_by_code_hash",
            AsyncMock(return_value=None),
        ):
            reply = _run(
                verify_code_from_whatsapp(
                    session, wa_id="917652064884", contact_id="c-1", code_text="JS-ABCDEF"
                )
            )
        assert reply == msg.VERIFY_INVALID

    def test_phone_mismatch_returns_invalid_message(self):
        session = AsyncMock()
        verification = SimpleNamespace(phone="919999999999")
        with patch(
            "jan_setu.auth.find_pending_verification_by_code_hash",
            AsyncMock(return_value=verification),
        ):
            reply = _run(
                verify_code_from_whatsapp(
                    session, wa_id="917652064884", contact_id="c-1", code_text="JS-ABCDEF"
                )
            )
        assert reply == msg.VERIFY_INVALID

    def test_success_returns_success_message(self):
        session = AsyncMock()
        verification = SimpleNamespace(phone="917652064884", id=uuid.uuid4())
        user = SimpleNamespace(id=uuid.uuid4())
        with (
            patch(
                "jan_setu.auth.find_pending_verification_by_code_hash",
                AsyncMock(return_value=verification),
            ),
            patch("jan_setu.auth.upsert_user_for_verified_phone", AsyncMock(return_value=user)),
            patch("jan_setu.auth.mark_verification_verified", AsyncMock()) as mock_mark,
        ):
            reply = _run(
                verify_code_from_whatsapp(
                    session, wa_id="917652064884", contact_id="c-1", code_text="JS-ABCDEF"
                )
            )
        assert reply == msg.VERIFY_SUCCESS
        mock_mark.assert_awaited_once()


# ===================================================================
# issue_tokens / rotate_refresh (direct unit tests)
# ===================================================================


class TestIssueAndRotateTokens:
    def test_issue_tokens_creates_refresh_token_row(self):
        settings = _settings()
        session = AsyncMock()
        with patch("jan_setu.auth.create_refresh_token", AsyncMock()) as mock_create:
            access_token, raw_refresh = _run(issue_tokens(session, settings, user_id="user-1"))
        assert decode_access_token(settings, access_token) == "user-1"
        assert len(raw_refresh) > 20
        mock_create.assert_awaited_once()

    def test_rotate_refresh_with_unknown_token_raises(self):
        settings = _settings()
        session = AsyncMock()
        with patch("jan_setu.auth.find_active_refresh_token", AsyncMock(return_value=None)):
            with pytest.raises(InvalidRefreshToken):
                _run(rotate_refresh(session, settings, raw_refresh_token="nope"))

    def test_rotate_refresh_revokes_old_and_issues_new(self):
        settings = _settings()
        session = AsyncMock()
        row = SimpleNamespace(user_id="user-1")
        with (
            patch("jan_setu.auth.find_active_refresh_token", AsyncMock(return_value=row)),
            patch("jan_setu.auth.revoke_refresh_token", AsyncMock()) as mock_revoke,
            patch("jan_setu.auth.create_refresh_token", AsyncMock()),
        ):
            access_token, raw_refresh = _run(
                rotate_refresh(session, settings, raw_refresh_token="old-token")
            )
        assert decode_access_token(settings, access_token) == "user-1"
        mock_revoke.assert_awaited_once()


# ===================================================================
# get_current_user (direct unit tests)
# ===================================================================


class TestGetCurrentUser:
    def test_missing_authorization_header_raises_401(self):
        settings = _settings()
        session = AsyncMock()
        with pytest.raises(HTTPException) as excinfo:
            _run(get_current_user(session, settings, authorization=None))
        assert excinfo.value.status_code == 401

    def test_non_bearer_authorization_raises_401(self):
        settings = _settings()
        session = AsyncMock()
        with pytest.raises(HTTPException) as excinfo:
            _run(get_current_user(session, settings, authorization="Basic xyz"))
        assert excinfo.value.status_code == 401

    def test_malformed_token_raises_401(self):
        settings = _settings()
        session = AsyncMock()
        with pytest.raises(HTTPException) as excinfo:
            _run(get_current_user(session, settings, authorization="Bearer not-a-jwt"))
        assert excinfo.value.status_code == 401

    def test_expired_token_raises_401(self):
        settings = _settings()
        session = AsyncMock()
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        token = jwt.encode(
            {"sub": "u-1", "iat": int(now.timestamp()), "exp": int(now.timestamp()) + 60},
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as excinfo:
            _run(get_current_user(session, settings, authorization=f"Bearer {token}"))
        assert excinfo.value.status_code == 401

    def test_unknown_user_raises_401(self):
        settings = _settings()
        session = AsyncMock()
        token = create_access_token(settings, user_id="ghost-user")
        with patch("jan_setu.auth.get_user", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as excinfo:
                _run(get_current_user(session, settings, authorization=f"Bearer {token}"))
        assert excinfo.value.status_code == 401

    def test_valid_token_returns_user(self):
        settings = _settings()
        session = AsyncMock()
        token = create_access_token(settings, user_id="user-1")
        user = SimpleNamespace(id="user-1")
        with patch("jan_setu.auth.get_user", AsyncMock(return_value=user)):
            result = _run(get_current_user(session, settings, authorization=f"Bearer {token}"))
        assert result is user


# ===================================================================
# /auth/request-code
# ===================================================================


class TestRequestCodeEndpoint:
    def test_missing_phone_returns_422(self):
        with TestClient(app) as client:
            r = client.post("/auth/request-code", json={})
        assert r.status_code == 422

    def test_short_phone_returns_422(self):
        with TestClient(app) as client:
            r = client.post("/auth/request-code", json={"phone": "12"})
        assert r.status_code == 422

    def test_too_many_attempts_returns_429(self):
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=5)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/request-code", json={"phone": "7652064884"})
        assert r.status_code == 429

    def test_unlinked_phone_uses_reverse_code_path(self):
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=None)),
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/request-code", json={"phone": "7652064884"})
        assert r.status_code == 200
        assert r.json()["method"] == "reverse_code"

    def test_linked_phone_outside_service_window_uses_reverse_code_path(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch("jan_setu.auth.latest_inbound_at", AsyncMock(return_value=None)),
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/request-code", json={"phone": "7652064884"})
        assert r.status_code == 200
        assert r.json()["method"] == "reverse_code"

    def test_linked_phone_inside_window_without_nonce_uses_reverse_code_path(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch(
                "jan_setu.auth.latest_inbound_at",
                AsyncMock(return_value=datetime.now(timezone.utc)),
            ),
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/request-code", json={"phone": "7652064884"})
        assert r.status_code == 200
        assert r.json()["method"] == "reverse_code"

    def test_linked_phone_inside_window_with_nonce_sends_approval_and_succeeds(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        challenge = SimpleNamespace(
            id=uuid.uuid4(),
            requested_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        outbound_row = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch(
                "jan_setu.auth.latest_inbound_at",
                AsyncMock(return_value=datetime.now(timezone.utc)),
            ),
            patch("jan_setu.auth.create_login_approval", AsyncMock(return_value=challenge)),
            patch("jan_setu.auth.store_outgoing_pending", AsyncMock(return_value=outbound_row)),
            patch("jan_setu.auth.attach_approval_outbound", AsyncMock()),
            patch("jan_setu.auth.send_pending", AsyncMock(return_value="sent")),
            patch("jan_setu.auth.mark_login_approval_fallback", AsyncMock()) as mock_fallback,
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post(
                    "/auth/request-code",
                    json={
                        "phone": "7652064884",
                        "browser_nonce": "n" * 32,
                        "browser_label": "Chrome on macOS",
                    },
                )
        assert r.status_code == 200
        body = r.json()
        assert body["method"] == "whatsapp_approval"
        mock_fallback.assert_not_called()

    def test_approval_send_failure_falls_back_to_reverse_code(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        challenge = SimpleNamespace(
            id=uuid.uuid4(),
            requested_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        outbound_row = SimpleNamespace(id=uuid.uuid4())
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch(
                "jan_setu.auth.latest_inbound_at",
                AsyncMock(return_value=datetime.now(timezone.utc)),
            ),
            patch("jan_setu.auth.create_login_approval", AsyncMock(return_value=challenge)),
            patch("jan_setu.auth.store_outgoing_pending", AsyncMock(return_value=outbound_row)),
            patch("jan_setu.auth.attach_approval_outbound", AsyncMock()),
            patch("jan_setu.auth.send_pending", AsyncMock(return_value="failed")),
            patch("jan_setu.auth.mark_login_approval_fallback", AsyncMock()) as mock_fallback,
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post(
                    "/auth/request-code",
                    json={"phone": "7652064884", "browser_nonce": "n" * 32},
                )
        assert r.status_code == 200
        assert r.json()["method"] == "reverse_code"
        mock_fallback.assert_awaited_once()

    def test_approval_no_outbound_row_falls_back_to_reverse_code(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        challenge = SimpleNamespace(
            id=uuid.uuid4(),
            requested_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        verification = SimpleNamespace(id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch(
                "jan_setu.auth.latest_inbound_at",
                AsyncMock(return_value=datetime.now(timezone.utc)),
            ),
            patch("jan_setu.auth.create_login_approval", AsyncMock(return_value=challenge)),
            patch("jan_setu.auth.store_outgoing_pending", AsyncMock(return_value=None)),
            patch("jan_setu.auth.mark_login_approval_fallback", AsyncMock()) as mock_fallback,
            patch(
                "jan_setu.auth.create_phone_verification",
                AsyncMock(return_value=verification),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post(
                    "/auth/request-code",
                    json={"phone": "7652064884", "browser_nonce": "n" * 32},
                )
        assert r.status_code == 200
        assert r.json()["method"] == "reverse_code"
        mock_fallback.assert_awaited_once()

    def test_reverse_code_rate_limit_inside_helper_returns_429(self):
        user = SimpleNamespace(contact_id=uuid.uuid4())
        with (
            patch("jan_setu.auth.count_recent_verifications", AsyncMock(return_value=0)),
            patch("jan_setu.auth.count_recent_login_approvals", AsyncMock(return_value=0)),
            patch("jan_setu.auth.get_linked_user_by_phone", AsyncMock(return_value=user)),
            patch(
                "jan_setu.auth.latest_inbound_at", AsyncMock(return_value=None)
            ),  # outside window -> reverse code path
            patch(
                "jan_setu.auth.create_verification",
                AsyncMock(side_effect=RateLimitExceeded("917652064884")),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/request-code", json={"phone": "7652064884"})
        assert r.status_code == 429


# ===================================================================
# /auth/status
# ===================================================================


class TestAuthStatusEndpoint:
    def test_unknown_id_returns_404(self):
        with patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=None)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.status_code == 404

    def test_pending_and_not_expired_returns_pending(self):
        verification = SimpleNamespace(
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        with patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=verification)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_pending_and_expired_returns_expired(self):
        verification = SimpleNamespace(
            status="pending",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        with patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=verification)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.status_code == 200
        assert r.json()["status"] == "expired"

    def test_verified_without_user_id_returns_expired(self):
        verification = SimpleNamespace(status="verified", user_id=None)
        with patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=verification)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.json()["status"] == "expired"

    def test_already_claimed_verification_returns_expired(self):
        verification = SimpleNamespace(status="verified", user_id=uuid.uuid4(), id=uuid.uuid4())
        with (
            patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=verification)),
            patch("jan_setu.auth.consume_verification", AsyncMock(return_value=False)),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.json()["status"] == "expired"

    def test_verified_success_issues_tokens_and_sets_cookie(self):
        verification = SimpleNamespace(status="verified", user_id=uuid.uuid4(), id=uuid.uuid4())
        with (
            patch("jan_setu.auth.get_phone_verification", AsyncMock(return_value=verification)),
            patch("jan_setu.auth.consume_verification", AsyncMock(return_value=True)),
            patch("jan_setu.auth.create_refresh_token", AsyncMock()),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.get("/auth/status", params={"verification_id": str(uuid.uuid4())})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "verified"
        assert body["access_token"]
        assert "refresh_token" in r.headers.get("set-cookie", "")


# ===================================================================
# /auth/approval-status
# ===================================================================


class TestApprovalStatusEndpoint:
    def _body(self, verification_id=None):
        return {
            "verification_id": str(verification_id or uuid.uuid4()),
            "browser_nonce": "n" * 32,
        }

    def test_missing_body_returns_422(self):
        with TestClient(app) as client:
            r = client.post("/auth/approval-status", json={})
        assert r.status_code == 422

    def test_unknown_challenge_returns_expired(self):
        with patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=None)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.json()["status"] == "expired"

    def test_expired_pending_challenge_returns_expired(self):
        challenge = SimpleNamespace(
            status="pending", expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        with patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.json()["status"] == "expired"

    def test_denied_challenge_returns_denied(self):
        challenge = SimpleNamespace(
            status="denied", expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        with patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.json()["status"] == "denied"

    def test_still_pending_challenge_returns_pending(self):
        challenge = SimpleNamespace(
            status="pending", expires_at=datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        with patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.json()["status"] == "pending"

    def test_approved_but_already_consumed_returns_expired(self):
        challenge = SimpleNamespace(
            status="approved",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            id=uuid.uuid4(),
        )
        with (
            patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=challenge)),
            patch("jan_setu.auth.consume_login_approval", AsyncMock(return_value=None)),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.json()["status"] == "expired"

    def test_approved_success_issues_tokens_and_sets_cookie(self):
        challenge = SimpleNamespace(
            status="approved",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            id=uuid.uuid4(),
        )
        with (
            patch("jan_setu.auth.get_login_approval", AsyncMock(return_value=challenge)),
            patch("jan_setu.auth.consume_login_approval", AsyncMock(return_value=uuid.uuid4())),
            patch("jan_setu.auth.create_refresh_token", AsyncMock()),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/approval-status", json=self._body())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "verified"
        assert body["access_token"]
        assert "refresh_token" in r.headers.get("set-cookie", "")


# ===================================================================
# /auth/refresh, /auth/logout
# ===================================================================


class TestRefreshEndpoint:
    def test_without_cookie_returns_401(self):
        with TestClient(app) as client:
            r = client.post("/auth/refresh")
        assert r.status_code == 401

    def test_invalid_refresh_token_returns_401(self):
        with patch("jan_setu.auth.find_active_refresh_token", AsyncMock(return_value=None)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/refresh", headers={"Cookie": "refresh_token=stale-token"})
        assert r.status_code == 401

    def test_valid_refresh_token_rotates_and_returns_new_access_token(self):
        row = SimpleNamespace(user_id="user-1")
        with (
            patch("jan_setu.auth.find_active_refresh_token", AsyncMock(return_value=row)),
            patch("jan_setu.auth.revoke_refresh_token", AsyncMock()),
            patch("jan_setu.auth.create_refresh_token", AsyncMock()),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/refresh", headers={"Cookie": "refresh_token=good-token"})
        assert r.status_code == 200
        assert r.json()["access_token"]
        assert "refresh_token" in r.headers.get("set-cookie", "")


class TestLogoutEndpoint:
    def test_without_cookie_returns_ok(self):
        with TestClient(app) as client:
            r = client.post("/auth/logout")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_with_cookie_revokes_token(self):
        with patch("jan_setu.auth.revoke_refresh_token", AsyncMock()) as mock_revoke:
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/auth/logout", headers={"Cookie": "refresh_token=some-token"})
        assert r.status_code == 200
        mock_revoke.assert_awaited_once()
