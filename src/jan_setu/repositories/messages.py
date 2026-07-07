"""Inbound/outbound WhatsApp message storage and the outbound send lease.

``StoredIncomingMessage`` distinguishes a freshly-stored message from a replay
(``created=False``) so callers only run the FSM for genuinely new messages.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import Contact, WhatsAppMessage
from jan_setu.repositories.contacts import upsert_contact
from jan_setu.whatsapp.client import IncomingWhatsAppMessage


@dataclass(frozen=True)
class StoredIncomingMessage:
    message: WhatsAppMessage | None
    wa_id: str
    created: bool


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
                status="received",
                message_type=incoming.message_type,
                text_body=incoming.text_body,
                media_id=incoming.media_id,
                media_mime_type=incoming.media_mime_type,
                location_latitude=incoming.location_latitude,
                location_longitude=incoming.location_longitude,
                location_name=incoming.location_name,
                location_address=incoming.location_address,
                location_url=incoming.location_url,
                reply_id=incoming.reply_id,
                interactive_type=incoming.interactive_type,
                button_payload=incoming.button_payload,
                context_message_id=incoming.context_message_id,
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

        stored_messages.append(
            StoredIncomingMessage(message=None, wa_id=incoming.wa_id, created=False)
        )
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


async def store_outgoing_pending(
    session: AsyncSession,
    *,
    contact_id: Any,
    conversation_id: Any,
    reply_kind: str,
    message_type: str,
    text_body: str | None,
    payload: dict[str, Any],
    idempotency_key: str,
    in_response_to_message_id: str | None,
) -> WhatsAppMessage | None:
    """Persist an outbound reply as ``pending`` before it is sent. Returns the new
    row, or ``None`` if an identical reply already exists (replay)."""
    result = await session.execute(
        insert(WhatsAppMessage)
        .values(
            contact_id=contact_id,
            conversation_id=conversation_id,
            direction="outgoing",
            status="pending",
            message_type=message_type,
            text_body=text_body,
            reply_kind=reply_kind,
            idempotency_key=idempotency_key,
            in_response_to_message_id=in_response_to_message_id,
            raw_payload=payload,
            received_at=utc_now(),
        )
        .on_conflict_do_nothing(index_elements=[WhatsAppMessage.idempotency_key])
        .returning(WhatsAppMessage)
    )
    return result.scalar_one_or_none()


async def claim_outbound(session: AsyncSession, *, message_id: Any, lease_seconds: int) -> bool:
    """Atomically lease a pending (or stale-leased) outbound row for sending.
    Only one caller wins; returns True if this caller claimed it."""
    now = utc_now()
    result = await session.execute(
        update(WhatsAppMessage)
        .where(
            WhatsAppMessage.id == message_id,
            WhatsAppMessage.direction == "outgoing",
            (WhatsAppMessage.status == "pending")
            | ((WhatsAppMessage.status == "sending") & (WhatsAppMessage.locked_until < now)),
        )
        .values(
            status="sending",
            locked_until=now + timedelta(seconds=lease_seconds),
            attempt_count=WhatsAppMessage.attempt_count + 1,
        )
        .returning(WhatsAppMessage.id)
    )
    return result.scalar_one_or_none() is not None


async def mark_outbound(
    session: AsyncSession,
    *,
    message_id: Any,
    status: str,
    meta_message_id: str | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "locked_until": None}
    if meta_message_id is not None:
        values["meta_message_id"] = meta_message_id
    await session.execute(
        update(WhatsAppMessage).where(WhatsAppMessage.id == message_id).values(**values)
    )


async def fetch_sweepable_outbound(session: AsyncSession, *, limit: int) -> list[WhatsAppMessage]:
    """Outbound replies that still need sending: never-sent ``pending`` rows and
    ``sending`` rows whose lease expired (a crashed sender). Claiming each row is
    the concurrency guard, so no row lock is held across the HTTP send."""
    now = utc_now()
    result = await session.execute(
        select(WhatsAppMessage)
        .where(
            WhatsAppMessage.direction == "outgoing",
            (WhatsAppMessage.status == "pending")
            | ((WhatsAppMessage.status == "sending") & (WhatsAppMessage.locked_until < now)),
        )
        .order_by(WhatsAppMessage.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())
