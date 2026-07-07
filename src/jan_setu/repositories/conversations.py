"""Conversation-engine persistence: per-contact locking, FSM idempotency, and
state transitions. Runs under a contact-row lock so the partial unique index
(one active conversation per contact) is never violated.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import Contact, Conversation, FsmMessageConsumption


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
