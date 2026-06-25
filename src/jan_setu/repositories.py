from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import desc, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.database import utc_now
from jan_setu.models import (
    Contact,
    Conversation,
    FsmMessageConsumption,
    Grievance,
    WebhookEvent,
    WhatsAppMessage,
)
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
    )
    session.add(event)
    await session.flush()
    return event


async def mark_event_processed(session: AsyncSession, *, event_id: Any) -> None:
    await session.execute(
        update(WebhookEvent).where(WebhookEvent.id == event_id).values(processed_at=utc_now())
    )


async def fetch_unprocessed_events(session: AsyncSession, *, limit: int) -> list[WebhookEvent]:
    result = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.processed_at.is_(None))
        .order_by(WebhookEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


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


# --- Conversation engine -------------------------------------------------------


async def lock_contact_and_get_conversation(
    session: AsyncSession, *, contact_id: Any, ttl_hours: int
) -> Conversation | None:
    """Serialize per-contact processing: lock the contact row, then return its
    active conversation (locked) if one exists and has not expired. An expired
    conversation is marked inactive and ``None`` is returned so the caller starts
    a fresh one."""
    await session.execute(select(Contact).where(Contact.id == contact_id).with_for_update())
    conversation = (
        await session.execute(
            select(Conversation)
            .where(Conversation.contact_id == contact_id, Conversation.active.is_(True))
            .with_for_update()
        )
    ).scalar_one_or_none()

    if conversation is None:
        return None
    if conversation.expires_at is not None and conversation.expires_at < utc_now():
        conversation.active = False
        # Flush the deactivation before the caller inserts a replacement, so the
        # partial unique index never sees two active rows for this contact.
        await session.flush()
        return None
    return conversation


async def claim_inbound(session: AsyncSession, *, inbound_message_id: str) -> bool:
    """Idempotency gate. Returns True if this inbound has not been consumed yet
    (caller should process it); False if it is a replay (caller skips)."""
    result = await session.execute(
        insert(FsmMessageConsumption)
        .values(inbound_message_id=inbound_message_id)
        .on_conflict_do_nothing(index_elements=[FsmMessageConsumption.inbound_message_id])
        .returning(FsmMessageConsumption.id)
    )
    return result.scalar_one_or_none() is not None


async def annotate_consumption(
    session: AsyncSession,
    *,
    inbound_message_id: str,
    conversation_id: Any,
    state_before: str | None,
    state_after: str | None,
) -> None:
    await session.execute(
        update(FsmMessageConsumption)
        .where(FsmMessageConsumption.inbound_message_id == inbound_message_id)
        .values(
            conversation_id=conversation_id,
            state_before=state_before,
            state_after=state_after,
        )
    )


def _service_window_expiry(last_user_message_at: Any, service_window_hours: int) -> Any:
    return last_user_message_at + timedelta(hours=service_window_hours)


async def upsert_conversation_state(
    session: AsyncSession,
    *,
    conversation: Conversation | None,
    contact_id: Any,
    state: str,
    context: dict[str, Any],
    last_user_message_at: Any,
    ttl_hours: int,
    service_window_hours: int,
) -> Conversation:
    """Create the conversation (first contact) or advance the existing one. Runs
    under the contact lock taken by ``lock_contact_and_get_conversation`` so the
    partial unique index (one active conversation per contact) is never violated."""
    now = utc_now()
    if conversation is None:
        conversation = Conversation(
            contact_id=contact_id,
            state=state,
            context=context,
            active=True,
            last_user_message_at=last_user_message_at,
            service_window_expires_at=_service_window_expiry(
                last_user_message_at, service_window_hours
            ),
            expires_at=now + timedelta(hours=ttl_hours),
        )
        session.add(conversation)
        await session.flush()
        return conversation

    conversation.state = state
    conversation.context = context
    conversation.state_version += 1
    conversation.last_user_message_at = last_user_message_at
    conversation.service_window_expires_at = _service_window_expiry(
        last_user_message_at, service_window_hours
    )
    conversation.expires_at = now + timedelta(hours=ttl_hours)
    return conversation


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


async def create_grievance(
    session: AsyncSession,
    *,
    contact_id: Any,
    conversation_id: Any,
    context: dict[str, Any],
) -> tuple[Grievance, bool]:
    """Register a grievance from the conversation context. Idempotent on
    ``conversation_id`` (unique) — a replay returns the existing grievance with
    its original human id. Returns (grievance, created)."""
    location = context.get("location", {})
    issue = context.get("issue", {})
    photo = context.get("photo", {})
    issue_message_ids = [
        message["message_id"] for message in issue.get("messages", []) if message.get("message_id")
    ]

    sequence = (await session.execute(text("SELECT nextval('grievance_human_seq')"))).scalar_one()
    human_id = f"JS-{utc_now():%Y%m%d}-{int(sequence):05d}"

    statement = (
        insert(Grievance)
        .values(
            human_id=human_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            location_latitude=location.get("lat"),
            location_longitude=location.get("lon"),
            location_address=location.get("display_address"),
            issue_message_ids=issue_message_ids,
            photo_media_id=photo.get("media_id"),
            status="registered",
        )
        .on_conflict_do_nothing(index_elements=[Grievance.conversation_id])
        .returning(Grievance)
    )
    grievance = (await session.execute(statement)).scalar_one_or_none()
    if grievance is not None:
        return grievance, True

    existing = (
        await session.execute(select(Grievance).where(Grievance.conversation_id == conversation_id))
    ).scalar_one()
    return existing, False
