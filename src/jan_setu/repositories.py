from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.database import utc_now
from jan_setu.models import Contact, WebhookEvent, WhatsAppMessage
from jan_setu.whatsapp import IncomingWhatsAppMessage


@dataclass(frozen=True)
class StoredIncomingMessage:
    message: WhatsAppMessage | None
    wa_id: str
    created: bool


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


async def store_webhook_event(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    signature_valid: bool,
) -> WebhookEvent:
    event = WebhookEvent(
        source="whatsapp",
        signature_valid=signature_valid,
        payload=payload,
        processed_at=utc_now(),
    )
    session.add(event)
    await session.flush()
    return event


async def store_incoming_messages(
    session: AsyncSession,
    messages: Iterable[IncomingWhatsAppMessage],
) -> list[StoredIncomingMessage]:
    stored_messages: list[StoredIncomingMessage] = []
    for incoming in messages:
        contact = await upsert_contact(
            session,
            wa_id=incoming.wa_id,
            profile_name=incoming.profile_name,
        )
        statement = (
            insert(WhatsAppMessage)
            .values(
                contact_id=contact.id,
                meta_message_id=incoming.meta_message_id,
                direction="incoming",
                message_type=incoming.message_type,
                text_body=incoming.text_body,
                raw_payload=incoming.raw_payload,
                received_at=incoming.received_at,
            )
            .on_conflict_do_nothing(index_elements=[WhatsAppMessage.meta_message_id])
            .returning(WhatsAppMessage)
        )
        result = await session.execute(statement)
        message = result.scalar_one_or_none()
        if message is not None:
            stored_messages.append(
                StoredIncomingMessage(message=message, wa_id=incoming.wa_id, created=True)
            )
            continue

        stored_messages.append(StoredIncomingMessage(message=None, wa_id=incoming.wa_id, created=False))
    return stored_messages


async def store_outgoing_message(
    session: AsyncSession,
    *,
    wa_id: str,
    meta_message_id: str | None,
    text_body: str,
    raw_payload: dict[str, Any],
) -> WhatsAppMessage:
    contact = await upsert_contact(session, wa_id=wa_id)
    message = WhatsAppMessage(
        contact_id=contact.id,
        meta_message_id=meta_message_id,
        direction="outgoing",
        message_type="text",
        text_body=text_body,
        raw_payload=raw_payload,
        received_at=utc_now(),
    )
    session.add(message)
    await session.flush()
    return message


async def list_contacts(session: AsyncSession, *, limit: int, offset: int) -> list[Contact]:
    result = await session.execute(
        select(Contact).order_by(desc(Contact.updated_at)).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def list_messages(
    session: AsyncSession,
    *,
    limit: int,
    wa_id: str | None = None,
) -> list[WhatsAppMessage]:
    statement = select(WhatsAppMessage).order_by(desc(WhatsAppMessage.received_at)).limit(limit)
    if wa_id:
        statement = statement.join(Contact).where(Contact.wa_id == wa_id)
    result = await session.execute(statement)
    return list(result.scalars().all())
