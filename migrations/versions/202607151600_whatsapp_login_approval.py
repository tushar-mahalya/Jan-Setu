"""WhatsApp login approval challenges

Revision ID: d72f06a81c44
Revises: c481a9f70e31
Create Date: 2026-07-15 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d72f06a81c44"
down_revision: str | None = "c481a9f70e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_approval_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("verifier_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_label", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_message_id", sa.String(length=255), nullable=True),
        sa.Column("approval_outbound_message_id", sa.UUID(), nullable=True),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["approval_outbound_message_id"], ["whatsapp_messages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_message_id"),
        sa.UniqueConstraint("verifier_hash"),
    )
    op.create_index(
        "ix_login_approval_challenges_user_id", "login_approval_challenges", ["user_id"]
    )
    op.create_index(
        "ix_login_approval_challenges_contact_id", "login_approval_challenges", ["contact_id"]
    )
    op.create_index("ix_login_approval_challenges_status", "login_approval_challenges", ["status"])
    op.create_index(
        "ix_login_approval_challenges_expires_at", "login_approval_challenges", ["expires_at"]
    )
    op.create_index(
        "ix_login_approval_challenges_approval_outbound_message_id",
        "login_approval_challenges",
        ["approval_outbound_message_id"],
    )
    op.create_index(
        "ix_login_approval_user_status_requested",
        "login_approval_challenges",
        ["user_id", "status", "requested_at"],
    )


def downgrade() -> None:
    op.drop_table("login_approval_challenges")
