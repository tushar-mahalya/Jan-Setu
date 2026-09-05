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
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.whatsapp import copy as msg
from jan_setu.config import Settings, get_settings
from jan_setu.db import AsyncSessionLocal, get_session, utc_now
from jan_setu.db.models import User
from jan_setu.repositories import (
    attach_approval_outbound,
    consume_login_approval,
    consume_verification,
    count_recent_login_approvals,
    count_recent_verifications,
    create_login_approval,
    create_phone_verification,
    create_refresh_token,
    find_active_refresh_token,
    find_pending_verification_by_code_hash,
    get_linked_user_by_phone,
    get_login_approval,
    get_phone_verification,
    get_user,
    latest_inbound_at,
    mark_login_approval_fallback,
    mark_verification_verified,
    revoke_refresh_token,
    store_outgoing_pending,
    upsert_user_for_verified_phone,
)
from jan_setu.schemas import (
    ApprovalStatusRequest,
    AuthStatusResponse,
    RefreshResponse,
    RequestCodeRequest,
    RequestCodeResponse,
)
from jan_setu.whatsapp.client import WhatsAppCloudClient, build_reply_buttons_payload
from jan_setu.whatsapp.dispatch import send_pending

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L ambiguity
CODE_LENGTH = 6
REFRESH_COOKIE_NAME = "refresh_token"
LOGIN_APPROVAL_YES = "login_yes"
LOGIN_APPROVAL_NO = "login_no"


def sanitize_browser_label(value: str | None) -> str:
    cleaned = "".join(
        character for character in (value or "This browser") if character.isprintable()
    )
    return " ".join(cleaned.split())[:128] or "This browser"


def build_login_approval_id(decision: str, challenge_id: str, verifier: str) -> str:
    return f"{decision}:{challenge_id}:{verifier}"


def parse_login_approval_id(reply_id: str | None) -> tuple[str, str, str] | None:
    if not reply_id or len(reply_id) > 256:
        return None
    parts = reply_id.split(":")
    if len(parts) != 3 or parts[0] not in (LOGIN_APPROVAL_YES, LOGIN_APPROVAL_NO):
        return None
    decision, challenge_id, verifier = parts
    if len(verifier) < 16 or len(challenge_id) != 36:
        return None
    return decision, challenge_id, verifier


