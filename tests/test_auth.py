import re

import jwt
import pytest

from jan_setu.auth import (
    create_access_token,
    decode_access_token,
    generate_code,
    hash_code,
    normalize_phone,
    parse_login_approval_id,
    sanitize_browser_label,
    build_login_approval_id,
)
from jan_setu.config import Settings

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
