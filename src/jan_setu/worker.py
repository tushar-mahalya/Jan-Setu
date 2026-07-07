"""Background worker: drains unprocessed webhook events, sweeps stuck pipeline
stages, and re-sends outbound replies that were persisted but never sent.

The API processes webhooks in-request via a BackgroundTask; this worker is the
durability net for everything that path can miss (API restart mid-flight, a
crashed pipeline stage, an unsent reply after a crash). Run with:
``uv run jan-setu-worker``.
"""

import asyncio
import logging

import httpx

from jan_setu.config import configure_logging, get_settings
from jan_setu.db import AsyncSessionLocal
from jan_setu.pipeline import sweep_expired_windows, sweep_stuck_dispatching
from jan_setu.whatsapp.client import WhatsAppCloudClient
from jan_setu.whatsapp.dispatch import sweep_pending_outbound
from jan_setu.whatsapp.processing import process_pending_events, sweep_stuck_processing

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "batch_size": settings.worker_batch_size,
        },
    )
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        transport=httpx.AsyncHTTPTransport(retries=2),
    ) as http_client:
        client = WhatsAppCloudClient(settings, http_client)
        while True:
            try:
                await process_pending_events(
                    settings, http_client, batch_size=settings.worker_batch_size
                )
            except Exception:
                logger.exception("worker_event_sweep_failed")

            if settings.auto_reply_enabled:
                async with AsyncSessionLocal() as session:
                    try:
                        await sweep_pending_outbound(
                            session, settings, client, limit=settings.worker_batch_size
                        )
                    except Exception:
                        await session.rollback()
                        logger.exception("worker_outbound_sweep_failed")

                try:
                    await sweep_stuck_processing(
                        settings, http_client, limit=settings.worker_batch_size
                    )
                    await sweep_expired_windows(
                        settings, http_client, limit=settings.worker_batch_size
                    )
                    await sweep_stuck_dispatching(
                        settings, http_client, limit=settings.worker_batch_size
                    )
                except Exception:
                    logger.exception("worker_pipeline_sweep_failed")

            await asyncio.sleep(settings.worker_poll_seconds)


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, log_format=settings.log_format)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker_stopped")
