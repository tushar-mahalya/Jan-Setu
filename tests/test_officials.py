from types import SimpleNamespace
from uuid import uuid4

from jan_setu.officials import OFFICIAL_TOKEN_AUDIENCE, _hash, _official_token
from jan_setu.repositories.officials import official_can_access
from jan_setu.config import Settings
import jwt


def _official(**overrides):
    values = {
        "id": uuid4(),
        "role": "triage_officer",
        "jurisdiction_id": "demo-ulb",
        "department_keys": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _grievance(**overrides):
    values = {"jurisdiction_id": "demo-ulb", "department_key": "public_works"}
    values.update(overrides)
    return SimpleNamespace(**values)


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
