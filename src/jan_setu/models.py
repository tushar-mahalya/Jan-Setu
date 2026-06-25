import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from jan_setu.database import Base, utc_now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    profile_name: Mapped[str | None] = mapped_column(String(255))

    messages: Mapped[list["WhatsAppMessage"]] = relationship(back_populates="contact")


class WhatsAppMessage(TimestampMixin, Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    meta_message_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(64), nullable=False)
    text_body: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(String(255))
    media_mime_type: Mapped[str | None] = mapped_column(String(255))
    location_latitude: Mapped[float | None] = mapped_column(Float)
    location_longitude: Mapped[float | None] = mapped_column(Float)
    location_name: Mapped[str | None] = mapped_column(String(255))
    location_address: Mapped[str | None] = mapped_column(Text)
    location_url: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )

    # Interactive-reply fields parsed from inbound webhooks (button/list taps).
    # reply_id is the stable button/list id the FSM branches on; context_message_id
    # is the wamid this reply targets (Meta's message.context.id).
    reply_id: Mapped[str | None] = mapped_column(String(256))
    interactive_type: Mapped[str | None] = mapped_column(String(32))
    button_payload: Mapped[str | None] = mapped_column(Text)
    context_message_id: Mapped[str | None] = mapped_column(String(255))

    # Outbound dispatch state machine. status: received (inbound) | pending |
    # sending | sent | failed | blocked_24h. "sent" means accepted by Graph, not
    # delivered. idempotency_key makes replays collide instead of double-sending.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="received")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    reply_kind: Mapped[str | None] = mapped_column(String(32))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    in_response_to_message_id: Mapped[str | None] = mapped_column(String(255))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contact: Mapped[Contact | None] = relationship(back_populates="messages")


class Conversation(TimestampMixin, Base):
    """One guided dialog with a contact. At most one is ``active`` per contact
    (enforced by a partial unique index)."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_user_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_conversations_active_contact",
            "contact_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class FsmMessageConsumption(Base):
    """Idempotency gate + transition log: one row per inbound message the FSM has
    consumed. A replayed inbound collides on ``inbound_message_id`` and is skipped."""

    __tablename__ = "fsm_message_consumptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inbound_message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    state_before: Mapped[str | None] = mapped_column(String(32))
    state_after: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GeocodeCache(Base):
    """Durable cache of reverse-geocode results, keyed by rounded coordinates.
    Geocodes are immutable, so there is no TTL — the cache survives restarts and
    avoids re-billing the provider."""

    __tablename__ = "geocode_cache"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    lat_round: Mapped[float] = mapped_column(Float, primary_key=True)
    lon_round: Mapped[float] = mapped_column(Float, primary_key=True)
    accept_language: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    display_address: Mapped[str | None] = mapped_column(Text)
    address_components: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExternalRateLimit(Base):
    """One row per throttled external provider. Claimed with ``SELECT ... FOR
    UPDATE`` + compare-and-set to enforce a global minimum spacing between calls
    across all processes."""

    __tablename__ = "external_rate_limits"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signature_valid: Mapped[bool] = mapped_column(nullable=False, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
