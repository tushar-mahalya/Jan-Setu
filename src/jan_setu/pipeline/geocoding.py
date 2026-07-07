"""Reverse geocoding with a durable Postgres cache and a global rate limiter.

Coordinates are canonical; the resolved address is only a display hint for the
citizen's confirmation step. The public Nominatim endpoint is dev-only (1 req/s,
no app/bulk traffic) — production must point ``nominatim_base_url`` at a
self-hosted Nominatim/Photon or a paid provider.

This module is meant to run BEFORE the conversation lock is taken: it depends
only on lat/lon, and the throttle wait happens outside any lock and any HTTP call.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings
from jan_setu.db.models import GeocodeCache
from jan_setu.pipeline.throttle import reserve_slot

logger = logging.getLogger(__name__)

CACHE_PRECISION = 5  # decimals; ~1.1m, plenty for caching repeat lookups


@dataclass(frozen=True)
class ReverseGeocode:
    status: str  # "ok" | "empty" | "failed"
    display_address: str | None = None
    address_components: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


class Geocoder(Protocol):
    provider: str

    async def reverse(self, lat: float, lon: float) -> ReverseGeocode: ...


class NominatimGeocoder:
    provider = "nominatim"

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http_client = http_client

    async def reverse(self, lat: float, lon: float) -> ReverseGeocode:
        params = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "addressdetails": 1,
            "accept-language": self.settings.geocoder_language,
        }
        headers = {"User-Agent": self.settings.nominatim_user_agent}
        url = f"{self.settings.nominatim_base_url.rstrip('/')}/reverse"
        timeout = self.settings.geocoder_timeout_seconds
        try:
            if self.http_client is not None:
                response = await self.http_client.get(
                    url, params=params, headers=headers, timeout=timeout
                )
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            logger.warning("geocode_failed", extra={"provider": self.provider})
            return ReverseGeocode(status="failed")

        display = data.get("display_name") if isinstance(data, dict) else None
        if not display:
            return ReverseGeocode(status="empty", raw=data if isinstance(data, dict) else None)
        return ReverseGeocode(
            status="ok",
            display_address=display,
            address_components=data.get("address"),
            raw=data,
        )


def get_geocoder(settings: Settings, http_client: httpx.AsyncClient | None = None) -> Geocoder:
    # ponytail: only Nominatim/OSM implemented; add Photon/paid adapters here when
    # production needs them — the Protocol keeps callers unchanged.
    return NominatimGeocoder(settings, http_client)


async def reverse_geocode_cached(
    session: AsyncSession,
    settings: Settings,
    lat: float,
    lon: float,
    http_client: httpx.AsyncClient | None = None,
) -> ReverseGeocode:
    """Cache-first reverse geocode. Owns its own short transactions — call this
    with a session NOT inside the FSM transaction."""
    provider = settings.geocoder_provider
    lat_round = round(lat, CACHE_PRECISION)
    lon_round = round(lon, CACHE_PRECISION)
    language = settings.geocoder_language

    cached = (
        await session.execute(
            select(GeocodeCache).where(
                GeocodeCache.provider == provider,
                GeocodeCache.lat_round == lat_round,
                GeocodeCache.lon_round == lon_round,
                GeocodeCache.accept_language == language,
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        return ReverseGeocode(
            status=cached.status,
            display_address=cached.display_address,
            address_components=cached.address_components,
            raw=cached.raw,
        )

    wait = await reserve_slot(session, provider, settings.geocoder_min_interval_seconds)
    if wait > 0:
        await asyncio.sleep(wait)

    result = await get_geocoder(settings, http_client).reverse(lat, lon)

    # Only cache deterministic outcomes ("ok"/"empty"); a transient "failed"
    # should be retried next time, not cached.
    if result.status in ("ok", "empty"):
        await session.execute(
            insert(GeocodeCache)
            .values(
                provider=provider,
                lat_round=lat_round,
                lon_round=lon_round,
                accept_language=language,
                status=result.status,
                display_address=result.display_address,
                address_components=result.address_components,
                raw=result.raw,
            )
            .on_conflict_do_nothing()
        )
        await session.commit()
    return result
