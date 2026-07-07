"""Channel-agnostic grievance processing pipeline.

Both the WhatsApp driver (``processing.py``) and the web API (``web_api.py``)
call these same functions, so the two channels share one implementation of
"what happens to a filed complaint" — transcribe -> classify -> geocode-if-
missing -> image-check -> PDF -> (dedup window | dispatch).

Every stage here degrades rather than blocks: a failed STT clip, a failed LLM
call, or a failed geocode all leave a flag on the grievance and continue, so a
citizen's complaint is never lost to a flaky free-tier API.
"""

import logging
import mimetypes
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.pipeline.classify import check_image_match, classify_issue
from jan_setu.config import Settings
from jan_setu.db import AsyncSessionLocal, utc_now
from jan_setu.pipeline.dedup import find_duplicate
from jan_setu.pipeline.dispatchers import DispatchError, get_dispatcher
from jan_setu.pipeline.geocoding import reverse_geocode_cached
from jan_setu.pipeline.media import download_whatsapp_media, save_upload
from jan_setu.db.models import Contact, Grievance
from jan_setu.pipeline.pdfgen import PdfSummary, build_grievance_pdf
from jan_setu.repositories import (
    add_grievance_event,
    fetch_expired_windows,
    fetch_stuck_dispatching,
    get_grievance,
    set_grievance_fields,
)
from jan_setu.pipeline.stt import transcribe_clip
from jan_setu.pipeline.taxonomy import category_or_default, department_for_category

logger = logging.getLogger(__name__)

MAX_DISPATCH_ATTEMPTS = 5


@dataclass(frozen=True)
class PipelineResult:
    grievance_id: str
    status: str  # "awaiting_confirmation" | "photo_mismatch"
    category: str
    department_name: str
    priority: str
    flags: list[str] = field(default_factory=list)
    image_match_status: str | None = None


@dataclass(frozen=True)
class FinalizeOutcome:
    status: str  # "submitted" | "pending_window" | "duplicate" | "dispatching" | "dispatch_failed"
    human_id: str
    duplicate_of_human_id: str | None = None
    report_count: int | None = None


def _log_stage(stage: str, grievance_id: Any, **fields: Any) -> None:
    logger.info(
        "pipeline_stage", extra={"stage": stage, "grievance_id": str(grievance_id), **fields}
    )


async def _combine_issue_text(
    session: AsyncSession,
    settings: Settings,
    http_client: httpx.AsyncClient,
    issue_messages: list[dict[str, Any]],
) -> tuple[str, str | None, list[str]]:
    """Concatenate typed text + transcribed English audio, in chronological
    order (the messages are already appended in arrival order). Each audio
    entry is either a WhatsApp ``media_id`` (downloaded fresh — media URLs
    expire) or a web upload already saved to disk (``local_path``). Returns
    (combined_text, detected_language, flags)."""
    parts: list[str] = []
    detected_language: str | None = None
    flags: list[str] = []
    for message in issue_messages:
        message_type = message.get("type")
        if message_type == "text" and message.get("text"):
            parts.append(message["text"])
            continue
        if message_type not in ("audio", "voice"):
            continue
        try:
            if message.get("local_path"):
                audio_bytes = Path(message["local_path"]).read_bytes()
                mime_type = message.get("mime_type") or "audio/ogg"
            elif message.get("media_id"):
                audio_bytes, mime_type = await download_whatsapp_media(
                    http_client, settings, message["media_id"]
                )
            else:
                continue
        except (httpx.HTTPError, OSError):
            flags.append("transcription_failed")
            continue
        result = await transcribe_clip(
            session, settings, http_client, audio_bytes=audio_bytes, mime_type=mime_type
        )
        if result.ok and result.text:
            parts.append(result.text)
            detected_language = detected_language or result.detected_language
        else:
            flags.append("transcription_failed")
    return "\n".join(parts).strip(), detected_language, flags


