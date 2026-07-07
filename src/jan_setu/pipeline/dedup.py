"""Duplicate-complaint detection for the non-priority dedup window.

A bounding-box prefilter (``find_dedup_candidates`` in repositories.py, backed
by the ``(category, window_expires_at)`` and lat/lon indexes) narrows to a
handful of rows; ``haversine_m`` then does the exact distance check in Python.
No PostGIS — candidate sets are tens of rows at demo scale.
"""

import math
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.db.models import Grievance
from jan_setu.repositories import find_dedup_candidates

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class DuplicateMatch:
    master: Grievance
    distance_m: float


async def find_duplicate(
    session: AsyncSession,
    *,
    category: str,
    lat: float | None,
    lon: float | None,
    radius_m: float,
    exclude_grievance_id: str | None = None,
) -> DuplicateMatch | None:
    if lat is None or lon is None:
        return None
    candidates = await find_dedup_candidates(
        session,
        category=category,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        exclude_grievance_id=exclude_grievance_id,
    )
    best: DuplicateMatch | None = None
    for candidate in candidates:
        if candidate.location_latitude is None or candidate.location_longitude is None:
            continue
        distance = haversine_m(lat, lon, candidate.location_latitude, candidate.location_longitude)
        if distance <= radius_m and (best is None or distance < best.distance_m):
            best = DuplicateMatch(master=candidate, distance_m=distance)
    return best
