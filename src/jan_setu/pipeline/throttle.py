"""Global rate limiting shared by every throttled external provider (Nominatim,
Sarvam, OpenRouter). One row per provider in ``external_rate_limits``, claimed
with ``SELECT ... FOR UPDATE`` + compare-and-set so a >=min_interval spacing
holds across all processes, not just within one.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import ExternalRateLimit

logger = logging.getLogger(__name__)


async def reserve_slot(session: AsyncSession, provider: str, min_interval: float) -> float:
    """Reserve the next call slot for ``provider`` and return how long to wait.

    The caller sleeps for the returned duration AFTER this short transaction
    commits (never under lock).
    """
    await session.execute(
        insert(ExternalRateLimit)
        .values(provider=provider, next_allowed_at=utc_now())
        .on_conflict_do_nothing(index_elements=[ExternalRateLimit.provider])
    )
    row = (
        await session.execute(
            select(ExternalRateLimit)
            .where(ExternalRateLimit.provider == provider)
            .with_for_update()
        )
    ).scalar_one()

    now = utc_now()
    slot = max(now, row.next_allowed_at)
    row.next_allowed_at = slot + timedelta(seconds=min_interval)
    await session.commit()
    wait_seconds = max(0.0, (slot - now).total_seconds())
    if wait_seconds > 0:
        waited_ms = round(wait_seconds * 1000, 2)
        logger.debug("throttle_wait_imposed", extra={"provider": provider, "waited_ms": waited_ms})
    return wait_seconds
