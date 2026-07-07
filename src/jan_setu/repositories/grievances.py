"""Grievance lifecycle persistence: draft creation, field/status updates, the
status-history audit trail, dedup-window candidate lookup, listings, and the
recovery sweeps (expired dedup windows, stuck dispatch, stuck pipeline runs).
"""

import math
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import Grievance, GrievanceEvent


async def create_draft_grievance(
    session: AsyncSession,
    *,
    contact_id: Any,
    conversation_id: Any,
    user_id: Any | None,
    source: str,
    context: dict[str, Any],
) -> tuple[Grievance, bool]:
    """Register a draft grievance from the conversation context. Idempotent on
    ``conversation_id`` (unique) — a replay returns the existing draft with its
    original human id. Returns (grievance, created)."""
    location = context.get("location", {})
    issue = context.get("issue", {})
    photo = context.get("photo", {})

    sequence = (await session.execute(text("SELECT nextval('grievance_human_seq')"))).scalar_one()
    human_id = f"JS-{utc_now():%Y%m%d}-{int(sequence):05d}"

    statement = (
        insert(Grievance)
        .values(
            human_id=human_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            user_id=user_id,
            source=source,
            location_latitude=location.get("lat"),
            location_longitude=location.get("lon"),
            location_address=location.get("display_address"),
            issue_messages=issue.get("messages", []),
            photo_media_id=photo.get("media_id"),
            status="draft",
            drafted_at=utc_now(),
        )
        .on_conflict_do_nothing(index_elements=[Grievance.conversation_id])
        .returning(Grievance)
    )
    grievance = (await session.execute(statement)).scalar_one_or_none()
    if grievance is not None:
        return grievance, True

    existing = (
        await session.execute(select(Grievance).where(Grievance.conversation_id == conversation_id))
    ).scalar_one()
    return existing, False


async def get_grievance(session: AsyncSession, *, grievance_id: Any) -> Grievance | None:
    return await session.get(Grievance, grievance_id)


async def set_grievance_fields(
    session: AsyncSession, *, grievance_id: Any, **fields: Any
) -> Grievance:
    grievance = await session.get(Grievance, grievance_id)
    if grievance is None:
        raise ValueError(f"grievance {grievance_id} not found")
    for key, value in fields.items():
        setattr(grievance, key, value)
    await session.flush()
    return grievance


async def add_grievance_event(
    session: AsyncSession, *, grievance_id: Any, status: str, note: str | None = None
) -> GrievanceEvent:
    event = GrievanceEvent(grievance_id=grievance_id, status=status, note=note)
    session.add(event)
    await session.flush()
    return event


async def list_grievance_events(
    session: AsyncSession, *, grievance_id: Any
) -> list[GrievanceEvent]:
    result = await session.execute(
        select(GrievanceEvent)
        .where(GrievanceEvent.grievance_id == grievance_id)
        .order_by(GrievanceEvent.created_at)
    )
    return list(result.scalars().all())


async def find_dedup_candidates(
    session: AsyncSession,
    *,
    category: str,
    lat: float,
    lon: float,
    radius_m: float,
    exclude_grievance_id: Any | None = None,
) -> list[Grievance]:
    """Bounding-box prefilter for dedup: pending-window grievances in the same
    category whose window hasn't expired. Exact distance (haversine) is checked
    by the caller (pipeline/dedup.py) on this small candidate set — no PostGIS
    needed at demo scale."""
    delta_lat = radius_m / 111_320
    delta_lon = radius_m / (111_320 * max(0.1, abs(math.cos(math.radians(lat)))))
    conditions = [
        Grievance.category == category,
        Grievance.status == "pending_window",
        Grievance.window_expires_at > utc_now(),
        Grievance.location_latitude.between(lat - delta_lat, lat + delta_lat),
        Grievance.location_longitude.between(lon - delta_lon, lon + delta_lon),
    ]
    if exclude_grievance_id is not None:
        conditions.append(Grievance.id != exclude_grievance_id)
    result = await session.execute(select(Grievance).where(*conditions))
    return list(result.scalars().all())


async def list_grievances_for_contact(
    session: AsyncSession, *, contact_id: Any, limit: int = 5
) -> list[Grievance]:
    result = await session.execute(
        select(Grievance)
        .where(Grievance.contact_id == contact_id)
        .order_by(desc(Grievance.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_grievances_for_user(
    session: AsyncSession, *, user_id: Any, limit: int, offset: int
) -> list[Grievance]:
    result = await session.execute(
        select(Grievance)
        .where(Grievance.user_id == user_id)
        .order_by(desc(Grievance.created_at))
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def fetch_expired_windows(session: AsyncSession, *, limit: int) -> list[Any]:
    result = await session.execute(
        select(Grievance.id)
        .where(Grievance.status == "pending_window", Grievance.window_expires_at <= utc_now())
        .limit(limit)
    )
    return list(result.scalars().all())


async def fetch_stuck_dispatching(session: AsyncSession, *, limit: int) -> list[Any]:
    result = await session.execute(
        select(Grievance.id)
        .where(Grievance.status == "dispatching", Grievance.dispatch_attempts < 5)
        .limit(limit)
    )
    return list(result.scalars().all())


async def fetch_stuck_processing(
    session: AsyncSession, *, older_than: Any, limit: int
) -> list[Any]:
    """Grievances whose pipeline run started (or was queued) but never reached
    awaiting_confirmation/photo_mismatch — e.g. a crash mid-pipeline. Recovery
    is a full re-run rather than a partial resume.

    ponytail: cheap requeue, not partial-resume; fine at demo scale. Add a
    stage-checkpoint column if a real deployment needs to skip completed
    stages on retry.
    """
    result = await session.execute(
        select(Grievance.id)
        .where(Grievance.status.in_(["draft", "processing"]), Grievance.updated_at < older_than)
        .limit(limit)
    )
    return list(result.scalars().all())