async def _fetch_photo(
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    photo_media_id: str | None,
    photo_path: str | None,
) -> tuple[bytes | None, str | None]:
    if photo_path:
        try:
            data = Path(photo_path).read_bytes()
        except OSError:
            logger.warning("photo_read_failed")
            return None, None
        return data, mimetypes.guess_type(photo_path)[0] or "image/jpeg"
    if not photo_media_id:
        return None, None
    try:
        return await download_whatsapp_media(http_client, settings, photo_media_id)
    except httpx.HTTPError:
        logger.warning("photo_download_failed")
        return None, None


async def _contact_phone(session: AsyncSession, contact_id: Any) -> str:
    contact = await session.get(Contact, contact_id)
    return contact.wa_id if contact else ""


async def _build_and_store_pdf(
    session: AsyncSession,
    settings: Settings,
    grievance: Grievance,
    photo_bytes: bytes | None,
) -> None:
    department = department_for_category(grievance.category or "other")
    summary = PdfSummary(
        human_id=grievance.human_id,
        created_at=grievance.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        category_label=category_or_default(grievance.category).label,
        department_name=department.name,
        priority=grievance.priority or "normal",
        term=grievance.term or "short_term",
        address=grievance.location_address,
        description=grievance.issue_text or "",
        contact_phone=await _contact_phone(session, grievance.contact_id),
        flags=list(grievance.flags or []),
    )
    pdf_bytes = build_grievance_pdf(summary, photo_bytes)
    path = save_upload(settings, grievance_id=str(grievance.id), name="summary.pdf", data=pdf_bytes)
    await set_grievance_fields(session, grievance_id=grievance.id, pdf_path=path)


def render_confirmation_summary(grievance: Grievance) -> str:
    department = department_for_category(grievance.category or "other")
    category_label = category_or_default(grievance.category).label
    return (
        f"{category_label} -> {department.name}\n"
        f"Priority: {grievance.priority or 'normal'}\n"
        f"Location: {grievance.location_address or 'unresolved'}\n\n"
        f"{grievance.issue_text or '(no description)'}"
    )


async def run_pipeline(
    grievance_id: Any, settings: Settings, http_client: httpx.AsyncClient
) -> PipelineResult:
    """First pass over a freshly-drafted grievance: transcribe, classify,
    geocode if needed, and check the photo."""
    async with AsyncSessionLocal() as session:
        grievance = await get_grievance(session, grievance_id=grievance_id)
        if grievance is None:
            raise ValueError(f"grievance {grievance_id} not found")

        text, detected_language, stt_flags = await _combine_issue_text(
            session, settings, http_client, grievance.issue_messages
        )
        _log_stage("transcribe", grievance_id, flags=stt_flags)

        classification = await classify_issue(session, settings, http_client, text=text)
        _log_stage(
            "classify",
            grievance_id,
            category=classification.category,
            degraded=classification.degraded,
        )

        address = grievance.location_address
        if not address and grievance.location_latitude is not None:
            geocode = await reverse_geocode_cached(
                session,
                settings,
                grievance.location_latitude,
                grievance.location_longitude,
                http_client,
            )
            address = geocode.display_address

        photo_bytes, photo_mime = await _fetch_photo(
            settings,
            http_client,
            photo_media_id=grievance.photo_media_id,
            photo_path=grievance.photo_path,
        )
        image_match_status = "none"
        if photo_bytes is not None:
            match = await check_image_match(
                session,
                settings,
                http_client,
                text=text,
                image_bytes=photo_bytes,
                mime_type=photo_mime or "image/jpeg",
            )
            image_match_status = "matched" if match.matches else "mismatched"
            _log_stage(
                "image_check", grievance_id, status=image_match_status, degraded=match.degraded
            )

        flags = list(stt_flags)
        if classification.degraded:
            flags.append("classification_failed")

        next_status = (
            "photo_mismatch" if image_match_status == "mismatched" else "awaiting_confirmation"
        )
        grievance = await set_grievance_fields(
            session,
            grievance_id=grievance_id,
            issue_text=text,
            location_address=address,
            source_language=detected_language,
            category=classification.category,
            department_key=category_or_default(classification.category).department_key,
            priority=classification.priority,
            term=classification.term,
            confidence=classification.confidence,
            image_match_status=image_match_status,
            flags=flags,
            status=next_status,
        )
        if next_status == "awaiting_confirmation":
            await _build_and_store_pdf(session, settings, grievance, photo_bytes)
        await add_grievance_event(session, grievance_id=grievance_id, status=next_status)
        await session.commit()

        department = department_for_category(classification.category)
        return PipelineResult(
            grievance_id=str(grievance_id),
            status=next_status,
            category=classification.category,
            department_name=department.name,
            priority=classification.priority,
            flags=flags,
            image_match_status=image_match_status,
        )


