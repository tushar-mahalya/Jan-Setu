"""conversation engine

Revision ID: e280b336d745
Revises: 9d5942d5f4db
Create Date: 2026-06-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e280b336d745"
down_revision: str | None = "9d5942d5f4db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_user_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("service_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_conversations_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(
        op.f("ix_conversations_contact_id"), "conversations", ["contact_id"], unique=False
    )
    # One active conversation per contact.
    op.create_index(
        "uq_conversations_active_contact",
        "conversations",
        ["contact_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "fsm_message_consumptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("inbound_message_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("state_before", sa.String(length=32), nullable=True),
        sa.Column("state_after", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_fsm_message_consumptions_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fsm_message_consumptions")),
        sa.UniqueConstraint(
            "inbound_message_id",
            name=op.f("uq_fsm_message_consumptions_inbound_message_id"),
        ),
    )
    op.create_index(
        op.f("ix_fsm_message_consumptions_conversation_id"),
        "fsm_message_consumptions",
        ["conversation_id"],
        unique=False,
    )

    op.create_table(
        "geocode_cache",
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("lat_round", sa.Float(), nullable=False),
        sa.Column("lon_round", sa.Float(), nullable=False),
        sa.Column("accept_language", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("display_address", sa.Text(), nullable=True),
        sa.Column("address_components", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "provider",
            "lat_round",
            "lon_round",
            "accept_language",
            name=op.f("pk_geocode_cache"),
        ),
    )

    op.create_table(
        "external_rate_limits",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider", name=op.f("pk_external_rate_limits")),
    )

    op.add_column("whatsapp_messages", sa.Column("reply_id", sa.String(length=256), nullable=True))
    op.add_column(
        "whatsapp_messages", sa.Column("interactive_type", sa.String(length=32), nullable=True)
    )
    op.add_column("whatsapp_messages", sa.Column("button_payload", sa.Text(), nullable=True))
    op.add_column(
        "whatsapp_messages", sa.Column("context_message_id", sa.String(length=255), nullable=True)
    )
    # status/attempt_count are NOT NULL. Add with a server_default so existing rows
    # backfill, then drop the default so the schema matches the models (which use
    # Python-side defaults only) and alembic check stays clean.
    op.add_column(
        "whatsapp_messages",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="received"),
    )
    op.alter_column("whatsapp_messages", "status", server_default=None)
    op.add_column(
        "whatsapp_messages", sa.Column("idempotency_key", sa.String(length=255), nullable=True)
    )
    op.add_column("whatsapp_messages", sa.Column("reply_kind", sa.String(length=32), nullable=True))
    op.add_column("whatsapp_messages", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column(
        "whatsapp_messages",
        sa.Column("in_response_to_message_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "whatsapp_messages", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "whatsapp_messages",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("whatsapp_messages", "attempt_count", server_default=None)
    op.create_unique_constraint(
        op.f("uq_whatsapp_messages_idempotency_key"),
        "whatsapp_messages",
        ["idempotency_key"],
    )
    op.create_index(
        op.f("ix_whatsapp_messages_conversation_id"),
        "whatsapp_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_whatsapp_messages_conversation_id_conversations"),
        "whatsapp_messages",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_whatsapp_messages_conversation_id_conversations"),
        "whatsapp_messages",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_whatsapp_messages_conversation_id"), table_name="whatsapp_messages")
    op.drop_constraint(
        op.f("uq_whatsapp_messages_idempotency_key"), "whatsapp_messages", type_="unique"
    )
    op.drop_column("whatsapp_messages", "attempt_count")
    op.drop_column("whatsapp_messages", "locked_until")
    op.drop_column("whatsapp_messages", "in_response_to_message_id")
    op.drop_column("whatsapp_messages", "conversation_id")
    op.drop_column("whatsapp_messages", "reply_kind")
    op.drop_column("whatsapp_messages", "idempotency_key")
    op.drop_column("whatsapp_messages", "status")
    op.drop_column("whatsapp_messages", "context_message_id")
    op.drop_column("whatsapp_messages", "button_payload")
    op.drop_column("whatsapp_messages", "interactive_type")
    op.drop_column("whatsapp_messages", "reply_id")

    op.drop_table("external_rate_limits")
    op.drop_table("geocode_cache")
    op.drop_index(
        op.f("ix_fsm_message_consumptions_conversation_id"),
        table_name="fsm_message_consumptions",
    )
    op.drop_table("fsm_message_consumptions")
    op.drop_index("uq_conversations_active_contact", table_name="conversations")
    op.drop_index(op.f("ix_conversations_contact_id"), table_name="conversations")
    op.drop_table("conversations")
