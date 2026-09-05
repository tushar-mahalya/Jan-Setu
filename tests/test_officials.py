import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session
from jan_setu.main import app
from jan_setu.officials import (
    OFFICIAL_TOKEN_AUDIENCE,
    _hash,
    _official_token,
    require_official,
)
from jan_setu.repositories.officials import official_can_access


def _official(**overrides):
    values = {
        "id": uuid4(),
        "role": "triage_officer",
        "jurisdiction_id": "demo-ulb",
        "department_keys": [],
        "active": True,
        "name": "Test Official",
        "email": "official@example.gov",
        "last_login_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _grievance(**overrides):
    values = {
        "id": uuid4(),
        "human_id": "JS-20260101-00001",
        "status": "awaiting_confirmation",
        "review_status": "pending_official",
        "photo_path": None,
        "category_id": "pothole_surface_damage",
        "category": "pothole_surface_damage",
        "department_key": "public_works",
        "jurisdiction_id": "demo-ulb",
        "priority": "normal",
        "safety_level": "none",
        "asset_scope": "public",
        "disposition": "municipal_ticket",
        "confidence": 0.9,
        "location_address": "123 Main St",
        "issue_text": "Pothole on the road",
        "structured_facts": {},
        "routing_snapshot": {},
        "flags": [],
        "image_match_status": "none",
        "created_at": datetime.now(timezone.utc),
        "state_version": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()


def test_official_token_has_separate_audience_and_scope():
    settings = Settings()
    official = _official(role="supervisor")
    token = _official_token(settings, official)
    payload = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=OFFICIAL_TOKEN_AUDIENCE,
    )
    assert payload["sub"] == str(official.id)
    assert payload["role"] == "supervisor"
    assert payload["jurisdiction"] == "demo-ulb"


def test_official_hash_is_case_and_whitespace_insensitive():
    assert _hash(" Official@Example.Gov ") == _hash("official@example.gov")


def test_official_scope_rejects_cross_jurisdiction_access():
    assert not official_can_access(_official(), _grievance(jurisdiction_id="other-ulb"))


def test_department_officer_is_limited_to_assigned_departments():
    official = _official(role="department_officer", department_keys=["sanitation"])
    assert official_can_access(official, _grievance(department_key="sanitation"))
    assert not official_can_access(official, _grievance(department_key="public_works"))


def test_supervisor_can_access_any_department_in_own_jurisdiction():
    official = _official(role="supervisor")
    assert official_can_access(official, _grievance(department_key="animal_welfare"))


# ===================================================================
# require_official dependency: token validation edge cases
# ===================================================================


def _run(coro):
    import anyio

    return anyio.run(lambda: coro)


class TestRequireOfficial:
    def test_missing_bearer_header_raises_401(self):
        from fastapi import HTTPException

        request = SimpleNamespace(headers={})
        settings = _settings()
        with pytest.raises(HTTPException) as excinfo:
            _run(require_official(request, AsyncMock(), settings))
        assert excinfo.value.status_code == 401

    def test_malformed_token_raises_401(self):
        from fastapi import HTTPException

        request = SimpleNamespace(headers={"Authorization": "Bearer not-a-jwt"})
        settings = _settings()
        with pytest.raises(HTTPException) as excinfo:
            _run(require_official(request, AsyncMock(), settings))
        assert excinfo.value.status_code == 401

    def test_wrong_audience_token_raises_401(self):
        from fastapi import HTTPException

        settings = _settings()
        now = datetime.now(timezone.utc)
        # Citizen-audience token (no "aud" claim) must not authenticate an official.
        token = jwt.encode(
            {"sub": "u-1", "iat": int(now.timestamp()), "exp": int(now.timestamp()) + 3600},
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        with pytest.raises(HTTPException) as excinfo:
            _run(require_official(request, AsyncMock(), settings))
        assert excinfo.value.status_code == 401

    def test_expired_token_raises_401(self):
        from fastapi import HTTPException

        settings = _settings()
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        token = jwt.encode(
            {
                "sub": "o-1",
                "aud": OFFICIAL_TOKEN_AUDIENCE,
                "role": "supervisor",
                "jurisdiction": "demo-ulb",
                "iat": int(now.timestamp()),
                "exp": int(now.timestamp()) + 60,
            },
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        with pytest.raises(HTTPException) as excinfo:
            _run(require_official(request, AsyncMock(), settings))
        assert excinfo.value.status_code == 401

    def test_unknown_official_raises_401(self):
        from fastapi import HTTPException

        settings = _settings()
        token = _official_token(settings, _official())
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        session = AsyncMock()
        with patch("jan_setu.officials.get_official", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as excinfo:
                _run(require_official(request, session, settings))
        assert excinfo.value.status_code == 401

    def test_inactive_official_raises_401(self):
        from fastapi import HTTPException

        settings = _settings()
        official = _official(active=False)
        token = _official_token(settings, official)
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        session = AsyncMock()
        with patch("jan_setu.officials.get_official", AsyncMock(return_value=official)):
            with pytest.raises(HTTPException) as excinfo:
                _run(require_official(request, session, settings))
        assert excinfo.value.status_code == 401

    def test_role_not_in_allowed_roles_raises_401(self):
        from fastapi import HTTPException

        settings = _settings()
        official = _official(role="ghost_role")
        token = _official_token(settings, official)
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        session = AsyncMock()
        with patch("jan_setu.officials.get_official", AsyncMock(return_value=official)):
            with pytest.raises(HTTPException) as excinfo:
                _run(require_official(request, session, settings))
        assert excinfo.value.status_code == 401

    def test_valid_token_returns_official(self):
        settings = _settings()
        official = _official(role="supervisor")
        token = _official_token(settings, official)
        request = SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
        session = AsyncMock()
        with patch("jan_setu.officials.get_official", AsyncMock(return_value=official)):
            result = _run(require_official(request, session, settings))
        assert result is official


# ===================================================================
# /api/official/auth/request-code
# ===================================================================


class TestRequestOfficialCode:
    def test_request_official_code_missing_email_returns_422(self):
        with TestClient(app) as client:
            r = client.post("/api/official/auth/request-code", json={})
        assert r.status_code == 422

    def test_request_official_code_invalid_email_returns_422(self):
        with TestClient(app) as client:
            r = client.post(
                "/api/official/auth/request-code",
                json={"email": "not-an-email"},
            )
        assert r.status_code == 422

    def test_unknown_email_returns_generic_response_and_sends_no_email(self):
        challenge = SimpleNamespace(id=uuid4())
        with (
            patch("jan_setu.officials.get_official_by_email", AsyncMock(return_value=None)),
            patch(
                "jan_setu.officials.create_official_challenge",
                AsyncMock(return_value=challenge),
            ),
            patch(
                "jan_setu.officials._recent_official_challenge_count",
                AsyncMock(return_value=0),
            ),
            patch("jan_setu.officials._send_official_code_email") as mock_send,
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post(
                    "/api/official/auth/request-code",
                    json={"email": "unknown@example.gov"},
                )
        assert r.status_code == 200
        assert set(r.json()) == {"status", "challenge_id"}
        mock_send.assert_not_called()

    def test_known_email_sends_email_and_never_returns_the_code(self):
        official = _official(email="known@example.gov")
        challenge = SimpleNamespace(id=uuid4())
        dev_settings = _settings(environment="development")
        with (
            patch("jan_setu.officials.get_official_by_email", AsyncMock(return_value=official)),
            patch(
                "jan_setu.officials.create_official_challenge",
                AsyncMock(return_value=challenge),
            ),
            patch(
                "jan_setu.officials._recent_official_challenge_count",
                AsyncMock(return_value=0),
            ),
            patch("jan_setu.officials._send_official_code_email") as mock_send,
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            app.dependency_overrides[get_settings] = lambda: dev_settings
            with TestClient(app) as client:
                r = client.post(
                    "/api/official/auth/request-code",
                    json={"email": "known@example.gov"},
                )
        assert r.status_code == 200
        assert set(r.json()) == {"status", "challenge_id"}
        mock_send.assert_called_once()

    def test_production_response_never_contains_the_code(self):
        official = _official(email="known@example.gov")
        challenge = SimpleNamespace(id=uuid4())
        prod_settings = _settings(
            environment="production",
            jwt_secret="production-secret-at-least-32-bytes-long",
        )
        with (
            patch("jan_setu.officials.get_official_by_email", AsyncMock(return_value=official)),
            patch(
                "jan_setu.officials.create_official_challenge",
                AsyncMock(return_value=challenge),
            ),
            patch(
                "jan_setu.officials._recent_official_challenge_count",
                AsyncMock(return_value=0),
            ),
            patch("jan_setu.officials._send_official_code_email") as mock_send,
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            app.dependency_overrides[get_settings] = lambda: prod_settings
            with TestClient(app) as client:
                r = client.post(
                    "/api/official/auth/request-code",
                    json={"email": "known@example.gov"},
                )
        assert r.status_code == 200
        assert set(r.json()) == {"status", "challenge_id"}
        mock_send.assert_called_once()

    def test_rate_limited_email_returns_429_without_creating_challenge(self):
        with (
            patch("jan_setu.officials.get_official_by_email", AsyncMock()) as mock_get,
            patch("jan_setu.officials.create_official_challenge", AsyncMock()) as mock_create,
            patch(
                "jan_setu.officials._recent_official_challenge_count",
                AsyncMock(return_value=5),
            ),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post(
                    "/api/official/auth/request-code",
                    json={"email": "known@example.gov"},
                )
        assert r.status_code == 429
        mock_get.assert_not_called()
        mock_create.assert_not_called()

    def test_send_official_code_email_swallows_smtp_errors(self):
        from jan_setu.officials import _send_official_code_email

        settings = _settings()
        with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            # Must not raise.
            _send_official_code_email(settings, "someone@example.gov", "123456", "official-id")


# ===================================================================
# /api/official/auth/verify
# ===================================================================


class TestVerifyOfficialCode:
    def _body(self, challenge_id=None, code="123456"):
        return {"challenge_id": str(challenge_id or uuid4()), "code": code}

    def _live_challenge(self, code="123456", official_user_id=None):
        return SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash(code),
            official_user_id=official_user_id or uuid4(),
        )

    def test_dev_login_code_is_accepted_in_development(self):
        official = _official()
        challenge = self._live_challenge(official_user_id=official.id)
        settings = _settings(environment="development", official_dev_login_code="000000")
        with (
            patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)),
            patch("jan_setu.officials.get_official", AsyncMock(return_value=official)),
            patch("jan_setu.officials.add_official_audit", AsyncMock()),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            app.dependency_overrides[get_settings] = lambda: settings
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="000000"))
        assert r.status_code == 200
        assert r.json()["access_token"]

    def test_dev_login_code_still_burns_an_attempt(self):
        # Otherwise a leaked demo code could be retried without limit.
        official = _official()
        challenge = self._live_challenge(official_user_id=official.id)
        settings = _settings(environment="development", official_dev_login_code="000000")
        with (
            patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)),
            patch("jan_setu.officials.get_official", AsyncMock(return_value=official)),
            patch("jan_setu.officials.add_official_audit", AsyncMock()),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            app.dependency_overrides[get_settings] = lambda: settings
            with TestClient(app) as client:
                client.post("/api/official/auth/verify", json=self._body(code="000000"))
        assert challenge.attempt_count == 1

    def test_dev_login_code_does_not_bypass_an_unknown_official(self):
        # The escape hatch replaces the code check only, never the account check.
        challenge = self._live_challenge()
        challenge.official_user_id = None
        settings = _settings(environment="development", official_dev_login_code="000000")
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            app.dependency_overrides[get_settings] = lambda: settings
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="000000"))
        assert r.status_code == 401

    def test_settings_refuse_to_load_dev_login_code_in_production(self):
        with pytest.raises(ValidationError):
            _settings(
                environment="production",
                jwt_secret="production-secret-at-least-32-bytes-long",
                official_dev_login_code="000000",
            )

    def test_unknown_challenge_returns_401(self):
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=None)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body())
        assert r.status_code == 401

    def test_already_consumed_challenge_returns_401(self):
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=uuid4(),
        )
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body())
        assert r.status_code == 401

    def test_expired_challenge_returns_401(self):
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=uuid4(),
        )
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body())
        assert r.status_code == 401

    def test_too_many_attempts_returns_401(self):
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=5,
            code_hash=_hash("123456"),
            official_user_id=uuid4(),
        )
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body())
        assert r.status_code == 401

    def test_wrong_code_increments_attempt_count_and_returns_401(self):
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=uuid4(),
        )
        session = AsyncMock()
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: session
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="000000"))
        assert r.status_code == 401
        assert challenge.attempt_count == 1
        session.commit.assert_awaited()

    def test_challenge_without_official_user_id_returns_401(self):
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=None,
        )
        with patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="123456"))
        assert r.status_code == 401

    def test_official_no_longer_active_returns_401(self):
        official_id = uuid4()
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=official_id,
        )
        with (
            patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)),
            patch("jan_setu.officials.get_official", AsyncMock(return_value=None)),
        ):
            app.dependency_overrides[get_session] = lambda: AsyncMock()
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="123456"))
        assert r.status_code == 401

    def test_successful_verification_returns_session_and_records_audit(self):
        official = _official()
        challenge = SimpleNamespace(
            id=uuid4(),
            consumed_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_count=0,
            code_hash=_hash("123456"),
            official_user_id=official.id,
        )
        session = AsyncMock()
        with (
            patch("jan_setu.officials.get_official_challenge", AsyncMock(return_value=challenge)),
            patch("jan_setu.officials.get_official", AsyncMock(return_value=official)),
            patch("jan_setu.officials.add_official_audit", AsyncMock()) as mock_audit,
        ):
            app.dependency_overrides[get_session] = lambda: session
            with TestClient(app) as client:
                r = client.post("/api/official/auth/verify", json=self._body(code="123456"))
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["official"]["id"] == str(official.id)
        assert challenge.consumed_at is not None
        mock_audit.assert_awaited_once()
        session.commit.assert_awaited()