async def recheck_image(
    grievance_id: Any,
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    proceed_without_photo: bool = False,
) -> PipelineResult:
    """Re-run just the image-match stage: either the citizen sent a
    replacement photo (re-check it) or chose to continue without one."""
    async with AsyncSessionLocal() as session:
        grievance = await get_grievance(session, grievance_id=grievance_id)
        if grievance is None:
            raise ValueError(f"grievance {grievance_id} not found")

        image_match_status = "skipped"
        photo_bytes: bytes | None = None
        if not proceed_without_photo:
            photo_bytes, photo_mime = await _fetch_photo(
                settings,
                http_client,
                photo_media_id=grievance.photo_media_id,
                photo_path=grievance.photo_path,
            )
            if photo_bytes is not None:
                match = await check_image_match(
                    session,
                    settings,
                    http_client,
                    text=grievance.issue_text,
                    image_bytes=photo_bytes,
                    mime_type=photo_mime or "image/jpeg",
                )
                image_match_status = "matched" if match.matches else "mismatched"

        next_status = (
            "photo_mismatch" if image_match_status == "mismatched" else "awaiting_confirmation"
        )
        grievance = await set_grievance_fields(
            session,
            grievance_id=grievance_id,
            image_match_status=image_match_status,
            status=next_status,
        )
        if next_status == "awaiting_confirmation":
            await _build_and_store_pdf(session, settings, grievance, photo_bytes)
        await add_grievance_event(session, grievance_id=grievance_id, status=next_status)
        await session.commit()

        department = department_for_category(grievance.category or "other")
        return PipelineResult(
            grievance_id=str(grievance_id),
            status=next_status,
            category=grievance.category or "other",
            department_name=department.name,
            priority=grievance.priority or "normal",
            flags=list(grievance.flags or []),
            image_match_status=image_match_status,
        )


async def finalize_grievance(
    settings: Settings, http_client: httpx.AsyncClient, *, grievance_id: Any
) -> FinalizeOutcome:
    """awaiting_confirmation -> registered, then either dispatch immediately
    (priority) or enter the dedup window (normal)."""
    async with AsyncSessionLocal() as session:
        grievance = await get_grievance(session, grievance_id=grievance_id)
        if grievance is None:
            raise ValueError(f"grievance {grievance_id} not found")

        await set_grievance_fields(
            session, grievance_id=grievance_id, status="registered", confirmed_at=utc_now()
        )
        await add_grievance_event(session, grievance_id=grievance_id, status="registered")

        category = grievance.category or "other"
        priority = grievance.priority or "normal"

        if priority == "priority":
            await session.commit()
            return await dispatch_grievance(settings, http_client, grievance_id=grievance_id)

        duplicate = await find_duplicate(
            session,
            category=category,
            lat=grievance.location_latitude,
            lon=grievance.location_longitude,
            radius_m=settings.dedup_radius_m,
            exclude_grievance_id=str(grievance_id),
        )
        if duplicate is not None:
            master = duplicate.master
            new_count = master.report_count + 1
            await set_grievance_fields(
                session, grievance_id=grievance_id, status="duplicate", duplicate_of_id=master.id
            )
            await set_grievance_fields(session, grievance_id=master.id, report_count=new_count)
            await add_grievance_event(
                session,
                grievance_id=grievance_id,
                status="duplicate",
                note=f"duplicate of {master.human_id}",
            )
            await session.commit()
            return FinalizeOutcome(
                status="duplicate",
                human_id=grievance.human_id,
                duplicate_of_human_id=master.human_id,
                report_count=new_count,
            )

        window_expires_at = utc_now() + timedelta(hours=settings.dedup_window_hours)
        await set_grievance_fields(
            session,
            grievance_id=grievance_id,
            status="pending_window",
            window_expires_at=window_expires_at,
        )
        await add_grievance_event(session, grievance_id=grievance_id, status="pending_window")
        await session.commit()
        return FinalizeOutcome(status="pending_window", human_id=grievance.human_id)


