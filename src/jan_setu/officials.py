"""Government official email-OTP authentication and scoped triage API."""

import hashlib
import logging
import secrets
import smtplib
from email.message import EmailMessage
from typing import Annotated, Any, Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session, utc_now
from jan_setu.db.models import Grievance, OfficialUser
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
    dev_code: str | None = None


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
        raise HTTPException(status_code=401, detail="Missing official access token")
    try:
        payload = jwt.decode(
            authorization.removeprefix("Bearer ").strip(),
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=OFFICIAL_TOKEN_AUDIENCE,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid official access token") from exc
    official = await get_official(session, official_id=payload["sub"])
    if official is None or not official.active or official.role not in OFFICIAL_ROLES:
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
            smtp.send_message(message)
    except OSError:
        logger.exception("official_otp_delivery_failed", extra={"official_id": official_id})


@router.post("/auth/request-code", response_model=OfficialCodeRequested)
async def request_official_code(
    body: OfficialCodeRequest,
    background: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OfficialCodeRequested:
    email = body.email.strip().lower()
    official = await get_official_by_email(session, email=email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = await create_official_challenge(
        session,
        official_user_id=official.id if official else None,
        email_hash=_hash(email),
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
    return OfficialCodeRequested(
        challenge_id=challenge.id,
        dev_code=code if settings.environment == "development" and official else None,
    )


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
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    challenge.attempt_count += 1
    if (
        not secrets.compare_digest(challenge.code_hash, _hash(body.code))
        or not challenge.official_user_id
    ):
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    official = await get_official(session, official_id=challenge.official_user_id)
    if official is None or not official.active:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    challenge.consumed_at = utc_now()
    official.last_login_at = utc_now()
    await add_official_audit(
        session, official_user_id=official.id, grievance_id=None, action="login"
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
    await session.commit()
    return after


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
