"""Jurisdiction routing overrides (data access only).

Rows in ``jurisdiction_routes`` are the sanctioned way to turn live department
dispatch on: the bundled taxonomy ships with dispatch off everywhere and
``validate_taxonomy`` refuses to import otherwise, so enabling it is an explicit,
reviewable data decision (``reviewed_by``, ``effective_from``/``effective_to``).

Merging these rows with the bundled profile is domain logic and lives in
``jan_setu.pipeline.routing`` -- this module stays free of pipeline imports so
the data layer has no cycle back into the domain layer.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db import utc_now
from jan_setu.db.models import JurisdictionRoute


async def load_jurisdiction_routes(
    session: AsyncSession,
    *,
    jurisdiction_id: str,
    taxonomy_version: str,
    at: datetime | None = None,
) -> dict[str, JurisdictionRoute]:
    """Live route overrides for a jurisdiction, keyed by category id.

    Scoped to one taxonomy version -- a route reviewed against an older taxonomy
    must not silently carry over -- and to its effective window, so a route can
    be scheduled or retired without deleting the audit trail.
    """
    moment = at or utc_now()
    rows = (
        (
            await session.execute(
                select(JurisdictionRoute).where(
                    JurisdictionRoute.jurisdiction_id == jurisdiction_id,
                    JurisdictionRoute.taxonomy_version == taxonomy_version,
                    (JurisdictionRoute.effective_from.is_(None))
                    | (JurisdictionRoute.effective_from <= moment),
                    (JurisdictionRoute.effective_to.is_(None))
                    | (JurisdictionRoute.effective_to > moment),
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.category_id: row for row in rows}
