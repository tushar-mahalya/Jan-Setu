"""Reverse-OTP authentication over WhatsApp.

The business cannot message a user first (WhatsApp policy), so the usual "send
an SMS OTP" flow is inverted: the web app shows a short code and a wa.me deep
link, and the user sends that code TO the bot. The webhook driver
(``processing.py``) intercepts code-shaped inbound text before running the
FSM and calls ``verify_code_from_whatsapp`` here.

Codes and refresh tokens are both short-lived, high-entropy random values, not
passwords — sha256 is the correct, dependency-free tool for hashing them
(bcrypt/argon2 solve a different problem: slow-hashing low-entropy secrets).
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

import jwt
from fastapi import APIRouter, Depends, HTTPException, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.whatsapp import copy as msg
from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session, utc_now
from jan_setu.db.models import User
from jan_setu.repositories import (
    consume_verification,
    count_recent_verifications,
    create_phone_verification,
    create_refresh_token,
    find_active_refresh_token,
    find_pending_verification_by_code_hash,
    get_phone_verification,
    get_user,
    mark_verification_verified,
    revoke_refresh_token,
    upsert_user_for_verified_phone,
)
from jan_setu.schemas import (
    AuthStatusResponse,
    RefreshResponse,
    RequestCodeRequest,
    RequestCodeResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L ambiguity
CODE_LENGTH = 6
REFRESH_COOKIE_NAME = "refresh_token"


class RateLimitExceeded(Exception):
    pass


class InvalidRefreshToken(Exception):
    pass


def generate_code() -> str:
    return "JS-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def normalize_phone(phone: str) -> str:
    """Return the canonical Meta WhatsApp ID for Indian mobile numbers."""
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits


def wa_deep_link(settings: Settings, code: str) -> str:
    number = settings.public_wa_number or ""
    return f"https://wa.me/{number}?text={quote(code)}"


async def create_verification(
    session: AsyncSession, settings: Settings, *, phone: str
) -> tuple[str, str]:
    """Returns (verification_id, plaintext_code). Raises RateLimitExceeded if
    this phone has requested too many codes in the last hour."""
    phone = normalize_phone(phone)
    since = utc_now() - timedelta(hours=1)
    if (
        await count_recent_verifications(session, phone=phone, since=since)
        >= settings.verification_max_per_hour
    ):
        raise RateLimitExceeded(phone)

    code = generate_code()
    expires_at = utc_now() + timedelta(minutes=settings.verification_code_ttl_minutes)
    verification = await create_phone_verification(
        session, phone=phone, code_hash=hash_code(code), expires_at=expires_at
    )
    return str(verification.id), code


async def verify_code_from_whatsapp(
    session: AsyncSession, *, wa_id: str, contact_id: str, code_text: str
) -> str:
    """Called by the webhook driver when inbound text looks like a
    verification code. Returns the reply body to send back."""
    verification = await find_pending_verification_by_code_hash(
        session, code_hash=hash_code(code_text)
    )
    if verification is None or verification.phone != normalize_phone(wa_id):
        return msg.VERIFY_INVALID

    user = await upsert_user_for_verified_phone(
        session, phone=normalize_phone(wa_id), contact_id=contact_id
    )
    await mark_verification_verified(session, verification_id=verification.id, user_id=user.id)
    return msg.VERIFY_SUCCESS


def create_access_token(settings: Settings, *, user_id: str) -> str:
    now = utc_now()
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> str:
    """Returns the user id, or raises jwt.PyJWTError."""
    payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"])
    return payload["sub"]


async def issue_tokens(
    session: AsyncSession, settings: Settings, *, user_id: str
) -> tuple[str, str]:
    """Returns (access_token, raw_refresh_token)."""
    access_token = create_access_token(settings, user_id=user_id)
    raw_refresh = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(days=settings.refresh_token_days)
    await create_refresh_token(
        session, user_id=user_id, token_hash=hash_code(raw_refresh), expires_at=expires_at
    )
    return access_token, raw_refresh


async def rotate_refresh(
    session: AsyncSession, settings: Settings, *, raw_refresh_token: str
) -> tuple[str, str]:
    """Validate + revoke the old refresh token and issue a fresh pair. Raises
    InvalidRefreshToken if the token is missing/expired/revoked."""
    token_hash = hash_code(raw_refresh_token)
    row = await find_active_refresh_token(session, token_hash=token_hash)
    if row is None:
        raise InvalidRefreshToken
    await revoke_refresh_token(session, token_hash=token_hash)
    return await issue_tokens(session, settings, user_id=str(row.user_id))


def _cookie_kwargs(settings: Settings) -> dict:
    return {
        "httponly": True,
        "secure": settings.environment == "production",
        "samesite": "lax",
        "path": "/auth",
        "max_age": settings.refresh_token_days * 24 * 3600,
    }


@router.post("/request-code", response_model=RequestCodeResponse)
async def request_code(
    body: RequestCodeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RequestCodeResponse:
    try:
        verification_id, code = await create_verification(session, settings, phone=body.phone)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification requests for this number. Try again later.",
        ) from exc
    await session.commit()
    return RequestCodeResponse(
        verification_id=verification_id, code=code, wa_link=wa_deep_link(settings, code)
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    verification_id: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthStatusResponse:
    verification = await get_phone_verification(session, verification_id=verification_id)
    if verification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown verification_id")

    if verification.status == "pending":
        if verification.expires_at <= utc_now():
            return AuthStatusResponse(status="expired")
        return AuthStatusResponse(status="pending")

    if verification.status != "verified" or verification.user_id is None:
        return AuthStatusResponse(status="expired")

    if not await consume_verification(session, verification_id=verification.id):
        return AuthStatusResponse(status="expired")  # already claimed by another poll

    access_token, raw_refresh = await issue_tokens(
        session, settings, user_id=str(verification.user_id)
    )
    await session.commit()
    response.set_cookie(REFRESH_COOKIE_NAME, raw_refresh, **_cookie_kwargs(settings))
    return AuthStatusResponse(status="verified", access_token=access_token)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    refresh_token: Annotated[str | None, Header(alias="Cookie")] = None,
) -> RefreshResponse:
    raw_token = _extract_cookie(refresh_token)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )
    try:
        access_token, new_raw_refresh = await rotate_refresh(
            session, settings, raw_refresh_token=raw_token
        )
    except InvalidRefreshToken as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc
    await session.commit()
    response.set_cookie(REFRESH_COOKIE_NAME, new_raw_refresh, **_cookie_kwargs(settings))
    return RefreshResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    refresh_token: Annotated[str | None, Header(alias="Cookie")] = None,
) -> dict[str, str]:
    raw_token = _extract_cookie(refresh_token)
    if raw_token is not None:
        await revoke_refresh_token(session, token_hash=hash_code(raw_token))
        await session.commit()
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth")
    return {"status": "ok"}


def _extract_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == REFRESH_COOKIE_NAME:
            return value
    return None


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(settings, token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
        ) from exc
    user = await get_user(session, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user
