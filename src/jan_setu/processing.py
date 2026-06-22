"""Asynchronous processing of WhatsApp webhook payloads.

The webhook endpoint persists the raw event and acknowledges Meta immediately;
the heavier work of storing messages and (later) running the complaint pipeline
happens here, off the request path. This keeps webhook latency low and means a
processing failure never loses the event — it stays unprocessed and can be
replayed.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.database import AsyncSessionLocal
from jan_setu.repositories import (
    fetch_unprocessed_events,
    mark_event_processed,
    store_incoming_messages,
)
from jan_setu.whatsapp import IncomingWhatsAppMessage, iter_incoming_messages

logger = logging.getLogger(__name__)


async def process_webhook_messages(
    event_id: UUID,
    messages: Sequence[IncomingWhatsAppMessage],
) -> None:
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
    # Future: run the complaint pipeline (classify, route, generate a reply)
    # for each newly created message here.


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
    if events:
        logger.info("worker_processed_events", extra={"events_processed": len(events)})
    return len(events)
