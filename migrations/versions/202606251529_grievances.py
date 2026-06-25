"""grievances

Revision ID: 1fd85bbfe004
Revises: e280b336d745
Create Date: 2026-06-25 15:29:44.705489
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1fd85bbfe004"
down_revision: str | None = "e280b336d745"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sequence backing the human-readable grievance id (JS-YYYYMMDD-NNNNN).
    op.execute("CREATE SEQUENCE IF NOT EXISTS grievance_human_seq")
    op.create_table(
        "grievances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("human_id", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("location_latitude", sa.Float(), nullable=True),
        sa.Column("location_longitude", sa.Float(), nullable=True),
        sa.Column("location_address", sa.Text(), nullable=True),
        sa.Column("issue_message_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issue_text", sa.Text(), nullable=True),
        sa.Column("photo_media_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_grievances_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_grievances_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grievances")),
        sa.UniqueConstraint("conversation_id", name=op.f("uq_grievances_conversation_id")),
        sa.UniqueConstraint("human_id", name=op.f("uq_grievances_human_id")),
    )
    op.create_index(op.f("ix_grievances_contact_id"), "grievances", ["contact_id"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f("ix_grievances_contact_id"), table_name="grievances")
    op.drop_table("grievances")
    op.execute("DROP SEQUENCE IF EXISTS grievance_human_seq")
