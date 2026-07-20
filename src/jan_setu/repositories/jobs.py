"""Durable claims for grievance pipeline jobs."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import PipelineJob


async def enqueue_pipeline_job(
    session: AsyncSession, *, grievance_id: Any, stage: str = "intelligence", key_suffix: str = ""
) -> None:
    key = f"grievance:{grievance_id}:{stage}{f':{key_suffix}' if key_suffix else ''}"
    await session.execute(
        insert(PipelineJob)
        .values(
            grievance_id=grievance_id,
            stage=stage,
            status="pending",
            idempotency_key=key,
            next_attempt_at=utc_now(),
        )
        .on_conflict_do_nothing(index_elements=[PipelineJob.idempotency_key])
    )


async def claim_pipeline_jobs(
    session: AsyncSession, *, limit: int, lease_seconds: int = 120
) -> list[PipelineJob]:
    now = utc_now()
    rows = list(
        (
            await session.execute(
                select(PipelineJob)
                .where(
                    # "processing" with an expired lease means the worker died
                    # mid-job; reclaim it instead of leaving it stuck forever.
                    PipelineJob.status.in_(["pending", "retry", "processing"]),
                    PipelineJob.next_attempt_at <= now,
                    (PipelineJob.locked_until.is_(None) | (PipelineJob.locked_until < now)),
                    PipelineJob.attempt_count < PipelineJob.max_attempts,
                )
                .order_by(PipelineJob.next_attempt_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).scalars()
    )
    for row in rows:
        row.status = "processing"
        row.locked_until = now + timedelta(seconds=lease_seconds)
        row.attempt_count += 1
    await session.flush()
    return rows


async def complete_pipeline_job(session: AsyncSession, *, job: PipelineJob) -> None:
    job.status = "completed"
    job.locked_until = None
    job.last_error = None
    await session.flush()


async def fail_pipeline_job(session: AsyncSession, *, job: PipelineJob, error: Exception) -> None:
    job.locked_until = None
    job.last_error = f"{type(error).__name__}: {error}"[:2000]
    if job.attempt_count >= job.max_attempts:
        job.status = "dead_letter"
    else:
        job.status = "retry"
        delay_seconds = min(300, 2**job.attempt_count)
        job.next_attempt_at = utc_now() + timedelta(seconds=delay_seconds)
    await session.flush()
