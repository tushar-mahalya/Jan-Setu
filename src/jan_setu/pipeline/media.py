"""WhatsApp media download/upload, and upload validation shared by both the
WhatsApp pipeline and the web API's direct file uploads.

Media URLs returned by the Graph ``/{media_id}`` lookup expire in minutes, so
every download here fetches and saves the bytes immediately — never store the
URL for later use.
"""

import logging
import mimetypes
import time
import uuid
from pathlib import Path

import httpx

from jan_setu.config import Settings

logger = logging.getLogger(__name__)

AUDIO_MIME_TYPES = frozenset(
    {"audio/ogg", "audio/opus", "audio/mpeg", "audio/mp3", "audio/wav", "audio/webm", "audio/mp4"}
)
IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
EXTENSIONS_BY_MIME_TYPE = {
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}


def normalize_mime_type(mime_type: str | None) -> str | None:
    """Strip optional MIME parameters such as a browser-supplied codec."""
    if not mime_type:
        return None
    return mime_type.partition(";")[0].strip().lower() or None


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
    if normalize_mime_type(mime_type) not in allowed:
        raise UploadTypeNotAllowed(f"{kind} type {mime_type!r} is not allowed")
    if size_bytes > max_bytes:
        raise UploadTooLarge(f"{kind} upload of {size_bytes} bytes exceeds the {max_bytes} limit")


def artifact_path(settings: Settings, stored_path: str | Path) -> Path:
    """Resolve a stored upload path under this process's configured upload root.

    The host API and Docker workers use different absolute roots in development.
    Persisted paths from either process are mapped by their path below ``uploads``
    so each process opens its own view of the shared artifact directory.
    """
    path = Path(stored_path)
    root = Path(settings.upload_dir)
    try:
        relative = path.relative_to(root)
    except ValueError:
        parts = path.parts
        try:
            relative = Path(*parts[parts.index("uploads") + 1 :])
        except ValueError:
            relative = path
    return root / relative


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

    start = time.perf_counter()
    lookup_url = f"https://graph.facebook.com/{settings.whatsapp_graph_api_version}/{media_id}"
    try:
        lookup = await client.get(lookup_url, headers=headers)
        lookup.raise_for_status()
        info = lookup.json()
    except (httpx.HTTPError, ValueError):
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.warning(
            "media_fetch_failed", extra={"media_id": media_id, "duration_ms": duration_ms}
        )
        raise

    try:
        media_url = info["url"]
    except (KeyError, TypeError) as exc:
        # A 2xx response with no "url" (unexpected shape, media still processing,
        # etc.) is a provider failure like any other — surface it as the same
        # exception type callers already catch, instead of an uncaught KeyError.
        raise httpx.HTTPError(f"WhatsApp media lookup for {media_id!r} returned no url") from exc
    mime_type = info.get("mime_type", "application/octet-stream")

    try:
        download = await client.get(media_url, headers=headers)
        download.raise_for_status()
    except httpx.HTTPError:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.warning(
            "media_fetch_failed", extra={"media_id": media_id, "duration_ms": duration_ms}
        )
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    size_bytes = len(download.content)
    logger.info(
        "media_fetched",
        extra={
            "media_id": media_id,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "status_code": download.status_code,
            "duration_ms": duration_ms,
        },
    )
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
    normalized = normalize_mime_type(mime_type) or ""
    return EXTENSIONS_BY_MIME_TYPE.get(normalized) or mimetypes.guess_extension(normalized) or ""


def new_filename(mime_type: str) -> str:
    return f"{uuid.uuid4().hex}{guess_extension(mime_type)}"