# ===================================================================
# /api/official/queue, /grievances/{id}, /grievances/{id}/actions, /metrics
# ===================================================================


class TestOfficialQueue:
    def test_official_queue_unauthorized(self):
        with TestClient(app) as client:
            r = client.get("/api/official/queue")
        assert r.status_code == 401

    def test_official_queue_bad_token(self):
        with TestClient(app) as client:
            r = client.get(
                "/api/official/queue", headers={"Authorization": "Bearer invalid.jwt.token"}
            )
        assert r.status_code == 401

    def test_official_queue_returns_scoped_items(self):
        official = _official()
        rows = [_grievance(), _grievance(category_id=None, category=None)]
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.list_scoped_grievances", AsyncMock(return_value=rows)):
            with TestClient(app) as client:
                r = client.get("/api/official/queue")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert body[0]["id"] == str(rows[0].id)


class TestOfficialGrievanceDetail:
    def test_official_grievance_detail_unauthorized(self):
        gid = str(uuid.uuid4())
        with TestClient(app) as client:
            r = client.get(f"/api/official/grievances/{gid}")
        assert r.status_code == 401

    def test_grievance_not_found_returns_404(self):
        official = _official()
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.get_grievance", AsyncMock(return_value=None)):
            with TestClient(app) as client:
                r = client.get(f"/api/official/grievances/{uuid4()}")
        assert r.status_code == 404

    def test_grievance_out_of_jurisdiction_returns_404(self):
        official = _official()
        grievance = _grievance(jurisdiction_id="other-ulb")
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)):
            with TestClient(app) as client:
                r = client.get(f"/api/official/grievances/{grievance.id}")
        assert r.status_code == 404

    def test_grievance_detail_success_records_audit(self):
        official = _official()
        grievance = _grievance()
        app.dependency_overrides[require_official] = lambda: official
        app.dependency_overrides[get_session] = lambda: AsyncMock()
        with (
            patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)),
            patch("jan_setu.officials.add_official_audit", AsyncMock()) as mock_audit,
        ):
            with TestClient(app) as client:
                r = client.get(f"/api/official/grievances/{grievance.id}")
        assert r.status_code == 200
        assert r.json()["id"] == str(grievance.id)
        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == "view"


