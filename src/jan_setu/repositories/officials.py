"""Official identity, scoped triage, and immutable audit persistence."""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import Grievance, OfficialAuditEvent, OfficialLoginChallenge, OfficialUser


async def get_official_by_email(session: AsyncSession, *, email: str) -> OfficialUser | None:
    return (
        await session.execute(
            select(OfficialUser).where(
                func.lower(OfficialUser.email) == email.strip().lower(),
                OfficialUser.active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def get_official(session: AsyncSession, *, official_id: Any) -> OfficialUser | None:
    return await session.get(OfficialUser, official_id)


async def create_official_challenge(
    session: AsyncSession,
    *,
    official_user_id: Any | None,
    email_hash: str,
    code_hash: str,
    expires_minutes: int = 10,
) -> OfficialLoginChallenge:
    row = OfficialLoginChallenge(
        official_user_id=official_user_id,
        email_hash=email_hash,
        code_hash=code_hash,
        expires_at=utc_now() + timedelta(minutes=expires_minutes),
    )
    session.add(row)
    await session.flush()
    return row


async def get_official_challenge(
    session: AsyncSession, *, challenge_id: Any
) -> OfficialLoginChallenge | None:
    return await session.get(OfficialLoginChallenge, challenge_id, with_for_update=True)


async def list_scoped_grievances(
    session: AsyncSession,
    *,
    official: OfficialUser,
    review_status: str | None,
    limit: int,
    offset: int,
) -> list[Grievance]:
    conditions = [Grievance.jurisdiction_id == official.jurisdiction_id]
    if official.role == "department_officer":
        conditions.append(Grievance.department_key.in_(list(official.department_keys or [])))
    if review_status:
        conditions.append(Grievance.review_status == review_status)
    return list(
        (
            await session.execute(
                select(Grievance)
                .where(*conditions)
                .order_by(Grievance.created_at)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


def official_can_access(official: OfficialUser, grievance: Grievance) -> bool:
    if grievance.jurisdiction_id != official.jurisdiction_id:
        return False
    return official.role != "department_officer" or grievance.department_key in set(
        official.department_keys or []
    )


async def add_official_audit(
    session: AsyncSession,
    *,
    official_user_id: Any,
    grievance_id: Any | None,
    action: str,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> None:
    session.add(
        OfficialAuditEvent(
            official_user_id=official_user_id,
            grievance_id=grievance_id,
            action=action,
            reason=reason,
            before=before,
            after=after,
            request_id=request_id,
            ip_hash=ip_hash,
        )
    )
    await session.flush()
