from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings, configure_logging, get_settings
from jan_setu.db import (
    Contact,
    WhatsAppMessage,
    get_session,
    list_contacts,
    list_messages,
    store_incoming_messages,
    store_outgoing_message,
    store_webhook_event,
)
from jan_setu.whatsapp import (
    WhatsAppClientUnavailable,
    WhatsAppCloudClient,
    iter_incoming_messages,
    verify_meta_signature,
)

settings = get_settings()
configure_logging(settings.log_level)


class ContactRead(BaseModel):
    id: UUID
    wa_id: str
    profile_name: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageRead(BaseModel):
    id: UUID
    contact_id: UUID | None
    meta_message_id: str | None
    direction: str
    message_type: str
    text_body: str | None
    raw_payload: dict[str, Any]
    received_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SendTextRequest(BaseModel):
    to: str = Field(min_length=5, max_length=32)
    body: str = Field(min_length=1, max_length=4096)


class SendTextResponse(BaseModel):
    provider_response: dict[str, Any]
    stored_message: MessageRead


router = APIRouter()


@router.get("/health", tags=["health"])
async def health(app_settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {"status": "ok", "service": "api", "environment": app_settings.environment}


@router.get("/ready", tags=["health"])
async def ready(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "service": "api"}


@router.get("/v1/contacts", response_model=list[ContactRead], tags=["contacts"])
async def get_contacts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Contact]:
    return await list_contacts(session, limit=limit, offset=offset)


@router.get("/v1/messages", response_model=list[MessageRead], tags=["messages"])
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
)
async def send_text_message(
    request: SendTextRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> SendTextResponse:
    client = WhatsAppCloudClient(app_settings)
    try:
        provider_response = await client.send_text(to=request.to, body=request.body)
    except WhatsAppClientUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"provider_status": exc.response.status_code, "provider_body": exc.response.text},
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
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    raw_body = await request.body()
    signature_valid = verify_meta_signature(
        raw_body=raw_body,
        signature_header=x_hub_signature_256,
        app_secret=app_settings.whatsapp_app_secret,
    )
    if not signature_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    incoming_messages = iter_incoming_messages(payload)
    await store_webhook_event(session, payload=payload, signature_valid=True)
    stored_messages = await store_incoming_messages(session, incoming_messages)

    await session.commit()
    return {
        "status": "accepted",
        "messages_seen": len(incoming_messages),
        "messages_stored": sum(1 for message in stored_messages if message.created),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Jan Setu API", version="0.1.0")
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("jan_setu.main:app", host="0.0.0.0", port=8000, reload=True)