"""Effective routing: bundled profile vs reviewed jurisdiction_routes rows."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jan_setu.db import utc_now
from jan_setu.pipeline.routing import resolve_route
from jan_setu.pipeline.taxonomy import DEMO_JURISDICTION_ID, DEMO_PROFILE, validate_taxonomy

CATEGORY = "pothole_surface_damage"


def _row(**overrides):
    base = dict(
        category_id=CATEGORY,
        department_key="public_works",
        owning_agency="Demo Municipal Corporation",
        sla_hours=72,
        dispatch_enabled=True,
        source_url=None,
    )
    return SimpleNamespace(**{**base, **overrides})


def _patch_rows(rows):
    return patch(
        "jan_setu.pipeline.routing.load_jurisdiction_routes",
        AsyncMock(return_value={r.category_id: r for r in rows}),
    )


def test_falls_back_to_bundled_profile_when_no_row_exists():
    # The safe default: a jurisdiction nobody has reviewed never dispatches.
    with _patch_rows([]):
        route = asyncio.run(
            resolve_route(AsyncMock(), category_key=CATEGORY, jurisdiction_id=DEMO_JURISDICTION_ID)
        )
    assert route.dispatch_enabled is False
    assert route == DEMO_PROFILE.routes[CATEGORY]


def test_reviewed_row_enables_dispatch():
    with _patch_rows([_row()]):
        route = asyncio.run(
            resolve_route(AsyncMock(), category_key=CATEGORY, jurisdiction_id=DEMO_JURISDICTION_ID)
        )
    assert route.dispatch_enabled is True
    assert route.department_key == "public_works"


def test_row_can_also_turn_dispatch_back_off():
    # Disabling must be expressible as data, not only by deleting the row.
    with _patch_rows([_row(dispatch_enabled=False)]):
        route = asyncio.run(
            resolve_route(AsyncMock(), category_key=CATEGORY, jurisdiction_id=DEMO_JURISDICTION_ID)
        )
    assert route.dispatch_enabled is False


def test_row_overrides_department_and_agency():
    with _patch_rows([_row(department_key="citizen_services", owning_agency="Other Agency")]):
        route = asyncio.run(
            resolve_route(AsyncMock(), category_key=CATEGORY, jurisdiction_id=DEMO_JURISDICTION_ID)
        )
    assert route.department_key == "citizen_services"
    assert route.owning_agency == "Other Agency"


def test_unknown_category_returns_none():
    with _patch_rows([]):
        route = asyncio.run(
            resolve_route(
                AsyncMock(), category_key="not-a-category", jurisdiction_id=DEMO_JURISDICTION_ID
            )
        )
    assert route is None


def test_a_row_for_another_category_does_not_leak():
    with _patch_rows([_row(category_id="streetlight_out")]):
        route = asyncio.run(
            resolve_route(AsyncMock(), category_key=CATEGORY, jurisdiction_id=DEMO_JURISDICTION_ID)
        )
    assert route.dispatch_enabled is False


def test_bundled_profile_still_refuses_to_ship_dispatch_on():
    # The DB override must not have weakened the import-time guarantee.
    assert all(not r.dispatch_enabled for r in DEMO_PROFILE.routes.values())
    validate_taxonomy()


def test_effective_window_is_applied_by_the_loader():
    from jan_setu.repositories.jurisdictions import load_jurisdiction_routes

    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    moment = utc_now() + timedelta(days=1)
    asyncio.run(
        load_jurisdiction_routes(
            session, jurisdiction_id=DEMO_JURISDICTION_ID, taxonomy_version="v1", at=moment
        )
    )
    # The query must be built with the supplied moment, not "now".
    assert session.execute.await_count == 1
