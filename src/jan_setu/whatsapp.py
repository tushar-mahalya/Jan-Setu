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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_text(self, *, to: str, body: str) -> dict[str, Any]:
        if not self.settings.whatsapp_access_token or not self.settings.whatsapp_phone_number_id:
            raise WhatsAppClientUnavailable(
                "WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required."
            )

        token = self.settings.whatsapp_access_token.get_secret_value()
        url = (
            f"https://graph.facebook.com/{self.settings.whatsapp_graph_api_version}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()


@dataclass(frozen=True)
class IncomingWhatsAppMessage:
    wa_id: str
    profile_name: str | None
    meta_message_id: str
    message_type: str
    text_body: str | None
    raw_payload: dict[str, Any]
    received_at: datetime


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

    secret_value = app_secret.get_secret_value() if isinstance(app_secret, SecretStr) else app_secret
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
                text_body = message.get("text", {}).get("body") if message_type == "text" else None
                messages.append(
                    IncomingWhatsAppMessage(
                        wa_id=wa_id,
                        profile_name=contact_names.get(wa_id),
                        meta_message_id=meta_message_id,
                        message_type=message_type,
                        text_body=text_body,
                        raw_payload=message,
                        received_at=parse_whatsapp_timestamp(message.get("timestamp")),
                    )
                )
    return messages