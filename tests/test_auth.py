import re

import jwt
import pytest

from jan_setu.auth import create_access_token, decode_access_token, generate_code, hash_code
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
