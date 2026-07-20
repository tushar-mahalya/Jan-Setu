"""intelligence and official operations foundation

Revision ID: c481a9f70e31
Revises: a992b6951a6b
Create Date: 2026-07-15 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c481a9f70e31"
down_revision: str | None = "a992b6951a6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jurisdictions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("geofence", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "jurisdiction_routes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("jurisdiction_id", sa.String(64), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("category_id", sa.String(96), nullable=False),
        sa.Column("department_key", sa.String(64), nullable=False),
        sa.Column("owning_agency", sa.String(255), nullable=False),
        sa.Column("dispatch_target", postgresql.JSONB(), nullable=True),
        sa.Column("dispatch_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["jurisdiction_id"], ["jurisdictions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "jurisdiction_id",
            "taxonomy_version",
            "category_id",
            name="uq_jurisdiction_route_version_category",
        ),
    )
    op.create_index(
        "ix_jurisdiction_routes_jurisdiction_id", "jurisdiction_routes", ["jurisdiction_id"]
    )

    grievance_columns = (
        sa.Column("taxonomy_version", sa.String(32), nullable=True),
        sa.Column("category_id", sa.String(96), nullable=True),
        sa.Column("aggregation_key", sa.String(96), nullable=True),
        sa.Column("jurisdiction_id", sa.String(64), nullable=True),
        sa.Column("safety_level", sa.String(16), nullable=True),
        sa.Column("asset_scope", sa.String(16), nullable=True),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("review_status", sa.String(32), nullable=True),
        sa.Column("policy_version", sa.String(32), nullable=True),
        sa.Column("routing_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("structured_facts", postgresql.JSONB(), nullable=True),
        sa.Column("transcript_metadata", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in grievance_columns:
        op.add_column("grievances", column)
    for column in ("category_id", "aggregation_key", "jurisdiction_id", "review_status"):
        op.create_index(f"ix_grievances_{column}", "grievances", [column])

    op.create_table(
        "grievance_extractions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("grievance_id", sa.UUID(), nullable=False),
        sa.Column("extraction_version", sa.String(32), nullable=False),
        sa.Column("taxonomy_version", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("requested_models", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("actual_model", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(), nullable=True),
        sa.Column("normalized_result", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("degradation_reason", sa.String(128), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_type", sa.String(32), nullable=True),
        sa.Column("accepted_by_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grievance_id"], ["grievances.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_grievance_extractions_grievance_id", "grievance_extractions", ["grievance_id"]
    )

    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("grievance_id", sa.UUID(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grievance_id"], ["grievances.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pipeline_jobs_grievance_id", "pipeline_jobs", ["grievance_id"])
    op.create_index("ix_pipeline_jobs_status", "pipeline_jobs", ["status"])

    op.create_table(
        "dispatch_outbox",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("grievance_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("routing_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ref", sa.String(255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grievance_id"], ["grievances.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_dispatch_outbox_grievance_id", "dispatch_outbox", ["grievance_id"])
    op.create_index("ix_dispatch_outbox_status", "dispatch_outbox", ["status"])

    op.create_table(
        "official_users",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("jurisdiction_id", sa.String(64), nullable=False),
        sa.Column("department_keys", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["jurisdiction_id"], ["jurisdictions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_official_users_jurisdiction_id", "official_users", ["jurisdiction_id"])

    op.create_table(
        "official_login_challenges",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("official_user_id", sa.UUID(), nullable=True),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["official_user_id"], ["official_users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_official_login_challenges_official_user_id",
        "official_login_challenges",
        ["official_user_id"],
    )
    op.create_index(
        "ix_official_login_challenges_email_hash", "official_login_challenges", ["email_hash"]
    )

    op.create_table(
        "official_audit_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("official_user_id", sa.UUID(), nullable=False),
        sa.Column("grievance_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["official_user_id"], ["official_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["grievance_id"], ["grievances.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_official_audit_events_official_user_id", "official_audit_events", ["official_user_id"]
    )
    op.create_index(
        "ix_official_audit_events_grievance_id", "official_audit_events", ["grievance_id"]
    )

    op.execute(
        """
        INSERT INTO jurisdictions (id, name, taxonomy_version, is_demo, active, created_at, updated_at)
        VALUES ('demo-ulb', 'Demo Municipal Corporation (non-production)', '2026-07-v2', true, true, now(), now())
        """
    )
    op.execute(
        """
        INSERT INTO official_users (
            id, email, name, role, jurisdiction_id, department_keys, active, created_at, updated_at
        ) VALUES (
            '00000000-0000-4000-8000-000000000001',
            'demo-official@example.com',
            'Demo Triage Officer',
            'supervisor',
            'demo-ulb',
            '[]'::jsonb,
            true,
            now(),
            now()
        )
        """
    )


def downgrade() -> None:
    for table in (
        "official_audit_events",
        "official_login_challenges",
        "official_users",
        "dispatch_outbox",
        "pipeline_jobs",
        "grievance_extractions",
        "jurisdiction_routes",
    ):
        op.drop_table(table)
    for column in (
        "state_version",
        "transcript_metadata",
        "structured_facts",
        "routing_snapshot",
        "policy_version",
        "review_status",
        "disposition",
        "asset_scope",
        "safety_level",
        "jurisdiction_id",
        "aggregation_key",
        "category_id",
        "taxonomy_version",
    ):
        op.drop_column("grievances", column)
    op.drop_table("jurisdictions")
