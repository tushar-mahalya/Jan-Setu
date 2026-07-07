"""Contact identity: upsert-by-wa_id and simple listing."""

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import Contact


async def upsert_contact(
    session: AsyncSession,
    *,
    wa_id: str,
    profile_name: str | None = None,
) -> Contact:
    update_values: dict[str, Any] = {"updated_at": utc_now()}
    if profile_name is not None:
        update_values["profile_name"] = profile_name

    statement = (
        insert(Contact)
        .values(wa_id=wa_id, profile_name=profile_name)
        .on_conflict_do_update(
            index_elements=[Contact.wa_id],
            set_=update_values,
        )
        .returning(Contact)
    )
    result = await session.execute(statement)
    return result.scalar_one()


async def list_contacts(session: AsyncSession, *, limit: int, offset: int) -> list[Contact]:
    result = await session.execute(
        select(Contact).order_by(desc(Contact.updated_at)).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def get_contact(session: AsyncSession, *, contact_id: Any) -> Contact | None:
    return await session.get(Contact, contact_id)
