"""Enable (or disable) live department dispatch for a jurisdiction.

The bundled taxonomy ships with dispatch off everywhere and refuses to import
otherwise, so turning it on is deliberately a data decision recorded in
``jurisdiction_routes`` -- with who reviewed it and from when -- rather than a
constant in the image.

    # local demo: every category dispatches, mail lands in Mailpit
    python scripts/seed_jurisdiction_routes.py --enable --reviewed-by you@example.com

    # narrow it to a couple of categories
    python scripts/seed_jurisdiction_routes.py --enable --category pothole_surface_damage \
        --category streetlight_out --reviewed-by you@example.com

    # turn it back off (rows stay, so the audit trail survives)
    python scripts/seed_jurisdiction_routes.py --disable

Refuses to run against staging/production: those jurisdictions route to real
municipal inboxes and must be reviewed through a real change process.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jan_setu.config import Settings
from jan_setu.db import utc_now
from jan_setu.db.models import Jurisdiction, JurisdictionRoute
from jan_setu.pipeline.taxonomy import (
    DEMO_JURISDICTION_ID,
    DEMO_PROFILE,
    TAXONOMY_VERSION,
)


def _database_url(settings: Settings) -> str:
    if settings.database_url:
        return settings.database_url
    password = settings.postgres_password.get_secret_value()
    return (
        f"postgresql+asyncpg://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


async def _seed(session: AsyncSession, *, jurisdiction_id, categories, enabled, reviewed_by) -> int:
    if not await session.get(Jurisdiction, jurisdiction_id):
        raise SystemExit(f"Unknown jurisdiction {jurisdiction_id!r} -- seed it first.")

    known = set(DEMO_PROFILE.routes)
    unknown = sorted(set(categories) - known) if categories else []
    if unknown:
        raise SystemExit(f"Unknown categories: {', '.join(unknown)}")
    targets = sorted(categories) if categories else sorted(known)

    now = utc_now()
    for key in targets:
        base = DEMO_PROFILE.routes[key]
        stmt = insert(JurisdictionRoute).values(
            jurisdiction_id=jurisdiction_id,
            taxonomy_version=TAXONOMY_VERSION,
            category_id=key,
            department_key=base.department_key,
            owning_agency=base.owning_agency,
            sla_hours=base.sla_hours,
            dispatch_enabled=enabled,
            reviewed_by=reviewed_by,
            effective_from=now,
            effective_to=None,
        )
        # Re-running must be idempotent and must flip an existing decision,
        # not raise on the (jurisdiction, version, category) unique constraint.
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_jurisdiction_route_version_category",
                set_={
                    "dispatch_enabled": enabled,
                    "reviewed_by": reviewed_by,
                    "effective_from": now,
                    "effective_to": None,
                },
            )
        )
    await session.commit()
    return len(targets)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--enable", action="store_true", help="allow live dispatch")
    mode.add_argument("--disable", action="store_true", help="stop live dispatch")
    parser.add_argument("--jurisdiction", default=DEMO_JURISDICTION_ID)
    parser.add_argument(
        "--category", action="append", default=[], help="repeatable; default is every category"
    )
    parser.add_argument("--reviewed-by", default=None, help="who approved this route")
    args = parser.parse_args(argv)

    settings = Settings()
    if settings.environment not in {"development", "test"}:
        raise SystemExit(
            f"Refusing to run with ENVIRONMENT={settings.environment}. "
            "Live dispatch routes for real jurisdictions need a reviewed change process."
        )
    if args.enable and not args.reviewed_by:
        raise SystemExit("--reviewed-by is required when enabling dispatch.")

    engine = create_async_engine(_database_url(settings))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            count = await _seed(
                session,
                jurisdiction_id=args.jurisdiction,
                categories=args.category,
                enabled=args.enable,
                reviewed_by=args.reviewed_by,
            )
            total = (
                await session.execute(
                    select(JurisdictionRoute).where(
                        JurisdictionRoute.jurisdiction_id == args.jurisdiction,
                        JurisdictionRoute.dispatch_enabled.is_(True),
                    )
                )
            ).scalars()
            verb = "enabled" if args.enable else "disabled"
            print(f"{verb} dispatch on {count} route(s) for {args.jurisdiction}")
            print(f"routes now dispatching live: {len(list(total))}")
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