class TestOfficialAction:
    def _body(self, **overrides):
        body = {"action": "approve", "reason": "Looks valid and verified."}
        body.update(overrides)
        return body

    def test_official_action_unauthorized(self):
        gid = str(uuid.uuid4())
        with TestClient(app) as client:
            r = client.post(f"/api/official/grievances/{gid}/actions", json=self._body())
        assert r.status_code == 401

    def test_auditor_role_forbidden(self):
        official = _official(role="auditor")
        app.dependency_overrides[require_official] = lambda: official
        with TestClient(app) as client:
            r = client.post(f"/api/official/grievances/{uuid4()}/actions", json=self._body())
        assert r.status_code == 403

    def test_action_grievance_not_found_returns_404(self):
        official = _official()
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.get_grievance", AsyncMock(return_value=None)):
            with TestClient(app) as client:
                r = client.post(f"/api/official/grievances/{uuid4()}/actions", json=self._body())
        assert r.status_code == 404

    def test_action_invalid_category_returns_422(self):
        official = _official()
        grievance = _grievance(category_id=None, category=None)
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)):
            with TestClient(app) as client:
                r = client.post(
                    f"/api/official/grievances/{grievance.id}/actions",
                    json=self._body(category_id="not-a-real-category"),
                )
        assert r.status_code == 422

    @pytest.mark.parametrize(
        ("action", "expected_review_status"),
        [
            ("approve", "approved"),
            ("correct", "approved"),
            ("redirect", "redirected"),
            ("reject", "rejected"),
            ("request_clarification", "awaiting_citizen"),
        ],
    )
    def test_action_success_maps_to_review_status(self, action, expected_review_status):
        official = _official()
        grievance = _grievance()
        session = AsyncMock()
        app.dependency_overrides[require_official] = lambda: official
        app.dependency_overrides[get_session] = lambda: session
        with (
            patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)),
            patch("jan_setu.officials.set_grievance_fields", AsyncMock()) as mock_set,
            patch("jan_setu.officials.add_official_audit", AsyncMock()) as mock_audit,
        ):
            with TestClient(app) as client:
                r = client.post(
                    f"/api/official/grievances/{grievance.id}/actions",
                    json=self._body(action=action),
                )
        assert r.status_code == 200
        assert mock_set.await_args.kwargs["review_status"] == expected_review_status
        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == action
        session.commit.assert_awaited()

    def test_redirect_action_forces_redirect_disposition(self):
        official = _official()
        grievance = _grievance()
        app.dependency_overrides[require_official] = lambda: official
        app.dependency_overrides[get_session] = lambda: AsyncMock()
        with (
            patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)),
            patch("jan_setu.officials.set_grievance_fields", AsyncMock()) as mock_set,
            patch("jan_setu.officials.add_official_audit", AsyncMock()),
        ):
            with TestClient(app) as client:
                r = client.post(
                    f"/api/official/grievances/{grievance.id}/actions",
                    json=self._body(action="redirect"),
                )
        assert r.status_code == 200
        assert mock_set.await_args.kwargs["disposition"] == "redirect"

    def test_action_explicit_department_key_overrides_route(self):
        official = _official()
        grievance = _grievance()
        app.dependency_overrides[require_official] = lambda: official
        app.dependency_overrides[get_session] = lambda: AsyncMock()
        with (
            patch("jan_setu.officials.get_grievance", AsyncMock(return_value=grievance)),
            patch("jan_setu.officials.set_grievance_fields", AsyncMock()) as mock_set,
            patch("jan_setu.officials.add_official_audit", AsyncMock()),
        ):
            with TestClient(app) as client:
                r = client.post(
                    f"/api/official/grievances/{grievance.id}/actions",
                    json=self._body(department_key="sanitation"),
                )
        assert r.status_code == 200
        assert mock_set.await_args.kwargs["department_key"] == "sanitation"


class TestOfficialMetrics:
    def test_official_metrics_unauthorized(self):
        with TestClient(app) as client:
            r = client.get("/api/official/metrics")
        assert r.status_code == 401

    def test_official_metrics_computes_counts(self):
        official = _official()
        rows = [
            _grievance(review_status="pending_official", safety_level="immediate", flags=[]),
            _grievance(
                review_status="approved",
                safety_level="none",
                flags=["classification_failed"],
            ),
            _grievance(review_status="approved", safety_level="none", status="dispatch_failed"),
        ]
        app.dependency_overrides[require_official] = lambda: official
        with patch("jan_setu.officials.list_scoped_grievances", AsyncMock(return_value=rows)):
            with TestClient(app) as client:
                r = client.get("/api/official/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["total_visible"] == 3
        assert body["pending_review"] == 1
        assert body["immediate_safety"] == 1
        assert body["failed_ai"] == 1
        assert body["failed_dispatch"] == 1
