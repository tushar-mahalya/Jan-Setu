import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import SecretStr

from jan_setu.config import Settings


class WhatsAppClientUnavailable(RuntimeError):
    pass


class WhatsAppCloudClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http_client = http_client

    async def send_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a fully-formed Graph message payload. The conversation engine
        builds payloads with the ``build_*`` helpers, persists them, then the
        dispatcher sends them verbatim through here."""
        if not self.settings.whatsapp_access_token or not self.settings.whatsapp_phone_number_id:
            raise WhatsAppClientUnavailable(
                "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required."
            )

        token = self.settings.whatsapp_access_token.get_secret_value()
        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_graph_api_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        headers = {"Authorization": f"Bearer {token}"}

        if self.http_client is not None:
            response = await self.http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as http_client:
            response = await http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def send_text(self, *, to: str, body: str) -> dict[str, Any]:
        return await self.send_raw(build_text_payload(to=to, body=body))

    async def send_location_request(self, *, to: str, body: str) -> dict[str, Any]:
        return await self.send_raw(build_location_request_payload(to=to, body=body))

    async def send_reply_buttons(
        self, *, to: str, body: str, buttons: list[tuple[str, str]]
    ) -> dict[str, Any]:
        return await self.send_raw(build_reply_buttons_payload(to=to, body=body, buttons=buttons))


def build_text_payload(*, to: str, body: str) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }


def build_location_request_payload(*, to: str, body: str) -> dict[str, Any]:
    """Interactive message with a native "Send location" button."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "location_request_message",
            "body": {"text": body},
            "action": {"name": "send_location"},
        },
    }


def build_reply_buttons_payload(
    *, to: str, body: str, buttons: list[tuple[str, str]]
) -> dict[str, Any]:
    """Up to 3 reply buttons. ``buttons`` is a list of (id, title)."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": button_id, "title": title}}
                    for button_id, title in buttons
                ]
            },
        },
    }


def build_document_button_payload(
    *,
    to: str,
    header_media_id: str,
    header_filename: str,
    body: str,
    buttons: list[tuple[str, str]],
) -> dict[str, Any]:
    """A reply-buttons message with a document (the PDF summary) as its header,
    so the citizen sees the complaint PDF and Confirm/Cancel in one bubble."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {
                "type": "document",
                "document": {"id": header_media_id, "filename": header_filename},
            },
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": button_id, "title": title}}
                    for button_id, title in buttons
                ]
            },
        },
    }


@dataclass(frozen=True)
class IncomingWhatsAppMessage:
    wa_id: str
    profile_name: str | None
    meta_message_id: str
    message_type: str
    text_body: str | None
    raw_payload: dict[str, Any]
    received_at: datetime
    media_id: str | None = None
    media_mime_type: str | None = None
    location_latitude: float | None = None
    location_longitude: float | None = None
    location_name: str | None = None
    location_address: str | None = None
    location_url: str | None = None
    reply_id: str | None = None
    interactive_type: str | None = None
    button_payload: str | None = None
    context_message_id: str | None = None


def verify_meta_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    app_secret: SecretStr | str | None,
) -> bool:
    if app_secret is None:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    secret_value = (
        app_secret.get_secret_value() if isinstance(app_secret, SecretStr) else app_secret
    )
    digest = hmac.new(
        key=secret_value.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, f"sha256={digest}")


def parse_whatsapp_timestamp(value: str | int | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


MEDIA_MESSAGE_TYPES = frozenset({"image", "audio", "video", "document", "voice", "sticker"})


def _extract_message_content(
    message: dict[str, Any], message_type: str
) -> tuple[str | None, str | None, str | None]:
    """Return (text_body, media_id, media_mime_type) for a WhatsApp message.

    Text bodies and media captions are normalised into ``text_body`` so the
    processing pipeline has a single place to read what the user said.
    """
    if message_type == "text":
        body = message.get("text", {})
        return (body.get("body") if isinstance(body, dict) else None), None, None
    if message_type in MEDIA_MESSAGE_TYPES:
        media = message.get(message_type, {})
        if isinstance(media, dict):
            return media.get("caption"), media.get("id"), media.get("mime_type")
    return None, None, None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_location(
    message: dict[str, Any], message_type: str
) -> tuple[float | None, float | None, str | None, str | None, str | None]:
    if message_type != "location":
        return None, None, None, None, None
    location = message.get("location", {})
    if not isinstance(location, dict):
        return None, None, None, None, None
    return (
        _as_float(location.get("latitude")),
        _as_float(location.get("longitude")),
        location.get("name"),
        location.get("address"),
        location.get("url"),
    )


def _extract_reply(
    message: dict[str, Any], message_type: str
) -> tuple[str | None, str | None, str | None]:
    """Return (reply_id, interactive_type, button_payload) for tap replies.

    Reply-button and list taps arrive as type ``interactive``; template quick
    replies arrive as type ``button``. All are normalised to a single
    ``reply_id`` the FSM can branch on.
    """
    if message_type == "interactive":
        interactive = message.get("interactive", {})
        if not isinstance(interactive, dict):
            return None, None, None
        interactive_type = interactive.get("type")
        reply = interactive.get(interactive_type, {}) if interactive_type else {}
        reply_id = reply.get("id") if isinstance(reply, dict) else None
        return reply_id, interactive_type, None
    if message_type == "button":
        button = message.get("button", {})
        if isinstance(button, dict):
            return button.get("payload"), "button", button.get("payload")
    return None, None, None


def iter_incoming_messages(payload: dict[str, Any]) -> list[IncomingWhatsAppMessage]:
    messages: list[IncomingWhatsAppMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contact_names = {
                contact.get("wa_id"): contact.get("profile", {}).get("name")
                for contact in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                wa_id = message.get("from")
                meta_message_id = message.get("id")
                if not wa_id or not meta_message_id:
                    continue

                message_type = message.get("type", "unknown")
                text_body, media_id, media_mime_type = _extract_message_content(
                    message, message_type
                )
                latitude, longitude, location_name, location_address, location_url = (
                    _extract_location(message, message_type)
                )
                reply_id, interactive_type, button_payload = _extract_reply(message, message_type)
                context = message.get("context", {})
                context_message_id = context.get("id") if isinstance(context, dict) else None
                messages.append(
                    IncomingWhatsAppMessage(
                        wa_id=wa_id,
                        profile_name=contact_names.get(wa_id),
                        meta_message_id=meta_message_id,
                        message_type=message_type,
                        text_body=text_body,
                        raw_payload=message,
                        received_at=parse_whatsapp_timestamp(message.get("timestamp")),
                        media_id=media_id,
                        media_mime_type=media_mime_type,
                        location_latitude=latitude,
                        location_longitude=longitude,
                        location_name=location_name,
                        location_address=location_address,
                        location_url=location_url,
                        reply_id=reply_id,
                        interactive_type=interactive_type,
                        button_payload=button_payload,
                        context_message_id=context_message_id,
                    )
                )
    return messages
