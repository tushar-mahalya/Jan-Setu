"""WhatsApp media download/upload, and upload validation shared by both the
WhatsApp pipeline and the web API's direct file uploads.

Media URLs returned by the Graph ``/{media_id}`` lookup expire in minutes, so
every download here fetches and saves the bytes immediately — never store the
URL for later use.
"""

import logging
import mimetypes
import uuid
from pathlib import Path

import httpx

from jan_setu.config import Settings

logger = logging.getLogger(__name__)

AUDIO_MIME_TYPES = frozenset(
    {"audio/ogg", "audio/opus", "audio/mpeg", "audio/mp3", "audio/wav", "audio/webm", "audio/mp4"}
)
IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class UploadTooLarge(ValueError):
    pass


class UploadTypeNotAllowed(ValueError):
    pass


def validate_upload(
    *, mime_type: str | None, size_bytes: int, kind: str, settings: Settings
) -> None:
    """Raise if an uploaded file (web form or WhatsApp media) is outside the
    allowed type/size for its kind ("audio" | "image")."""
    allowed = AUDIO_MIME_TYPES if kind == "audio" else IMAGE_MIME_TYPES
    max_bytes = settings.max_audio_bytes if kind == "audio" else settings.max_image_bytes
    if mime_type not in allowed:
        raise UploadTypeNotAllowed(f"{kind} type {mime_type!r} is not allowed")
    if size_bytes > max_bytes:
        raise UploadTooLarge(f"{kind} upload of {size_bytes} bytes exceeds the {max_bytes} limit")


def save_upload(settings: Settings, *, grievance_id: str, name: str, data: bytes) -> str:
    """Write bytes under ``upload_dir/<grievance_id>/<name>`` and return the path."""
    directory = Path(settings.upload_dir) / str(grievance_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return str(path)


async def download_whatsapp_media(
    client: httpx.AsyncClient, settings: Settings, media_id: str
) -> tuple[bytes, str]:
    """Resolve a Graph media id to bytes + mime type. Downloads immediately —
    the resolved URL is short-lived."""
    if not settings.whatsapp_access_token:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN is required to download media.")
    token = settings.whatsapp_access_token.get_secret_value()
    headers = {"Authorization": f"Bearer {token}"}

    lookup_url = f"https://graph.facebook.com/{settings.whatsapp_graph_api_version}/{media_id}"
    lookup = await client.get(lookup_url, headers=headers)
    lookup.raise_for_status()
    info = lookup.json()
    media_url = info["url"]
    mime_type = info.get("mime_type", "application/octet-stream")

    download = await client.get(media_url, headers=headers)
    download.raise_for_status()
    return download.content, mime_type


async def upload_whatsapp_media(
    client: httpx.AsyncClient, settings: Settings, *, data: bytes, filename: str, mime_type: str
) -> str:
    """Upload bytes (e.g. the generated PDF) to Graph and return the media id."""
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise RuntimeError("WhatsApp credentials are required to upload media.")
    token = settings.whatsapp_access_token.get_secret_value()
    url = (
        f"https://graph.facebook.com/{settings.whatsapp_graph_api_version}/"
        f"{settings.whatsapp_phone_number_id}/media"
    )
    files = {"file": (filename, data, mime_type)}
    payload = {"messaging_product": "whatsapp"}
    response = await client.post(
        url, headers={"Authorization": f"Bearer {token}"}, data=payload, files=files
    )
    response.raise_for_status()
    return response.json()["id"]


def guess_extension(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type) or ""


def new_filename(mime_type: str) -> str:
    return f"{uuid.uuid4().hex}{guess_extension(mime_type)}"
