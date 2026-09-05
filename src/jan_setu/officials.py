"""Government official email-OTP authentication and scoped triage API."""

import hashlib
import mimetypes
import logging
import secrets
import smtplib
from email.message import EmailMessage
from datetime import timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session, utc_now
from jan_setu.pipeline.media import artifact_path
from jan_setu.db.models import Grievance, OfficialLoginChallenge, OfficialUser
from jan_setu.logctx import request_id_var
from jan_setu.pipeline.taxonomy import (
    TAXONOMY_VERSION,
    canonical_category_key,
    category_or_default,
    evaluate_routing_policy,
    route_for_category,
)
from jan_setu.repositories import get_grievance, set_grievance_fields
from jan_setu.repositories.officials import (
    add_official_audit,
    create_official_challenge,
    get_official,
    get_official_by_email,
    get_official_challenge,
    list_scoped_grievances,
    official_can_access,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/official", tags=["official operations"])
OFFICIAL_TOKEN_AUDIENCE = "jan-setu-official"
OFFICIAL_ROLES = {"triage_officer", "department_officer", "supervisor", "auditor", "admin"}


class OfficialCodeRequest(BaseModel):
    email: EmailStr


class OfficialCodeRequested(BaseModel):
    status: str = "accepted"
    challenge_id: UUID


class OfficialCodeVerify(BaseModel):
    challenge_id: UUID
    code: str = Field(min_length=6, max_length=12)


class OfficialSession(BaseModel):
    access_token: str
    official: dict[str, Any]


class OfficialAction(BaseModel):
    action: Literal["approve", "correct", "redirect", "reject", "request_clarification"]
    reason: str = Field(min_length=3, max_length=1000)
    category_id: str | None = None
    asset_scope: Literal["public", "private", "unknown"] | None = None
    safety_level: Literal["none", "possible", "immediate"] | None = None
    department_key: str | None = None


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


async def _recent_official_challenge_count(session: AsyncSession, *, email_hash: str) -> int:
    """Challenges issued for this email in the last hour. Without this, the
    per-challenge 5-attempt lockout is meaningless — an attacker can just
    request a fresh challenge (no auth required) after every 5 guesses and
    keep brute-forcing the 6-digit code indefinitely."""
    since = utc_now() - timedelta(hours=1)
    result = await session.execute(
        select(func.count())
        .select_from(OfficialLoginChallenge)
        .where(
            OfficialLoginChallenge.email_hash == email_hash,
            OfficialLoginChallenge.created_at >= since,
        )
    )
    return result.scalar_one()


def _official_token(settings: Settings, official: OfficialUser) -> str:
    now = utc_now()
    return jwt.encode(
        {
            "sub": str(official.id),
            "aud": OFFICIAL_TOKEN_AUDIENCE,
            "role": official.role,
            "jurisdiction": official.jurisdiction_id,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + settings.access_token_minutes * 60,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


async def require_official(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfficialUser:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        logger.warning("official_token_rejected", extra={"reason": "missing_token"})
        raise HTTPException(status_code=401, detail="Missing official access token")
    try:
        payload = jwt.decode(
            authorization.removeprefix("Bearer ").strip(),
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=OFFICIAL_TOKEN_AUDIENCE,
        )
    except jwt.PyJWTError as exc:
        logger.warning("official_token_rejected", extra={"reason": "invalid_signature_or_expired"})
        raise HTTPException(status_code=401, detail="Invalid official access token") from exc
    official = await get_official(session, official_id=payload["sub"])
    if official is None or not official.active or official.role not in OFFICIAL_ROLES:
        logger.warning(
            "official_token_rejected",
            extra={"reason": "official_not_found_or_inactive", "official_id": payload.get("sub")},
        )
        raise HTTPException(status_code=401, detail="Unknown official")
    return official


def _send_official_code_email(
    settings: Settings, to_email: str, code: str, official_id: str
) -> None:
    message = EmailMessage()
    message["Subject"] = "Your Jan Setu official sign-in code"
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(f"Your one-time Jan Setu code is {code}. It expires in 10 minutes.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
            smtp.ehlo()
            # Opportunistic upgrade: the OTP is sensitive in transit, and most
            # real relays advertise STARTTLS. Local dev/test SMTP debug servers
            # (e.g. aiosmtpd on smtp_port=1025) don't, so this is a no-op there.
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("official_otp_delivery_failed", extra={"official_id": official_id})


@router.post("/auth/request-code", response_model=OfficialCodeRequested)
async def request_official_code(
    body: OfficialCodeRequest,
    background: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfficialCodeRequested:
    email = body.email.strip().lower()
    email_hash = _hash(email)
    # Rate limit by email hash (not by whether the account exists) so the
    # 429 itself never leaks account existence.
    if await _recent_official_challenge_count(session, email_hash=email_hash) >= (
        settings.official_code_max_per_hour
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many code requests for this email. Try again later.",
        )
    official = await get_official_by_email(session, email=email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = await create_official_challenge(
        session,
        official_user_id=official.id if official else None,
        email_hash=email_hash,
        code_hash=_hash(code),
    )
    # Generic response prevents account enumeration; sending the mail after the
    # response (in a threadpool) keeps the event loop unblocked and removes the
    # response-time signal that would otherwise reveal whether the email exists.
    if official:
        logger.info("official_otp_issued", extra={"official_id": str(official.id)})
        background.add_task(
            _send_official_code_email, settings, official.email, code, str(official.id)
        )
    await session.commit()
    # The code is never returned to the caller: it reaches the official only by
    # email. Local demos use OFFICIAL_DEV_LOGIN_CODE instead.
    return OfficialCodeRequested(challenge_id=challenge.id)


@router.post("/auth/verify", response_model=OfficialSession)
async def verify_official_code(
    body: OfficialCodeVerify,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfficialSession:
    challenge = await get_official_challenge(session, challenge_id=body.challenge_id)
    if (
        challenge is None
        or challenge.consumed_at is not None
        or challenge.expires_at <= utc_now()
        or challenge.attempt_count >= 5
    ):
        logger.warning(
            "official_otp_rejected",
            extra={
                "reason": "challenge_invalid_expired_or_consumed",
                "challenge_id": str(body.challenge_id),
            },
        )
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    challenge.attempt_count += 1
    code_matches = secrets.compare_digest(challenge.code_hash, _hash(body.code))
    used_dev_code = False
    # Local-demo escape hatch. It replaces only the code comparison -- the
    # challenge must still be live and bound to a real, active official -- and
    # it still burns an attempt, so it cannot be brute-forced. Settings refuses
    # to load with this set outside development/test.
    if not code_matches and settings.official_dev_login_code is not None:
        code_matches = settings.environment in {"development", "test"} and (
            secrets.compare_digest(settings.official_dev_login_code.get_secret_value(), body.code)
        )
        if code_matches:
            used_dev_code = True
    if not code_matches or not challenge.official_user_id:
        await session.commit()
        logger.warning(
            "official_otp_rejected",
            extra={
                "reason": "invalid_code",
                "challenge_id": str(body.challenge_id),
                "attempt": challenge.attempt_count,
            },
        )
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    official = await get_official(session, official_id=challenge.official_user_id)
    if official is None or not official.active:
        logger.warning(
            "official_otp_rejected",
            extra={
                "reason": "official_not_found_or_inactive",
                "official_id": str(challenge.official_user_id),
            },
        )
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    challenge.consumed_at = utc_now()
    official.last_login_at = utc_now()
    await add_official_audit(
        session, official_user_id=official.id, grievance_id=None, action="login"
    )
    if used_dev_code:
        logger.warning(
            "official_dev_login_used",
            extra={"official_id": str(official.id), "environment": settings.environment},
        )
    else:
        logger.info(
            "official_login_succeeded",
            extra={"official_id": str(official.id), "role": official.role},
        )
    await session.commit()
    return OfficialSession(
        access_token=_official_token(settings, official),
        official={
            "id": str(official.id),
            "name": official.name,
            "email": official.email,
            "role": official.role,
            "jurisdiction_id": official.jurisdiction_id,
            "department_keys": list(official.department_keys or []),
        },
    )


def _queue_item(grievance: Grievance) -> dict[str, Any]:
    category = category_or_default(grievance.category_id or grievance.category)
    return {
        "id": str(grievance.id),
        "human_id": grievance.human_id,
        "status": grievance.status,
        "review_status": grievance.review_status,
        "category_id": grievance.category_id,
        "category_label": category.label,
        "domain": category.parent_key,
        "department_key": grievance.department_key,
        "priority": grievance.priority,
        "safety_level": grievance.safety_level,
        "disposition": grievance.disposition,
        "confidence": grievance.confidence,
        "address": grievance.location_address,
        "issue_text": grievance.issue_text,
        "photo_url": (
            f"/api/official/grievances/{grievance.id}/photo" if grievance.photo_path else None
        ),
        "image_match_status": grievance.image_match_status,
        "structured_facts": grievance.structured_facts,
        "routing": grievance.routing_snapshot,
        "flags": list(grievance.flags or []),
        "created_at": grievance.created_at.isoformat(),
        "state_version": grievance.state_version,
    }


@router.get("/queue")
async def official_queue(
    session: Annotated[AsyncSession, Depends(get_session)],
    official: Annotated[OfficialUser, Depends(require_official)],
    review_status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    rows = await list_scoped_grievances(
        session, official=official, review_status=review_status, limit=limit, offset=offset
    )
    return [_queue_item(row) for row in rows]


@router.get("/grievances/{grievance_id}")
async def official_grievance(
    grievance_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    official: Annotated[OfficialUser, Depends(require_official)],
) -> dict[str, Any]:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    if grievance is None or not official_can_access(official, grievance):
        raise HTTPException(status_code=404, detail="Complaint not found")
    await add_official_audit(
        session,
        official_user_id=official.id,
        grievance_id=grievance.id,
        action="view",
        request_id=request_id_var.get(),
    )
    await session.commit()
    return _queue_item(grievance)


@router.post("/grievances/{grievance_id}/actions")
async def official_action(
    grievance_id: UUID,
    body: OfficialAction,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    official: Annotated[OfficialUser, Depends(require_official)],
) -> dict[str, Any]:
    if official.role == "auditor":
        raise HTTPException(status_code=403, detail="Auditors cannot modify complaints")
    grievance = await get_grievance(session, grievance_id=grievance_id)
    if grievance is None or not official_can_access(official, grievance):
        raise HTTPException(status_code=404, detail="Complaint not found")
    before = _queue_item(grievance)
    category_key = canonical_category_key(
        body.category_id or grievance.category_id or grievance.category
    )
    if category_key is None:
        raise HTTPException(status_code=422, detail="Valid category required")
    asset_scope = body.asset_scope or grievance.asset_scope or "unknown"
    safety = body.safety_level or grievance.safety_level or "none"
    category = category_or_default(category_key)
    policy = evaluate_routing_policy(
        category_key=category_key,
        safety=safety,
        asset_scope=asset_scope,
        jurisdiction_known=bool(grievance.location_address),
        extraction_confidence=1.0,
    )
    route = route_for_category(category_key)
    review_status = {
        "approve": "approved",
        "correct": "approved",
        "redirect": "redirected",
        "reject": "rejected",
        "request_clarification": "awaiting_citizen",
    }[body.action]
    await set_grievance_fields(
        session,
        grievance_id=grievance.id,
        category=category_key,
        category_id=category_key,
        aggregation_key=category.aggregation_key,
        department_key=body.department_key
        or (route.department_key if route else category.department_key),
        priority=policy.priority,
        asset_scope=asset_scope,
        safety_level=safety,
        disposition="redirect" if body.action == "redirect" else policy.disposition,
        review_status=review_status,
        taxonomy_version=TAXONOMY_VERSION,
        state_version=grievance.state_version + 1,
        routing_snapshot={
            "taxonomy_version": TAXONOMY_VERSION,
            "category_id": category_key,
            "department_key": body.department_key
            or (route.department_key if route else category.department_key),
            "owning_agency": route.owning_agency if route else None,
            "dispatch_enabled": route.dispatch_enabled if route else False,
            "sla_hours": route.sla_hours if route else None,
            "disposition": "redirect" if body.action == "redirect" else policy.disposition,
        },
    )
    after = _queue_item(grievance)
    await add_official_audit(
        session,
        official_user_id=official.id,
        grievance_id=grievance.id,
        action=body.action,
        reason=body.reason,
        before=before,
        after=after,
        request_id=request_id_var.get(),
    )
    logger.info(
        "official_action_recorded",
        extra={
            "official_id": str(official.id),
            "grievance_id": str(grievance.id),
            "action": body.action,
            "role": official.role,
        },
    )
    await session.commit()
    return after


@router.get("/grievances/{grievance_id}/photo")
async def official_grievance_photo(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    official: Annotated[OfficialUser, Depends(require_official)],
) -> FileResponse:
    """Citizen evidence photo for the reviewing official. Scoped by the same
    jurisdiction check as the case itself, and recorded as an evidence view --
    the login copy promises that evidence access is audited."""
    grievance = await get_grievance(session, grievance_id=grievance_id)
    if grievance is None or not official_can_access(official, grievance):
        raise HTTPException(status_code=404, detail="Complaint not found")
    if not grievance.photo_path:
        raise HTTPException(status_code=404, detail="No photo attached")
    photo_path = artifact_path(settings, grievance.photo_path)
    if not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Photo artifact is unavailable")
    await add_official_audit(
        session, official_user_id=official.id, grievance_id=grievance.id, action="view_evidence"
    )
    await session.commit()
    return FileResponse(
        photo_path, media_type=mimetypes.guess_type(photo_path.name)[0] or "image/jpeg"
    )


@router.get("/metrics")
async def official_metrics(
    session: Annotated[AsyncSession, Depends(get_session)],
    official: Annotated[OfficialUser, Depends(require_official)],
) -> dict[str, Any]:
    rows = await list_scoped_grievances(
        session, official=official, review_status=None, limit=100, offset=0
    )
    return {
        "total_visible": len(rows),
        "pending_review": sum(row.review_status == "pending_official" for row in rows),
        "immediate_safety": sum(row.safety_level == "immediate" for row in rows),
        "failed_ai": sum("classification_failed" in (row.flags or []) for row in rows),
        "failed_dispatch": sum(row.status == "dispatch_failed" for row in rows),
    }