async def cancel_grievance(*, grievance_id: Any) -> None:
    async with AsyncSessionLocal() as session:
        await set_grievance_fields(session, grievance_id=grievance_id, status="cancelled")
        await add_grievance_event(session, grievance_id=grievance_id, status="cancelled")
        await session.commit()


async def dispatch_grievance(
    settings: Settings, http_client: httpx.AsyncClient, *, grievance_id: Any
) -> FinalizeOutcome:
    async with AsyncSessionLocal() as session:
        grievance = await get_grievance(session, grievance_id=grievance_id)
        if grievance is None:
            raise ValueError(f"grievance {grievance_id} not found")
        await set_grievance_fields(session, grievance_id=grievance_id, status="dispatching")
        await session.flush()

        department = department_for_category(grievance.category or "other")
        dispatcher = get_dispatcher(settings, http_client)
        summary = render_confirmation_summary(grievance)
        pdf_bytes = Path(grievance.pdf_path).read_bytes() if grievance.pdf_path else b""

        try:
            ref = await dispatcher.dispatch(
                human_id=grievance.human_id,
                department=department,
                summary=summary,
                pdf_bytes=pdf_bytes,
            )
        except DispatchError:
            attempts = grievance.dispatch_attempts + 1
            new_status = "dispatch_failed" if attempts >= MAX_DISPATCH_ATTEMPTS else "dispatching"
            await set_grievance_fields(
                session, grievance_id=grievance_id, dispatch_attempts=attempts, status=new_status
            )
            if new_status == "dispatch_failed":
                await add_grievance_event(
                    session, grievance_id=grievance_id, status="dispatch_failed"
                )
            await session.commit()
            logger.warning(
                "dispatch_failed", extra={"grievance_id": str(grievance_id), "attempts": attempts}
            )
            return FinalizeOutcome(status=new_status, human_id=grievance.human_id)

        await set_grievance_fields(
            session, grievance_id=grievance_id, status="submitted", dispatch_ref=ref
        )
        await add_grievance_event(session, grievance_id=grievance_id, status="submitted", note=ref)
        await session.commit()
        return FinalizeOutcome(status="submitted", human_id=grievance.human_id)


async def sweep_expired_windows(
    settings: Settings, http_client: httpx.AsyncClient, *, limit: int
) -> int:
    """Dedup windows that have expired: dispatch their (surviving) master
    grievance. Called from the worker loop."""
    async with AsyncSessionLocal() as session:
        ids = await fetch_expired_windows(session, limit=limit)
    for grievance_id in ids:
        try:
            await dispatch_grievance(settings, http_client, grievance_id=grievance_id)
        except Exception:
            logger.exception(
                "dedup_window_dispatch_failed", extra={"grievance_id": str(grievance_id)}
            )
    return len(ids)


async def sweep_stuck_dispatching(
    settings: Settings, http_client: httpx.AsyncClient, *, limit: int
) -> int:
    """Retry grievances stuck mid-dispatch (crash, transient dispatcher error)."""
    async with AsyncSessionLocal() as session:
        ids = await fetch_stuck_dispatching(session, limit=limit)
    for grievance_id in ids:
        try:
            await dispatch_grievance(settings, http_client, grievance_id=grievance_id)
        except Exception:
            logger.exception("dispatch_retry_failed", extra={"grievance_id": str(grievance_id)})
    return len(ids)
