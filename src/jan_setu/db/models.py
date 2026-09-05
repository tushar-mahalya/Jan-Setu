import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from jan_setu.db.session import Base, utc_now


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


class Grievance(TimestampMixin, Base):
    """A registered citizen complaint. At most one per conversation (the unique
    ``conversation_id`` makes WhatsApp registration idempotent; web-sourced
    grievances have ``conversation_id is None``). ``human_id`` is the
    citizen-facing ticket number (e.g. ``JS-20260625-00001``) from a Postgres
    sequence; the UUID ``id`` is the internal key.

    ``status`` lifecycle: draft -> processing -> awaiting_confirmation ->
    registered -> (dispatching -> submitted) | pending_window -> dispatching ->
    submitted | duplicate | cancelled | dispatch_failed. Every transition is
    also appended to ``grievance_events`` for the audit timeline.
    """

    __tablename__ = "grievances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    human_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), unique=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="whatsapp")

    location_latitude: Mapped[float | None] = mapped_column(Float)
    location_longitude: Mapped[float | None] = mapped_column(Float)
    location_address: Mapped[str | None] = mapped_column(Text)

    # Raw accumulated issue messages from the FSM context (id/type/text/media_id/
    # mime_type per message) — the pipeline's transcribe+combine stage reads this
    # directly rather than re-joining whatsapp_messages.
    issue_messages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    issue_text: Mapped[str | None] = mapped_column(
        Text
    )  # combined typed text + original-language STT
    source_language: Mapped[str | None] = mapped_column(String(16))
    photo_media_id: Mapped[str | None] = mapped_column(String(255))
    photo_path: Mapped[str | None] = mapped_column(Text)
    audio_paths: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    pdf_path: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    category: Mapped[str | None] = mapped_column(String(64))
    department_key: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str | None] = mapped_column(String(16))
    term: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(Float)
    image_match_status: Mapped[str | None] = mapped_column(String(16))
    flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grievances.id", ondelete="SET NULL"), index=True
    )
    window_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dispatch_ref: Mapped[str | None] = mapped_column(String(255))
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # v2 intelligence/routing fields are additive during the compatibility rollout.
    taxonomy_version: Mapped[str | None] = mapped_column(String(32))
    category_id: Mapped[str | None] = mapped_column(String(96), index=True)
    aggregation_key: Mapped[str | None] = mapped_column(String(96), index=True)
    jurisdiction_id: Mapped[str | None] = mapped_column(String(64), index=True)
    safety_level: Mapped[str | None] = mapped_column(String(16))
    asset_scope: Mapped[str | None] = mapped_column(String(16))
    disposition: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str | None] = mapped_column(String(32), index=True)
    policy_version: Mapped[str | None] = mapped_column(String(32))
    routing_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    structured_facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    transcript_metadata: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index("ix_grievances_status", "status"),
        Index("ix_grievances_created_at", "created_at"),
        Index("ix_grievances_category_window", "category", "window_expires_at"),
        Index("ix_grievances_lat_lon", "location_latitude", "location_longitude"),
        # Matches repositories/officials.py:list_scoped_grievances, which always
        # filters on jurisdiction_id and (for department_officer) also on
        # department_key — the officials triage dashboard's main query.
        Index("ix_grievances_jurisdiction_department", "jurisdiction_id", "department_key"),
    )


