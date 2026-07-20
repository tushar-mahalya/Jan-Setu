"""Atomic persistence for browser-bound WhatsApp login approvals."""

from datetime import timedelta
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import LoginApprovalChallenge, User, WhatsAppMessage


async def get_linked_user_by_phone(session: AsyncSession, *, phone: str) -> User | None:
    return (
        await session.execute(select(User).where(User.phone == phone, User.contact_id.is_not(None)))
    ).scalar_one_or_none()


async def latest_inbound_at(session: AsyncSession, *, contact_id: Any) -> Any | None:
    return (
        await session.execute(
            select(WhatsAppMessage.received_at)
            .where(
                WhatsAppMessage.contact_id == contact_id,
                WhatsAppMessage.direction == "incoming",
            )
            .order_by(desc(WhatsAppMessage.received_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def count_recent_login_approvals(session: AsyncSession, *, phone: str, since: Any) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(LoginApprovalChallenge)
            .where(
                LoginApprovalChallenge.phone == phone,
                LoginApprovalChallenge.requested_at >= since,
            )
        )
    ).scalar_one()


async def create_login_approval(
    session: AsyncSession,
    *,
    user: User,
    phone: str,
    verifier_hash: str,
    browser_nonce_hash: str,
    browser_label: str,
    expires_minutes: int,
    request_ip_hash: str | None,
) -> LoginApprovalChallenge:
    await session.execute(
        update(LoginApprovalChallenge)
        .where(
            LoginApprovalChallenge.user_id == user.id,
            LoginApprovalChallenge.status == "pending",
        )
        .values(status="superseded", decided_at=utc_now())
    )
    row = LoginApprovalChallenge(
        user_id=user.id,
        contact_id=user.contact_id,
        phone=phone,
        verifier_hash=verifier_hash,
        browser_nonce_hash=browser_nonce_hash,
        browser_label=browser_label,
        status="pending",
        expires_at=utc_now() + timedelta(minutes=expires_minutes),
        request_ip_hash=request_ip_hash,
    )
    session.add(row)
    await session.flush()
    return row


async def attach_approval_outbound(
    session: AsyncSession, *, challenge_id: Any, message_id: Any
) -> None:
    await session.execute(
        update(LoginApprovalChallenge)
        .where(
            LoginApprovalChallenge.id == challenge_id,
            LoginApprovalChallenge.status == "pending",
        )
        .values(approval_outbound_message_id=message_id)
    )


async def decide_login_approval(
    session: AsyncSession,
    *,
    challenge_id: Any,
    verifier_hash: str,
    contact_id: Any,
    phone: str,
    context_message_id: str,
    decision_message_id: str,
    decision: str,
) -> LoginApprovalChallenge | None:
    if decision not in ("approved", "denied"):
        return None
    outbound_wamid = (
        select(WhatsAppMessage.meta_message_id)
        .where(WhatsAppMessage.id == LoginApprovalChallenge.approval_outbound_message_id)
        .scalar_subquery()
    )
    result = await session.execute(
        update(LoginApprovalChallenge)
        .where(
            LoginApprovalChallenge.id == challenge_id,
            LoginApprovalChallenge.status == "pending",
            LoginApprovalChallenge.expires_at > utc_now(),
            LoginApprovalChallenge.verifier_hash == verifier_hash,
            LoginApprovalChallenge.contact_id == contact_id,
            LoginApprovalChallenge.phone == phone,
            LoginApprovalChallenge.approval_outbound_message_id.is_not(None),
            outbound_wamid == context_message_id,
        )
        .values(
            status=decision,
            decided_at=utc_now(),
            decision_message_id=decision_message_id,
        )
        .returning(LoginApprovalChallenge)
    )
    return result.scalar_one_or_none()


async def consume_login_approval(
    session: AsyncSession, *, challenge_id: Any, browser_nonce_hash: str
) -> Any | None:
    result = await session.execute(
        update(LoginApprovalChallenge)
        .where(
            LoginApprovalChallenge.id == challenge_id,
            LoginApprovalChallenge.status == "approved",
            LoginApprovalChallenge.expires_at > utc_now(),
            LoginApprovalChallenge.browser_nonce_hash == browser_nonce_hash,
        )
        .values(status="consumed", consumed_at=utc_now())
        .returning(LoginApprovalChallenge.user_id)
    )
    return result.scalar_one_or_none()


async def get_login_approval(
    session: AsyncSession, *, challenge_id: Any, browser_nonce_hash: str
) -> LoginApprovalChallenge | None:
    return (
        await session.execute(
            select(LoginApprovalChallenge).where(
                LoginApprovalChallenge.id == challenge_id,
                LoginApprovalChallenge.browser_nonce_hash == browser_nonce_hash,
            )
        )
    ).scalar_one_or_none()


async def mark_login_approval_fallback(session: AsyncSession, *, challenge_id: Any) -> None:
    await session.execute(
        update(LoginApprovalChallenge)
        .where(
            LoginApprovalChallenge.id == challenge_id,
            LoginApprovalChallenge.status == "pending",
        )
        .values(status="fallback", decided_at=utc_now())
    )