def _request_ip_hash(request: Request) -> str | None:
    if not request.client:
        return None
    return hashlib.sha256(request.client.host.encode()).hexdigest()


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
    recent_count = await count_recent_verifications(session, phone=phone, since=since)
    if recent_count >= settings.verification_max_per_hour:
        logger.warning(
            "verification_code_rejected",
            extra={"reason": "rate_limit_exceeded", "attempt": recent_count},
        )
        raise RateLimitExceeded(phone)

    code = generate_code()
    expires_at = utc_now() + timedelta(minutes=settings.verification_code_ttl_minutes)
    verification = await create_phone_verification(
        session, phone=phone, code_hash=hash_code(code), expires_at=expires_at
    )
    expires_in_seconds = settings.verification_code_ttl_minutes * 60
    logger.info(
        "verification_code_created",
        extra={"verification_id": str(verification.id), "expires_in_seconds": expires_in_seconds},
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
        logger.warning("verification_failed", extra={"reason": "code_not_found_or_mismatch"})
        return msg.VERIFY_INVALID

    user = await upsert_user_for_verified_phone(
        session, phone=normalize_phone(wa_id), contact_id=contact_id
    )
    await mark_verification_verified(session, verification_id=verification.id, user_id=user.id)
    logger.info(
        "verification_verified",
        extra={"verification_id": str(verification.id), "user_id": str(user.id)},
    )
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
    expires_in_seconds = settings.refresh_token_days * 24 * 3600
    logger.info(
        "access_token_issued",
        extra={"user_id": str(user_id), "expires_in_seconds": expires_in_seconds},
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
        logger.warning("refresh_token_rejected", extra={"reason": "token_not_found_or_expired"})
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


async def _reverse_code_response(
    session: AsyncSession, settings: Settings, *, phone: str
) -> RequestCodeResponse:
    verification_id, code = await create_verification(session, settings, phone=phone)
    return RequestCodeResponse(
        verification_id=verification_id,
        method="reverse_code",
        code=code,
        wa_link=wa_deep_link(settings, code),
    )


@router.post("/request-code", response_model=RequestCodeResponse)
async def request_code(
    body: RequestCodeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RequestCodeResponse:
    phone = normalize_phone(body.phone)
    since = utc_now() - timedelta(hours=1)
    # Approval challenges send a WhatsApp message each, so they count against
    # the same hourly cap as reverse codes — otherwise the approval path is an
    # unmetered message-spam vector for any linked phone number.
    attempts = await count_recent_verifications(
        session, phone=phone, since=since
    ) + await count_recent_login_approvals(session, phone=phone, since=since)
    if attempts >= settings.verification_max_per_hour:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification requests for this number. Try again later.",
        )

    user = await get_linked_user_by_phone(session, phone=phone)
    last_inbound = await latest_inbound_at(session, contact_id=user.contact_id) if user else None
    inside_window = bool(
        last_inbound and utc_now() <= last_inbound + timedelta(hours=settings.service_window_hours)
    )
    if user and inside_window and body.browser_nonce:
        verifier = secrets.token_urlsafe(18)
        browser_label = sanitize_browser_label(body.browser_label)
        challenge = await create_login_approval(
            session,
            user=user,
            phone=phone,
            verifier_hash=hash_code(verifier),
            browser_nonce_hash=hash_code(body.browser_nonce),
            browser_label=browser_label,
            expires_minutes=settings.verification_code_ttl_minutes,
            request_ip_hash=_request_ip_hash(request),
        )
        requested = challenge.requested_at.astimezone().strftime("%d %b %Y, %H:%M")
        expires = challenge.expires_at.astimezone().strftime("%H:%M")
        message = (
            "Approve Jan Setu sign-in?\n\n"
            f"Browser: {browser_label}\nRequested: {requested}\nExpires: {expires}\n\n"
            "If this was not you, tap No."
        )
        payload = build_reply_buttons_payload(
            to=phone,
            body=message,
            buttons=[
                (
                    build_login_approval_id(LOGIN_APPROVAL_YES, str(challenge.id), verifier),
                    "Yes, it's me",
                ),
                (
                    build_login_approval_id(LOGIN_APPROVAL_NO, str(challenge.id), verifier),
                    "No, deny",
                ),
            ],
        )
        row = await store_outgoing_pending(
            session,
            contact_id=user.contact_id,
            conversation_id=None,
            reply_kind="login_approval",
            message_type="interactive",
            text_body=message,
            payload=payload,
            idempotency_key=f"login-approval:{challenge.id}",
            in_response_to_message_id=None,
        )
        if row is not None:
            await attach_approval_outbound(session, challenge_id=challenge.id, message_id=row.id)
        await session.commit()
        if row is not None:
            client = WhatsAppCloudClient(settings, request.app.state.http_client)
            async with AsyncSessionLocal() as send_session:
                send_status = await send_pending(send_session, settings, client, row.id)
            if send_status == "sent":
                logger.info(
                    "login_approval_issued",
                    extra={"challenge_id": str(challenge.id)},
                )
                return RequestCodeResponse(
                    verification_id=challenge.id,
                    method="whatsapp_approval",
                    browser_label=browser_label,
                    requested_at=challenge.requested_at,
                    expires_at=challenge.expires_at,
                )
        logger.warning(
            "login_approval_fallback",
            extra={"reason": "send_failed", "challenge_id": str(challenge.id)},
        )
        await mark_login_approval_fallback(session, challenge_id=challenge.id)

    try:
        response = await _reverse_code_response(session, settings, phone=phone)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many verification requests for this number. Try again later.",
        ) from exc
    await session.commit()
    return response


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    verification_id: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthStatusResponse:
    verification = await get_phone_verification(session, verification_id=verification_id)
    if verification is None:
        logger.warning("auth_status_failed", extra={"reason": "verification_not_found"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown verification_id")

    if verification.status == "pending":
        if verification.expires_at <= utc_now():
            logger.info(
                "verification_expired",
                extra={"verification_id": verification_id, "reason": "ttl_elapsed"},
            )
            return AuthStatusResponse(status="expired")
        return AuthStatusResponse(status="pending")

    if verification.status != "verified" or verification.user_id is None:
        logger.info(
            "verification_expired",
            extra={"verification_id": verification_id, "reason": "not_verified"},
        )
        return AuthStatusResponse(status="expired")

    if not await consume_verification(session, verification_id=verification.id):
        logger.info(
            "verification_already_claimed",
            extra={"verification_id": verification_id},
        )
        return AuthStatusResponse(status="expired")  # already claimed by another poll

    access_token, raw_refresh = await issue_tokens(
        session, settings, user_id=str(verification.user_id)
    )
    await session.commit()
    response.set_cookie(REFRESH_COOKIE_NAME, raw_refresh, **_cookie_kwargs(settings))
    return AuthStatusResponse(status="verified", access_token=access_token)


@router.post("/approval-status", response_model=AuthStatusResponse)
async def approval_status(
    body: ApprovalStatusRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthStatusResponse:
    nonce_hash = hash_code(body.browser_nonce)
    challenge = await get_login_approval(
        session, challenge_id=body.verification_id, browser_nonce_hash=nonce_hash
    )
    if challenge is None:
        logger.info(
            "login_approval_expired",
            extra={"challenge_id": str(body.verification_id), "reason": "challenge_not_found"},
        )
        return AuthStatusResponse(status="expired")
    if challenge.expires_at <= utc_now() and challenge.status == "pending":
        logger.info(
            "login_approval_expired",
            extra={"challenge_id": str(body.verification_id), "reason": "ttl_elapsed"},
        )
        return AuthStatusResponse(status="expired")
    if challenge.status == "denied":
        logger.info("login_approval_denied", extra={"challenge_id": str(body.verification_id)})
        return AuthStatusResponse(status="denied")
    if challenge.status != "approved":
        return AuthStatusResponse(status="pending" if challenge.status == "pending" else "expired")
    user_id = await consume_login_approval(
        session, challenge_id=challenge.id, browser_nonce_hash=nonce_hash
    )
    if user_id is None:
        logger.info(
            "login_approval_already_claimed",
            extra={"challenge_id": str(body.verification_id)},
        )
        return AuthStatusResponse(status="expired")
    access_token, raw_refresh = await issue_tokens(session, settings, user_id=str(user_id))
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
        logger.warning("refresh_rejected", extra={"reason": "missing_token"})
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
        logger.info("user_logout", extra={"status": "token_revoked"})
    else:
        logger.info("user_logout", extra={"status": "no_token"})
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
        logger.warning("access_token_rejected", extra={"reason": "missing_token"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_id = decode_access_token(settings, token)
    except jwt.PyJWTError as exc:
        logger.warning("access_token_rejected", extra={"reason": "invalid_signature_or_expired"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token"
        ) from exc
    user = await get_user(session, user_id=user_id)
    if user is None:
        logger.warning(
            "access_token_rejected", extra={"reason": "user_not_found", "user_id": str(user_id)}
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user
