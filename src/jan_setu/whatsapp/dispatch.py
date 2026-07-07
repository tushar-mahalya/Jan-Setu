"""Outbound reply dispatch: claim → 24h gate → send → record.

Replies are persisted as ``pending`` inside the FSM transaction and sent here,
after commit. Both the in-request path and the worker sweep call ``send_pending``;
the atomic claim ensures only one of them sends a given row. ``sent`` means Graph
accepted the message — delivery/read are tracked later via status webhooks.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings
from jan_setu.db import utc_now
from jan_setu.db.models import Conversation, WhatsAppMessage
from jan_setu.repositories import claim_outbound, fetch_sweepable_outbound, mark_outbound
from jan_setu.whatsapp.client import WhatsAppCloudClient, WhatsAppClientUnavailable

logger = logging.getLogger(__name__)

LEASE_SECONDS = 30
MAX_SEND_ATTEMPTS = 5


def _provider_message_id(response: dict[str, Any]) -> str | None:
    messages = response.get("messages") if isinstance(response, dict) else None
    if messages:
        return messages[0].get("id")
    return None


async def send_pending(
    session: AsyncSession,
    settings: Settings,
    client: WhatsAppCloudClient,
    message_id: Any,
) -> str:
    """Claim and send one pending outbound row. Returns the terminal status:
    ``sent`` | ``blocked_24h`` | ``failed`` | ``skipped``."""
    if not await claim_outbound(session, message_id=message_id, lease_seconds=LEASE_SECONDS):
        await session.commit()
        return "skipped"  # another sender holds the lease

    message = await session.get(WhatsAppMessage, message_id)
    if message is None:
        await session.commit()
        return "skipped"

    # Give up on a reply that keeps failing rather than retrying it forever every
    # time its lease expires. claim_outbound already incremented attempt_count.
    if message.attempt_count > MAX_SEND_ATTEMPTS:
        await mark_outbound(session, message_id=message_id, status="failed")
        await session.commit()
        logger.warning(
            "outbound_giving_up",
            extra={"reply_kind": message.reply_kind, "attempts": message.attempt_count},
        )
        return "failed"

    # Send-time 24h gate: a stuck/late reply outside the customer-service window
    # would be rejected by Graph (error 131047), so park it as blocked_24h instead.
    window_expiry = (
        await session.execute(
            select(Conversation.service_window_expires_at).where(
                Conversation.id == message.conversation_id
            )
        )
    ).scalar_one_or_none()
    if window_expiry is not None and utc_now() > window_expiry:
        await mark_outbound(session, message_id=message_id, status="blocked_24h")
        await session.commit()
        logger.warning("outbound_blocked_24h", extra={"reply_kind": message.reply_kind})
        return "blocked_24h"

    payload = message.raw_payload
    # Commit the lease before the HTTP call so the send is durable and visible to
    # other senders. This is at-least-once: a crash after Graph receives the
    # message but before we mark it 'sent' can resend on the next sweep. Acceptable
    # for slice 1; a client-side idempotency key is the upgrade path.
    await session.commit()

    try:
        response = await client.send_raw(payload)
    except (httpx.HTTPError, WhatsAppClientUnavailable):
        # Leave the lease to expire; the worker sweep retries it.
        await mark_outbound(session, message_id=message_id, status="pending")
        await session.commit()
        logger.warning("outbound_send_failed", extra={"reply_kind": message.reply_kind})
        return "failed"

    await mark_outbound(
        session,
        message_id=message_id,
        status="sent",
        meta_message_id=_provider_message_id(response),
    )
    await session.commit()
    return "sent"


async def sweep_pending_outbound(
    session: AsyncSession,
    settings: Settings,
    client: WhatsAppCloudClient,
    *,
    limit: int,
) -> int:
    """Send replies that were persisted but never sent (crash after commit) and
    re-send those whose lease expired. Returns how many rows were attempted."""
    rows = await fetch_sweepable_outbound(session, limit=limit)
    for row in rows:
        await send_pending(session, settings, client, row.id)
    return len(rows)
