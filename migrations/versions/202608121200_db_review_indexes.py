"""database review: FK/index and email-case-integrity fixes

Revision ID: 50e84f16c409
Revises: d72f06a81c44
Create Date: 2026-08-12 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "50e84f16c409"
down_revision: str | None = "d72f06a81c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # phone_verifications.user_id is a FK with no index (the one exception to
    # "index every FK" in this schema).
    op.create_index("ix_phone_verifications_user_id", "phone_verifications", ["user_id"])

    # repositories/officials.py:list_scoped_grievances always filters on
    # jurisdiction_id, and additionally on department_key for
    # department_officer role — the officials triage dashboard's main query.
    op.create_index(
        "ix_grievances_jurisdiction_department",
        "grievances",
        ["jurisdiction_id", "department_key"],
    )

    # repositories/officials.py:get_official_by_email looks up by
    # func.lower(email). The plain unique(email) constraint is case-sensitive,
    # so it neither serves that query nor stops two officials being created
    # with emails differing only by case, which would make that lookup raise
    # MultipleResultsFound.
    op.create_index(
        "uq_official_users_email_lower",
        "official_users",
        [sa.text("lower(email)")],
        unique=True,
    )

    # repositories/webhook_events.py:fetch_unprocessed_event_ids scans WHERE
    # processed_at IS NULL ORDER BY created_at.
    op.create_index(
        "ix_webhook_events_unprocessed",
        "webhook_events",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    # repositories/jobs.py:claim_pipeline_jobs filters status IN (...) AND
    # next_attempt_at <= now, ORDER BY next_attempt_at, on every worker poll.
    op.create_index(
        "ix_pipeline_jobs_status_next_attempt",
        "pipeline_jobs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_jobs_status_next_attempt", table_name="pipeline_jobs")
    op.drop_index("ix_webhook_events_unprocessed", table_name="webhook_events")
    op.drop_index("uq_official_users_email_lower", table_name="official_users")
    op.drop_index("ix_grievances_jurisdiction_department", table_name="grievances")
    op.drop_index("ix_phone_verifications_user_id", table_name="phone_verifications")