class GrievanceEvent(Base):
    """Append-only status-history audit trail for one grievance. Drives both the
    web complaint-detail timeline and the WhatsApp ``status`` reply."""

    __tablename__ = "grievance_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grievances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(TimestampMixin, Base):
    """A web-app account. ``phone`` is the WhatsApp-registered number (== the
    ``wa_id`` of the linked ``Contact``) and is the sole login identifier —
    there is no password; identity is proven by the reverse-OTP flow."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), unique=True
    )
    name: Mapped[str | None] = mapped_column(String(255))


class PhoneVerification(Base):
    """A reverse-OTP challenge: the web app shows ``code`` to the user, who
    sends it TO the WhatsApp bot (we cannot message them first). ``code_hash``
    is sha256 of the code — these are short-lived random nonces, not passwords,
    so a fast hash is the correct tool, not bcrypt/argon2."""

    __tablename__ = "phone_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_phone_verifications_phone_created_at", "phone", "created_at"),)


class RefreshToken(Base):
    """A rotating refresh token. ``token_hash`` is sha256 of the raw token sent
    to the client in an httpOnly cookie; the raw value is never stored."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LoginApprovalChallenge(Base):
    """Browser-bound WhatsApp login approval for an existing linked citizen."""

    __tablename__ = "login_approval_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    verifier_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    browser_nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_label: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_message_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    approval_outbound_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("whatsapp_messages.id", ondelete="SET NULL"), index=True
    )
    request_ip_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_login_approval_user_status_requested", "user_id", "status", "requested_at"),
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
    # Lease fields for the unified drive_event claim (the api background task
    # AND the worker sweep both claim through this row-lease, same pattern as
    # outbound sends, so a race between them can no longer drop an event's FSM
    # turns silently).
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # repositories/webhook_events.py:fetch_unprocessed_event_ids scans
        # WHERE processed_at IS NULL ORDER BY created_at. Without this, the
        # plain created_at index still has to walk past every already-
        # processed (oldest-first) row before reaching the small unprocessed
        # tail, degrading as the table grows.
        Index(
            "ix_webhook_events_unprocessed",
            "created_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )


class Jurisdiction(TimestampMixin, Base):
    __tablename__ = "jurisdictions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    geofence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class JurisdictionRoute(TimestampMixin, Base):
    __tablename__ = "jurisdiction_routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jurisdictions.id", ondelete="CASCADE"), index=True
    )
    taxonomy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    category_id: Mapped[str] = mapped_column(String(96), nullable=False)
    department_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owning_agency: Mapped[str] = mapped_column(String(255), nullable=False)
    dispatch_target: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    dispatch_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sla_hours: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "jurisdiction_id",
            "taxonomy_version",
            "category_id",
            name="uq_jurisdiction_route_version_category",
        ),
    )


class GrievanceExtraction(Base):
    __tablename__ = "grievance_extractions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openrouter")
    requested_models: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    actual_model: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    normalized_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    degradation_reason: Mapped[str | None] = mapped_column(String(128))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_type: Mapped[str | None] = mapped_column(String(32))
    accepted_by_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PipelineJob(TimestampMixin, Base):
    __tablename__ = "pipeline_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        # repositories/jobs.py:claim_pipeline_jobs filters status IN (...) AND
        # next_attempt_at <= now, ORDER BY next_attempt_at, on every worker
        # poll. The single-column status index leaves next_attempt_at
        # unindexed within each status, forcing a sort/filter over every job
        # in that status as the table grows.
        Index("ix_pipeline_jobs_status_next_attempt", "status", "next_attempt_at"),
    )


class DispatchOutbox(TimestampMixin, Base):
    __tablename__ = "dispatch_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    routing_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)


class OfficialUser(TimestampMixin, Base):
    __tablename__ = "official_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    jurisdiction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jurisdictions.id", ondelete="RESTRICT"), index=True
    )
    department_keys: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # repositories/officials.py:get_official_by_email looks up by
        # func.lower(email) on every login attempt. The plain unique(email)
        # constraint above is case-sensitive, so it neither serves that query
        # (forcing a seq scan) nor stops two officials being created with
        # emails that differ only by case (e.g. "Foo@x.com" / "foo@x.com"),
        # which would make that lookup raise MultipleResultsFound.
        Index("uq_official_users_email_lower", text("lower(email)"), unique=True),
    )


class OfficialLoginChallenge(Base):
    __tablename__ = "official_login_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    official_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("official_users.id", ondelete="CASCADE"), index=True
    )
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OfficialAuditEvent(Base):
    __tablename__ = "official_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    official_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("official_users.id", ondelete="RESTRICT"), index=True
    )
    grievance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("grievances.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
