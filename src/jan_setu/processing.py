"""Asynchronous processing of WhatsApp webhook payloads.

The webhook endpoint persists the raw event and acknowledges Meta immediately;
the heavier work of storing messages and running the conversation engine happens
here, off the request path. This keeps webhook latency low and means a processing
failure never loses the event — it stays unprocessed and can be replayed.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings, get_settings
from jan_setu.conversation import advance
from jan_setu.database import AsyncSessionLocal
from jan_setu.dispatch import send_pending
from jan_setu.geocoding import reverse_geocode_cached
from jan_setu.repositories import (
    annotate_consumption,
    claim_inbound,
    fetch_unprocessed_events,
    lock_contact_and_get_conversation,
    mark_event_processed,
    store_incoming_messages,
    store_outgoing_pending,
    upsert_contact,
    upsert_conversation_state,
)
from jan_setu.whatsapp import IncomingWhatsAppMessage, WhatsAppCloudClient, iter_incoming_messages

logger = logging.getLogger(__name__)


async def process_webhook_messages(
    event_id: UUID,
    messages: Sequence[IncomingWhatsAppMessage],
) -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        try:
            stored = await store_incoming_messages(session, messages)
            await mark_event_processed(session, event_id=event_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("webhook_processing_failed", extra={"event_id": str(event_id)})
            return

    messages_stored = sum(1 for item in stored if item.created)
    logger.info(
        "webhook_messages_processed",
        extra={"event_id": str(event_id), "messages_stored": messages_stored},
    )

    if not settings.auto_reply_enabled:
        return

    # Only run the FSM for messages newly stored by this call; replays are also
    # guarded by the consumption gate. Process each contact's messages in
    # WhatsApp-timestamp order.
    fresh = [incoming for incoming, item in zip(messages, stored) if item.created]
    fresh.sort(key=lambda m: m.received_at)
    client = WhatsAppCloudClient(settings)
    for incoming in fresh:
        try:
            await _run_conversation_turn(settings, client, incoming)
        except Exception:
            logger.exception(
                "auto_reply_failed", extra={"meta_message_id": incoming.meta_message_id}
            )


async def _run_conversation_turn(
    settings: Settings,
    client: WhatsAppCloudClient,
    incoming: IncomingWhatsAppMessage,
) -> None:
    # Geocode BEFORE taking the conversation lock — it depends only on lat/lon and
    # would otherwise hold the lock across a slow external call.
    geocode = None
    if incoming.message_type == "location" and incoming.location_latitude is not None:
        async with AsyncSessionLocal() as geo_session:
            geocode = await reverse_geocode_cached(
                geo_session,
                settings,
                incoming.location_latitude,
                incoming.location_longitude,
            )

    pending_ids: list[UUID] = []
    async with AsyncSessionLocal() as session:
        try:
            contact = await upsert_contact(session, wa_id=incoming.wa_id)
            if not await claim_inbound(session, inbound_message_id=incoming.meta_message_id):
                await session.commit()  # replay: already consumed
                return

            conversation = await lock_contact_and_get_conversation(
                session, contact_id=contact.id, ttl_hours=settings.conversation_ttl_hours
            )
            state_before = conversation.state if conversation else None
            result = advance(
                wa_id=incoming.wa_id,
                state=state_before,
                context=conversation.context if conversation else None,
                inbound=incoming,
                geocode=geocode,
            )
            conversation = await upsert_conversation_state(
                session,
                conversation=conversation,
                contact_id=contact.id,
                state=result.state,
                context=result.context,
                last_user_message_at=incoming.received_at,
                ttl_hours=settings.conversation_ttl_hours,
                service_window_hours=settings.service_window_hours,
            )
            await annotate_consumption(
                session,
                inbound_message_id=incoming.meta_message_id,
                conversation_id=conversation.id,
                state_before=state_before,
                state_after=result.state,
            )
            for intent in result.intents:
                idempotency_key = (
                    f"{conversation.id}:{incoming.meta_message_id}:{intent.reply_kind}"
                )
                row = await store_outgoing_pending(
                    session,
                    contact_id=contact.id,
                    conversation_id=conversation.id,
                    reply_kind=intent.reply_kind,
                    message_type=intent.message_type,
                    text_body=intent.text_body,
                    payload=intent.payload,
                    idempotency_key=idempotency_key,
                    in_response_to_message_id=incoming.meta_message_id,
                )
                if row is not None:
                    pending_ids.append(row.id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Persist-before-send: replies are committed as `pending`; send them now. A
    # crash here leaves them for the worker sweep, never lost.
    for message_id in pending_ids:
        async with AsyncSessionLocal() as send_session:
            await send_pending(send_session, settings, client, message_id)


async def process_pending_events(session: AsyncSession, *, batch_size: int) -> int:
    """Drain webhook events that were never marked processed.

    A durable safety net for events whose in-request background task failed or
    never ran. Storing is idempotent, so re-processing is safe. The caller owns
    the transaction (commit/rollback).
    """
    events = await fetch_unprocessed_events(session, limit=batch_size)
    for event in events:
        messages = iter_incoming_messages(event.payload)
        await store_incoming_messages(session, messages)
        await mark_event_processed(session, event_id=event.id)
    # ponytail: this recovery path stores messages durably but does NOT run the
    # FSM for them (auto-reply runs only on the in-request path). Triggering the
    # FSM for events the API missed entirely is a deferred robustness item.
    if events:
        logger.info("worker_processed_events", extra={"events_processed": len(events)})
    return len(events)
