"""Webhook event durability: store, lease-claim, and sweep unprocessed events.

``claim_event`` is the same row-lease compare-and-set pattern as
``claim_outbound`` — it is what lets both the in-request BackgroundTask and the
worker sweep drive the same event without double-processing it.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import WebhookEvent


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
        update(WebhookEvent)
        .where(WebhookEvent.id == event_id)
        .values(processed_at=utc_now(), locked_until=None)
    )


async def claim_event(
    session: AsyncSession, *, event_id: Any, lease_seconds: int
) -> dict[str, Any] | None:
    """Atomically lease an unprocessed webhook event for driving. Returns the
    event payload + attempt count if this caller won the claim, else ``None``."""
    now = utc_now()
    result = await session.execute(
        update(WebhookEvent)
        .where(
            WebhookEvent.id == event_id,
            WebhookEvent.processed_at.is_(None),
            (WebhookEvent.locked_until.is_(None)) | (WebhookEvent.locked_until < now),
        )
        .values(
            locked_until=now + timedelta(seconds=lease_seconds),
            attempt_count=WebhookEvent.attempt_count + 1,
        )
        .returning(WebhookEvent.payload, WebhookEvent.attempt_count)
    )
    row = result.one_or_none()
    if row is None:
        return None
    payload, attempt_count = row
    return {"payload": payload, "attempt_count": attempt_count}


async def fetch_unprocessed_event_ids(session: AsyncSession, *, limit: int) -> list[Any]:
    now = utc_now()
    result = await session.execute(
        select(WebhookEvent.id)
        .where(
            WebhookEvent.processed_at.is_(None),
            (WebhookEvent.locked_until.is_(None)) | (WebhookEvent.locked_until < now),
        )
        .order_by(WebhookEvent.created_at)
        .limit(limit)
    )
    return list(result.scalars().all())
