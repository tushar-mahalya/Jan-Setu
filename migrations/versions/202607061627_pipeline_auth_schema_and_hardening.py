"""pipeline auth schema and hardening

Revision ID: a992b6951a6b
Revises: 1fd85bbfe004
Create Date: 2026-07-06 16:27:54.165893
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a992b6951a6b"
down_revision: str | None = "1fd85bbfe004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_users_contact_id_contacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("contact_id", name=op.f("uq_users_contact_id")),
        sa.UniqueConstraint("phone", name=op.f("uq_users_phone")),
    )

    op.create_table(
        "phone_verifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_phone_verifications_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_verifications")),
    )
    op.create_index(
        op.f("ix_phone_verifications_code_hash"), "phone_verifications", ["code_hash"], unique=False
    )
    op.create_index(
        "ix_phone_verifications_phone_created_at",
        "phone_verifications",
        ["phone", "created_at"],
        unique=False,
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "grievance_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("grievance_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["grievance_id"],
            ["grievances.id"],
            name=op.f("fk_grievance_events_grievance_id_grievances"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grievance_events")),
    )
    op.create_index(
        op.f("ix_grievance_events_grievance_id"), "grievance_events", ["grievance_id"], unique=False
    )

    # --- grievances: new columns ---------------------------------------
    op.add_column("grievances", sa.Column("user_id", sa.UUID(), nullable=True))

    # source/issue_messages/audio_paths/flags/report_count/dispatch_attempts are
    # NOT NULL. Add with a server_default so existing rows backfill, then drop
    # the default so the schema matches the models (which use Python-side
    # defaults only) and alembic check stays clean.
    op.add_column(
        "grievances",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="whatsapp"),
    )
    op.alter_column("grievances", "source", server_default=None)

    op.add_column(
        "grievances",
        sa.Column(
            "issue_messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("grievances", "issue_messages", server_default=None)

    op.add_column("grievances", sa.Column("source_language", sa.String(length=16), nullable=True))
    op.add_column("grievances", sa.Column("photo_path", sa.Text(), nullable=True))

    op.add_column(
        "grievances",
        sa.Column(
            "audio_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("grievances", "audio_paths", server_default=None)

    op.add_column("grievances", sa.Column("pdf_path", sa.Text(), nullable=True))
    op.add_column("grievances", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("grievances", sa.Column("department_key", sa.String(length=64), nullable=True))
    op.add_column("grievances", sa.Column("priority", sa.String(length=16), nullable=True))
    op.add_column("grievances", sa.Column("term", sa.String(length=16), nullable=True))
    op.add_column("grievances", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "grievances", sa.Column("image_match_status", sa.String(length=16), nullable=True)
    )

    op.add_column(
        "grievances",
        sa.Column(
            "flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("grievances", "flags", server_default=None)

    op.add_column(
        "grievances",
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("grievances", "report_count", server_default=None)

    op.add_column("grievances", sa.Column("duplicate_of_id", sa.UUID(), nullable=True))
    op.add_column(
        "grievances", sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("grievances", sa.Column("dispatch_ref", sa.String(length=255), nullable=True))

    op.add_column(
        "grievances",
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("grievances", "dispatch_attempts", server_default=None)

    op.add_column("grievances", sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "grievances", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # status is widened (16 -> 32) and repurposed; already NOT NULL with
    # existing values, so a plain type change is sufficient (no backfill).
    op.alter_column(
        "grievances",
        "status",
        existing_type=sa.VARCHAR(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

    op.create_index(
        "ix_grievances_category_window",
        "grievances",
        ["category", "window_expires_at"],
        unique=False,
    )
    op.create_index("ix_grievances_created_at", "grievances", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_grievances_duplicate_of_id"), "grievances", ["duplicate_of_id"], unique=False
    )
    op.create_index(
        "ix_grievances_lat_lon",
        "grievances",
        ["location_latitude", "location_longitude"],
        unique=False,
    )
    op.create_index("ix_grievances_status", "grievances", ["status"], unique=False)
    op.create_index(op.f("ix_grievances_user_id"), "grievances", ["user_id"], unique=False)

    op.create_foreign_key(
        op.f("fk_grievances_duplicate_of_id_grievances"),
        "grievances",
        "grievances",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_grievances_user_id_users"),
        "grievances",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_column("grievances", "issue_message_ids")

    # --- webhook_events: lease fields for the unified drive_event claim -
    op.add_column(
        "webhook_events",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("webhook_events", "attempt_count", server_default=None)
    op.add_column(
        "webhook_events", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("webhook_events", "locked_until")
    op.drop_column("webhook_events", "attempt_count")

    # Re-add the column removed in upgrade(). Use the same temporary
    # server_default technique as upgrade() so downgrading a table that
    # already has rows (e.g. a real rollback in production) doesn't violate
    # NOT NULL.
    op.add_column(
        "grievances",
        sa.Column(
            "issue_message_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("grievances", "issue_message_ids", server_default=None)

    op.drop_constraint(op.f("fk_grievances_user_id_users"), "grievances", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_grievances_duplicate_of_id_grievances"), "grievances", type_="foreignkey"
    )

    op.drop_index(op.f("ix_grievances_user_id"), table_name="grievances")
    op.drop_index("ix_grievances_status", table_name="grievances")
    op.drop_index("ix_grievances_lat_lon", table_name="grievances")
    op.drop_index(op.f("ix_grievances_duplicate_of_id"), table_name="grievances")
    op.drop_index("ix_grievances_created_at", table_name="grievances")
    op.drop_index("ix_grievances_category_window", table_name="grievances")

    op.alter_column(
        "grievances",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.VARCHAR(length=16),
        existing_nullable=False,
    )

    op.drop_column("grievances", "confirmed_at")
    op.drop_column("grievances", "drafted_at")
    op.drop_column("grievances", "dispatch_attempts")
    op.drop_column("grievances", "dispatch_ref")
    op.drop_column("grievances", "window_expires_at")
    op.drop_column("grievances", "duplicate_of_id")
    op.drop_column("grievances", "report_count")
    op.drop_column("grievances", "flags")
    op.drop_column("grievances", "image_match_status")
    op.drop_column("grievances", "confidence")
    op.drop_column("grievances", "term")
    op.drop_column("grievances", "priority")
    op.drop_column("grievances", "department_key")
    op.drop_column("grievances", "category")
    op.drop_column("grievances", "pdf_path")
    op.drop_column("grievances", "audio_paths")
    op.drop_column("grievances", "photo_path")
    op.drop_column("grievances", "source_language")
    op.drop_column("grievances", "issue_messages")
    op.drop_column("grievances", "source")
    op.drop_column("grievances", "user_id")

    op.drop_index(op.f("ix_grievance_events_grievance_id"), table_name="grievance_events")
    op.drop_table("grievance_events")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_phone_verifications_phone_created_at", table_name="phone_verifications")
    op.drop_index(op.f("ix_phone_verifications_code_hash"), table_name="phone_verifications")
    op.drop_table("phone_verifications")

    op.drop_table("users")
