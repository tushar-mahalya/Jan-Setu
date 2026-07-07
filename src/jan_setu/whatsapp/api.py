import hmac
import logging
from json import JSONDecodeError
from typing import Annotated, Any

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session
from jan_setu.db.models import Contact, WhatsAppMessage
from jan_setu.whatsapp.processing import drive_event
from jan_setu.repositories import (
    list_contacts,
    list_messages,
    store_outgoing_message,
    store_webhook_event,
)
from jan_setu.schemas import ContactRead, MessageRead, SendTextRequest, SendTextResponse
from jan_setu.whatsapp.client import (
    WhatsAppClientUnavailable,
    WhatsAppCloudClient,
    iter_incoming_messages,
    verify_meta_signature,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def is_development_environment(environment: str) -> bool:
    return environment.lower() in {"development", "test"}


def require_api_key(
    app_settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    if app_settings.api_key is None:
        if is_development_environment(app_settings.environment):
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY is required outside development.",
        )
    expected = app_settings.api_key.get_secret_value()
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


def get_whatsapp_client(
    request: Request,
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> WhatsAppCloudClient:
    return WhatsAppCloudClient(
        app_settings,
        http_client=getattr(request.app.state, "http_client", None),
    )


@router.get("/health", tags=["health"])
async def health(app_settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {"status": "ok", "service": "api", "environment": app_settings.environment}


@router.get("/ready", tags=["health"])
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "service": "api"}


@router.get(
    "/v1/contacts",
    response_model=list[ContactRead],
    tags=["contacts"],
    dependencies=[Depends(require_api_key)],
)
async def get_contacts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Contact]:
    return await list_contacts(session, limit=limit, offset=offset)


@router.get(
    "/v1/messages",
    response_model=list[MessageRead],
    tags=["messages"],
    dependencies=[Depends(require_api_key)],
)
async def get_messages(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    wa_id: str | None = None,
) -> list[WhatsAppMessage]:
    return await list_messages(session, limit=limit, wa_id=wa_id)


@router.post(
    "/v1/messages/text",
    response_model=SendTextResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["messages"],
    dependencies=[Depends(require_api_key)],
)
async def send_text_message(
    request: SendTextRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[WhatsAppCloudClient, Depends(get_whatsapp_client)],
) -> SendTextResponse:
    try:
        provider_response = await client.send_text(to=request.to, body=request.body)
    except WhatsAppClientUnavailable as exc:
        logger.warning("whatsapp_client_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "whatsapp_provider_error",
            extra={"provider_status": exc.response.status_code},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "provider_status": exc.response.status_code,
                "provider_body": exc.response.text,
            },
        ) from exc

    provider_messages: list[dict[str, Any]] = provider_response.get("messages", [])
    meta_message_id = provider_messages[0].get("id") if provider_messages else None
    stored_message = await store_outgoing_message(
        session,
        wa_id=request.to,
        meta_message_id=meta_message_id,
        text_body=request.body,
        raw_payload=provider_response,
    )
    await session.commit()
    logger.info("whatsapp_message_sent", extra={"meta_message_id": meta_message_id})
    return SendTextResponse(provider_response=provider_response, stored_message=stored_message)


@router.get("/whatsapp/webhook", tags=["whatsapp"])
async def verify_webhook(
    app_settings: Annotated[Settings, Depends(get_settings)],
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> PlainTextResponse:
    if mode == "subscribe" and verify_token == app_settings.whatsapp_verify_token and challenge:
        return PlainTextResponse(content=challenge)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")


@router.post("/whatsapp/webhook", tags=["whatsapp"])
async def receive_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    app_settings: Annotated[Settings, Depends(get_settings)],
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    if app_settings.whatsapp_app_secret is None and not is_development_environment(
        app_settings.environment
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WHATSAPP_APP_SECRET is required outside development.",
        )

    raw_body = await request.body()
    signature_valid = verify_meta_signature(
        raw_body=raw_body,
        signature_header=x_hub_signature_256,
        app_secret=app_settings.whatsapp_app_secret,
    )
    if not signature_valid:
        logger.warning("whatsapp_webhook_invalid_signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = await request.json()
    except JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be an object",
        )

    # Persist the raw event and acknowledge Meta immediately; the actual message
    # storage and complaint pipeline run off the request path so a slow or
    # failing processor never causes Meta to retry or disable the webhook.
    incoming_messages = iter_incoming_messages(payload)
    event = await store_webhook_event(session, payload=payload, signature_valid=signature_valid)
    await session.commit()

    background_tasks.add_task(drive_event, app_settings, request.app.state.http_client, event.id)

    messages_seen = len(incoming_messages)
    logger.info(
        "whatsapp_webhook_accepted",
        extra={"event_id": str(event.id), "messages_seen": messages_seen},
    )
    return {"status": "accepted", "messages_seen": messages_seen}
