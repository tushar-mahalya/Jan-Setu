"""Speech-to-text via Sarvam AI's ``saaras`` model.

``mode=transcribe`` preserves the citizen's spoken language for the complaint
record. The multilingual extraction model receives that original transcript.
"""

import asyncio
import logging
import mimetypes
import time
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings
from jan_setu.pipeline.media import normalize_mime_type
from jan_setu.pipeline.throttle import reserve_slot

logger = logging.getLogger(__name__)

# The Sarvam REST endpoint rejects clips longer than this; longer voice notes
# would need the batch API (not implemented — out of scope for this pipeline).
MAX_CLIP_SECONDS = 30


@dataclass(frozen=True)
class TranscriptionResult:
    ok: bool
    text: str | None = None
    detected_language: str | None = None


async def transcribe_clip(
    session: AsyncSession,
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    audio_bytes: bytes,
    mime_type: str,
) -> TranscriptionResult:
    """Transcribe (and translate to English) one voice clip. Never raises —
    failures degrade to ``ok=False`` so the pipeline can continue with
    whatever other text the user provided."""
    if not settings.sarvam_api_key:
        logger.warning("sarvam_not_configured")
        return TranscriptionResult(ok=False)

    wait = await reserve_slot(session, "sarvam", settings.sarvam_min_interval_seconds)
    if wait > 0:
        await asyncio.sleep(wait)

    mime_type = normalize_mime_type(mime_type) or "audio/ogg"
    extension = mimetypes.guess_extension(mime_type) or ".ogg"
    filename = f"clip{extension}"
    files = {"file": (filename, audio_bytes, mime_type)}
    data = {"model": settings.sarvam_model, "mode": "transcribe"}
    headers = {"api-subscription-key": settings.sarvam_api_key.get_secret_value()}
    url = f"{settings.sarvam_base_url.rstrip('/')}/speech-to-text"

    start = time.perf_counter()
    try:
        response = await http_client.post(
            url, headers=headers, data=data, files=files, timeout=settings.sarvam_timeout_seconds
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("sarvam_transcription_failed")
        return TranscriptionResult(ok=False)

    # A 2xx with an unexpected shape (list, string, etc.) is a provider failure
    # like any other — degrade instead of an uncaught AttributeError on .get().
    transcript = body.get("transcript") if isinstance(body, dict) else None
    if not transcript:
        return TranscriptionResult(ok=False)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "sarvam_transcription_succeeded",
        extra={
            "duration_ms": duration_ms,
            "audio_bytes": len(audio_bytes),
            "transcript_length": len(transcript),
        },
    )
    return TranscriptionResult(
        ok=True, text=transcript, detected_language=body.get("language_code")
    )
