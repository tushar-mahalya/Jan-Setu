from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    media_id: str | None
    media_mime_type: str | None
    location_latitude: float | None
    location_longitude: float | None
    location_name: str | None
    location_address: str | None
    location_url: str | None
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
