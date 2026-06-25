"""Optional background worker that drains unprocessed webhook events.

The API processes webhooks in-request via background tasks. If that fails, or
the API restarts mid-flight, the raw event is still persisted but left
unprocessed (``processed_at IS NULL``). This worker polls for those events and
processes them, so message ingestion is durable rather than best-effort.

Run with: ``uv run jan-setu-worker``.
"""

import asyncio
import logging

from jan_setu.config import configure_logging, get_settings
from jan_setu.database import AsyncSessionLocal
from jan_setu.dispatch import sweep_pending_outbound
from jan_setu.processing import process_pending_events
from jan_setu.whatsapp import WhatsAppCloudClient

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    client = WhatsAppCloudClient(settings)
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "batch_size": settings.worker_batch_size,
        },
    )
    while True:
        async with AsyncSessionLocal() as session:
            try:
                await process_pending_events(session, batch_size=settings.worker_batch_size)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("worker_iteration_failed")

        if settings.auto_reply_enabled:
            async with AsyncSessionLocal() as session:
                try:
                    await sweep_pending_outbound(
                        session, settings, client, limit=settings.worker_batch_size
                    )
                except Exception:
                    await session.rollback()
                    logger.exception("worker_outbound_sweep_failed")
        await asyncio.sleep(settings.worker_poll_seconds)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, log_format=settings.log_format)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker_stopped")
