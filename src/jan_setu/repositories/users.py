"""Auth-domain persistence: web-app users, reverse-OTP phone verifications, and
rotating refresh tokens. Named ``users`` (not ``auth``) to stay distinct from
the top-level ``jan_setu.auth`` module, which holds the auth *logic* (code
generation, JWT issuance) that calls into these functions.
"""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import PhoneVerification, RefreshToken, User


async def upsert_user_for_verified_phone(
    session: AsyncSession, *, phone: str, contact_id: Any | None
) -> User:
    statement = (
        insert(User)
        .values(phone=phone, contact_id=contact_id)
        .on_conflict_do_update(
            index_elements=[User.phone],
            set_={"contact_id": contact_id, "updated_at": utc_now()},
        )
        .returning(User)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def get_user(session: AsyncSession, *, user_id: Any) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_phone(session: AsyncSession, *, phone: str) -> User | None:
    return (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()


async def get_user_by_contact_id(session: AsyncSession, *, contact_id: Any) -> User | None:
    result = await session.execute(select(User).where(User.contact_id == contact_id))
    return result.scalar_one_or_none()


async def count_recent_verifications(session: AsyncSession, *, phone: str, since: Any) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PhoneVerification)
        .where(PhoneVerification.phone == phone, PhoneVerification.created_at >= since)
    )
    return result.scalar_one()


async def create_phone_verification(
    session: AsyncSession, *, phone: str, code_hash: str, expires_at: Any
) -> PhoneVerification:
    verification = PhoneVerification(phone=phone, code_hash=code_hash, expires_at=expires_at)
    session.add(verification)
    await session.flush()
    return verification


async def get_phone_verification(
    session: AsyncSession, *, verification_id: Any
) -> PhoneVerification | None:
    return await session.get(PhoneVerification, verification_id)


async def find_pending_verification_by_code_hash(
    session: AsyncSession, *, code_hash: str
) -> PhoneVerification | None:
    result = await session.execute(
        select(PhoneVerification).where(
            PhoneVerification.code_hash == code_hash,
            PhoneVerification.status == "pending",
            PhoneVerification.expires_at > utc_now(),
        )
    )
    return result.scalar_one_or_none()


async def mark_verification_verified(
    session: AsyncSession, *, verification_id: Any, user_id: Any
) -> None:
    await session.execute(
        update(PhoneVerification)
        .where(PhoneVerification.id == verification_id)
        .values(status="verified", verified_at=utc_now(), user_id=user_id)
    )


async def consume_verification(session: AsyncSession, *, verification_id: Any) -> bool:
    """Flip a verified code to consumed exactly once (single-use). Returns True
    if this call performed the flip."""
    result = await session.execute(
        update(PhoneVerification)
        .where(PhoneVerification.id == verification_id, PhoneVerification.status == "verified")
        .values(status="consumed")
        .returning(PhoneVerification.id)
    )
    return result.scalar_one_or_none() is not None


async def create_refresh_token(
    session: AsyncSession, *, user_id: Any, token_hash: str, expires_at: Any
) -> RefreshToken:
    token = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(token)
    await session.flush()
    return token


async def find_active_refresh_token(
    session: AsyncSession, *, token_hash: str
) -> RefreshToken | None:
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utc_now(),
        )
    )
    return result.scalar_one_or_none()


async def revoke_refresh_token(session: AsyncSession, *, token_hash: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
