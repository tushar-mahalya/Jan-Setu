"""Effective routing: bundled taxonomy profile overlaid with reviewed DB routes.

``DEMO_PROFILE`` is the fallback and ships with ``dispatch_enabled=False`` for
every category -- ``validate_taxonomy`` refuses to import otherwise, so no image
can ever dispatch live by default. A row in ``jurisdiction_routes`` is the
sanctioned override: an explicit operational decision, recorded with who
reviewed it and from when.

Resolution is "live DB row wins, bundled profile otherwise", so a missing row
keeps the safe default and a jurisdiction only dispatches once someone has
written a row saying it may.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db.models import JurisdictionRoute as JurisdictionRouteRow
from jan_setu.pipeline.taxonomy import (
    DEMO_PROFILE,
    TAXONOMY_VERSION,
    JurisdictionRoute,
    canonical_category_key,
)
from jan_setu.repositories.jurisdictions import load_jurisdiction_routes

logger = logging.getLogger(__name__)


def _as_route(row: JurisdictionRouteRow) -> JurisdictionRoute:
    return JurisdictionRoute(
        category_key=row.category_id,
        department_key=row.department_key,
        owning_agency=row.owning_agency,
        sla_hours=row.sla_hours,
        dispatch_enabled=row.dispatch_enabled,
        source_url=row.source_url,
    )


async def resolve_route(
    session: AsyncSession,
    *,
    category_key: str | None,
    jurisdiction_id: str,
    taxonomy_version: str = TAXONOMY_VERSION,
) -> JurisdictionRoute | None:
    """The route actually in force for this category and jurisdiction.

    Returns None only when the category itself is unknown, matching the previous
    ``route_for_category`` contract so callers keep their existing None handling.
    """
    canonical = canonical_category_key(category_key) or ""
    if not canonical:
        return None
    overrides = await load_jurisdiction_routes(
        session, jurisdiction_id=jurisdiction_id, taxonomy_version=taxonomy_version
    )
    row = overrides.get(canonical)
    route = _as_route(row) if row is not None else DEMO_PROFILE.routes.get(canonical)
    if route:
        matched_rule = "override" if row is not None else "bundled"
        logger.info(
            "route_resolved",
            extra={
                "department_key": route.department_key,
                "matched_rule": matched_rule,
            },
        )
    return route
