import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request

from jan_setu.api import router
from jan_setu.config import configure_logging, get_settings

settings = get_settings()
configure_logging(settings.log_level, log_format=settings.log_format)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app_settings = get_settings()
    async with httpx.AsyncClient(timeout=app_settings.request_timeout_seconds) as http_client:
        app.state.http_client = http_client
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="Jan Setu API", version="0.1.0", lifespan=lifespan)
    add_request_logging(app)
    app.include_router(router)
    return app


def add_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        started_at = time.perf_counter()
        log_context = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={**log_context, "duration_ms": elapsed_ms(started_at)},
            )
            raise

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                **log_context,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms(started_at),
            },
        )
        return response


def elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)


app = create_app()
