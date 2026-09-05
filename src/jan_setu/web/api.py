"""Web channel: file a complaint through a proper form (not chat).

Shares the same pipeline services as the WhatsApp channel via ``jan_setu.pipeline``
— this module and ``jan_setu.whatsapp.processing`` are both thin, channel-specific
adapters over the same orchestrator, so "what happens to a filed complaint" is
implemented exactly once.
"""

import mimetypes
import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.auth import get_current_user
from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session
from jan_setu.db.models import Grievance, User
from jan_setu.pipeline import accept_photo_mismatch, finalize_grievance, recheck_image
from jan_setu.pipeline.stt import transcribe_clip
from jan_setu.pipeline.media import (
    UploadTooLarge,
    UploadTypeNotAllowed,
    new_filename,
    artifact_path,
    normalize_mime_type,
    save_upload,
    validate_upload,
)
from jan_setu.pipeline.taxonomy import (
    DOMAIN_LABELS,
    TAXONOMY_VERSION,
    canonical_category_key,
    category_or_default,
    department_for_category,
    evaluate_routing_policy,
    route_for_category,
)
from jan_setu.repositories import (
    create_draft_grievance,
    enqueue_pipeline_job,
    get_grievance,
    list_grievance_events,
    list_grievances_for_user,
    set_grievance_fields,
)
from jan_setu.schemas import (
    GrievanceConfirmResponse,
    GrievanceDetail,
    GrievanceDraftResponse,
    GrievanceEventRead,
    GrievanceReviewPatch,
    GrievanceSummary,
    TranscriptionPreview,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/grievances", tags=["grievances"])


def _require_owner(grievance: Grievance | None, user: User) -> Grievance:
    if grievance is None or grievance.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grievance not found")
    return grievance


def _voice_note_urls(grievance: Grievance) -> list[str]:
    return [
        f"/api/grievances/{grievance.id}/audio/{index}"
        for index, message in enumerate(grievance.issue_messages)
        if message.get("type") in ("audio", "voice") and message.get("local_path")
    ]


def _voice_note_metadata(grievance: Grievance) -> list[dict[str, str | int]]:
    return [
        {
            "recording_id": str(message.get("recording_id") or f"legacy-{index + 1}"),
            "segment_index": int(message.get("segment_index") or 0),
            "mime_type": str(message.get("mime_type") or "audio/webm"),
        }
        for index, message in enumerate(grievance.issue_messages)
        if message.get("type") in ("audio", "voice") and message.get("local_path")
    ]


async def _draft_response(session: AsyncSession, grievance_id: UUID) -> GrievanceDraftResponse:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    category = category_or_default(grievance.category_id or grievance.category)
    department = department_for_category(category.key)
    return GrievanceDraftResponse(
        id=grievance.id,
        human_id=grievance.human_id,
        status=grievance.status,
        category=grievance.category,
        department_name=department.name,
        priority=grievance.priority,
        term=grievance.term,
        confidence=grievance.confidence,
        address=grievance.location_address,
        issue_text=grievance.issue_text,
        image_match_status=grievance.image_match_status,
        flags=list(grievance.flags or []),
        pdf_url=f"/api/grievances/{grievance.id}/pdf" if grievance.pdf_path else None,
        photo_url=f"/api/grievances/{grievance.id}/photo" if grievance.photo_path else None,
        taxonomy_version=grievance.taxonomy_version,
        category_id=grievance.category_id,
        category_label=category.label if grievance.category_id else None,
        domain_label=DOMAIN_LABELS.get(category.parent_key) if grievance.category_id else None,
        safety_level=grievance.safety_level,
        asset_scope=grievance.asset_scope,
        disposition=grievance.disposition,
        review_status=grievance.review_status,
        structured_facts=grievance.structured_facts,
        routing=grievance.routing_snapshot,
        transcript_metadata=list(grievance.transcript_metadata or []),
        voice_note_urls=_voice_note_urls(grievance),
        voice_note_metadata=_voice_note_metadata(grievance),
    )


@router.post("/transcription-preview", response_model=TranscriptionPreview)
async def preview_transcription(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
    audio: Annotated[UploadFile, File()],
) -> TranscriptionPreview:
    del user  # Authentication is required even though preview is not persisted.
    # Cap the read at the limit validate_upload enforces anyway, so an
    # oversized upload is rejected without first buffering it all into memory.
    data = await audio.read(settings.max_audio_bytes + 1)
    mime_type = normalize_mime_type(audio.content_type) or "audio/ogg"
    try:
        validate_upload(mime_type=mime_type, size_bytes=len(data), kind="audio", settings=settings)
    except (UploadTooLarge, UploadTypeNotAllowed) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    result = await transcribe_clip(
        session, settings, request.app.state.http_client, audio_bytes=data, mime_type=mime_type
    )
    await session.commit()
    if not result.ok or not result.text:
        return TranscriptionPreview(status="unavailable")
    return TranscriptionPreview(text=result.text, language=result.detected_language, status="final")


@router.post("/draft", response_model=GrievanceDraftResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
    lat: Annotated[float, Form(ge=-90, le=90)],
    lon: Annotated[float, Form(ge=-180, le=180)],
    text: Annotated[str | None, Form(max_length=5000)] = None,
    landmark: Annotated[str | None, Form(max_length=300)] = None,
    photo: Annotated[UploadFile | None, File()] = None,
    audio: Annotated[list[UploadFile] | None, File()] = None,
    audio_metadata: Annotated[list[str] | None, Form()] = None,
) -> GrievanceDraftResponse:
    if user.contact_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is not linked to a verified WhatsApp contact",
        )

    text_messages = []
    if text and text.strip():
        text_messages.append({"type": "text", "text": text.strip()})

    photo_bytes: bytes | None = None
    photo_mime: str | None = None
    if photo is not None and photo.filename:
        photo_bytes = await photo.read(settings.max_image_bytes + 1)
        photo_mime = photo.content_type or "image/jpeg"
        try:
            validate_upload(
                mime_type=photo_mime, size_bytes=len(photo_bytes), kind="image", settings=settings
            )
        except (UploadTooLarge, UploadTypeNotAllowed) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    raw_audio_metadata = audio_metadata or []
    if len(raw_audio_metadata) != len(audio or []):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Each voice note requires its recording metadata.",
        )
    parsed_audio_metadata: list[dict[str, str | int]] = []
    for raw_metadata in raw_audio_metadata:
        try:
            metadata = json.loads(raw_metadata)
            recording_id = str(metadata["recording_id"])
            segment_index = int(metadata["segment_index"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Voice note metadata is invalid.",
            ) from exc
        if len(recording_id) > 128 or not recording_id or segment_index < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Voice note metadata is invalid.",
            )
        parsed_audio_metadata.append({"recording_id": recording_id, "segment_index": segment_index})

    audio_clips: list[tuple[bytes, str, dict[str, str | int]]] = []
    for clip, metadata in zip(audio or [], parsed_audio_metadata, strict=True):
        if not clip.filename:
            continue
        data = await clip.read(settings.max_audio_bytes + 1)
        mime_type = normalize_mime_type(clip.content_type) or "audio/ogg"
        try:
            validate_upload(
                mime_type=mime_type, size_bytes=len(data), kind="audio", settings=settings
            )
        except (UploadTooLarge, UploadTypeNotAllowed) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        audio_clips.append((data, mime_type, metadata))

    if not text_messages and not audio_clips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a description (text or voice note).",
        )

    # Citizen-provided landmark from step 1: fed to the pipeline as a text hint so
    # extraction populates structured_facts.landmark without a review clarification.
    if landmark and landmark.strip():
        text_messages.append({"type": "text", "text": f"Nearby landmark: {landmark.strip()}"})

    context = {
        "location": {"lat": lat, "lon": lon, "display_address": None},
        "issue": {"messages": text_messages},
        "photo": {"media_id": None},
    }
    grievance, _created = await create_draft_grievance(
        session,
        contact_id=user.contact_id,
        conversation_id=None,
        user_id=user.id,
        source="web",
        context=context,
    )
    await session.commit()

    issue_messages = list(text_messages)
    for data, mime_type, metadata in audio_clips:
        # save_upload() does synchronous disk I/O; offload to a worker thread
        # so it doesn't block the event loop for other concurrent requests.
        path = await run_in_threadpool(
            save_upload,
            settings,
            grievance_id=str(grievance.id),
            name=new_filename(mime_type),
            data=data,
        )
        issue_messages.append(
            {
                "type": "audio",
                "mime_type": mime_type,
                "local_path": path,
                **metadata,
            }
        )

    photo_path = None
    if photo_bytes is not None:
        photo_path = await run_in_threadpool(
            save_upload,
            settings,
            grievance_id=str(grievance.id),
            name=new_filename(photo_mime),
            data=photo_bytes,
        )

    await set_grievance_fields(
        session,
        grievance_id=grievance.id,
        issue_messages=issue_messages,
        photo_path=photo_path,
        status="processing",
    )
    await enqueue_pipeline_job(session, grievance_id=grievance.id)
    await session.commit()
    logger.info(
        "grievance_created", extra={"grievance_id": str(grievance.id), "user_id": str(user.id)}
    )
    return await _draft_response(session, grievance.id)


@router.get("/{grievance_id}/draft", response_model=GrievanceDraftResponse)
async def get_draft(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> GrievanceDraftResponse:
    _require_owner(await get_grievance(session, grievance_id=grievance_id), user)
    return await _draft_response(session, grievance_id)


@router.patch("/{grievance_id}/review", response_model=GrievanceDraftResponse)
async def update_review(
    grievance_id: UUID,
    body: GrievanceReviewPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> GrievanceDraftResponse:
    grievance = _require_owner(await get_grievance(session, grievance_id=grievance_id), user)
    category_key = canonical_category_key(
        body.category_id or grievance.category_id or grievance.category
    )
    if category_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown civic category"
        )
    asset_scope = body.asset_scope or grievance.asset_scope or "unknown"
    if asset_scope not in ("public", "private", "unknown"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid asset scope"
        )
    category = category_or_default(category_key)
    policy = evaluate_routing_policy(
        category_key=category_key,
        safety=grievance.safety_level or "none",
        asset_scope=asset_scope,
        jurisdiction_known=bool(grievance.location_address),
        extraction_confidence=1.0,
    )
    route = route_for_category(category_key)
    facts = dict(grievance.structured_facts or {})
    if body.summary is not None:
        facts["summary"] = body.summary.strip()
    if body.clarification_answer is not None:
        facts["clarification_answer"] = body.clarification_answer.strip()
    await set_grievance_fields(
        session,
        grievance_id=grievance.id,
        taxonomy_version=TAXONOMY_VERSION,
        category=category_key,
        category_id=category_key,
        aggregation_key=category.aggregation_key,
        department_key=category.department_key,
        priority=policy.priority,
        term=category.term_hint,
        confidence=1.0,
        asset_scope=asset_scope,
        disposition=policy.disposition,
        review_status="pending_official" if policy.needs_official_review else "citizen_review",
        structured_facts=facts,
        routing_snapshot={
            "taxonomy_version": TAXONOMY_VERSION,
            "category_id": category_key,
            "department_key": route.department_key if route else category.department_key,
            "owning_agency": route.owning_agency if route else None,
            "dispatch_enabled": route.dispatch_enabled if route else False,
            "sla_hours": route.sla_hours if route else None,
            "disposition": policy.disposition,
        },
        state_version=grievance.state_version + 1,
    )
    # A correction or clarification is a discrepancy signal: queue an escalated
    # re-extraction (stronger model + the citizen's context) in the background.
    if body.category_id or body.clarification_answer:
        await enqueue_pipeline_job(
            session,
            grievance_id=grievance.id,
            stage="reextract",
            key_suffix=str(grievance.state_version + 1),
        )
    await session.commit()
    logger.info(
        "grievance_review_updated",
        extra={
            "grievance_id": str(grievance.id),
            "user_id": str(user.id),
            "review_status": policy.needs_official_review,
        },
    )
    return await _draft_response(session, grievance.id)


@router.patch("/{grievance_id}/photo", response_model=GrievanceDraftResponse)
async def replace_photo(
    grievance_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
    photo: Annotated[UploadFile, File()],
) -> GrievanceDraftResponse:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    _require_owner(grievance, user)

    data = await photo.read(settings.max_image_bytes + 1)
    mime_type = photo.content_type or "image/jpeg"
    try:
        validate_upload(mime_type=mime_type, size_bytes=len(data), kind="image", settings=settings)
    except (UploadTooLarge, UploadTypeNotAllowed) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    path = await run_in_threadpool(
        save_upload,
        settings,
        grievance_id=str(grievance_id),
        name=new_filename(mime_type),
        data=data,
    )
    await set_grievance_fields(
        session, grievance_id=grievance_id, photo_path=path, photo_media_id=None
    )
    await session.commit()

    http_client = request.app.state.http_client
    try:
        await recheck_image(grievance_id, settings, http_client, proceed_without_photo=False)
    except Exception:
        logger.exception("web_photo_recheck_failed", extra={"grievance_id": str(grievance_id)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Photo re-check failed; please try again.",
        ) from None

    logger.info(
        "grievance_photo_updated",
        extra={"grievance_id": str(grievance_id), "user_id": str(user.id)},
    )
    return await _draft_response(session, grievance_id)


@router.post("/{grievance_id}/confirm", response_model=GrievanceConfirmResponse)
async def confirm_draft(
    grievance_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> GrievanceConfirmResponse:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    if grievance.status not in ("awaiting_confirmation", "photo_mismatch"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm a grievance in status {grievance.status!r}",
        )

    http_client = request.app.state.http_client
    if grievance.status == "photo_mismatch":
        # The mismatch warning is advisory: the citizen may file anyway. Move to
        # awaiting_confirmation (and build the receipt the pipeline skipped)
        # before finalizing, keeping the mismatch on record for the official.
        await accept_photo_mismatch(grievance_id, settings, http_client)
    outcome = await finalize_grievance(settings, http_client, grievance_id=grievance_id)
    logger.info(
        "grievance_confirmed",
        extra={
            "grievance_id": str(grievance_id),
            "user_id": str(user.id),
            "status": outcome.status,
        },
    )
    return GrievanceConfirmResponse(
        status=outcome.status,
        human_id=outcome.human_id,
        duplicate_of_human_id=outcome.duplicate_of_human_id,
        report_count=outcome.report_count,
    )


@router.get("", response_model=list[GrievanceSummary])
async def list_my_grievances(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Grievance]:
    return await list_grievances_for_user(session, user_id=user.id, limit=limit, offset=offset)


@router.get("/{grievance_id}", response_model=GrievanceDetail)
async def get_grievance_detail(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> GrievanceDetail:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    events = await list_grievance_events(session, grievance_id=grievance_id)
    category = category_or_default(grievance.category_id or grievance.category)
    department = department_for_category(category.key)
    return GrievanceDetail(
        id=grievance.id,
        human_id=grievance.human_id,
        category=grievance.category,
        status=grievance.status,
        priority=grievance.priority,
        source=grievance.source,
        created_at=grievance.created_at,
        address=grievance.location_address,
        issue_text=grievance.issue_text,
        department_key=grievance.department_key,
        department_name=department.name,
        term=grievance.term,
        confidence=grievance.confidence,
        image_match_status=grievance.image_match_status,
        flags=list(grievance.flags or []),
        report_count=grievance.report_count,
        dispatch_ref=grievance.dispatch_ref,
        events=[GrievanceEventRead.model_validate(event) for event in events],
        pdf_url=f"/api/grievances/{grievance.id}/pdf" if grievance.pdf_path else None,
        photo_url=f"/api/grievances/{grievance.id}/photo" if grievance.photo_path else None,
        category_id=grievance.category_id,
        category_label=category.label if grievance.category_id else None,
        domain_label=DOMAIN_LABELS.get(category.parent_key) if grievance.category_id else None,
        safety_level=grievance.safety_level,
        asset_scope=grievance.asset_scope,
        disposition=grievance.disposition,
        review_status=grievance.review_status,
        source_language=grievance.source_language,
        transcript_metadata=list(grievance.transcript_metadata or []),
        structured_facts=grievance.structured_facts,
        routing=grievance.routing_snapshot,
    )


@router.get("/{grievance_id}/audio/{message_index}")
async def stream_voice_note(
    grievance_id: UUID,
    message_index: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    grievance = _require_owner(await get_grievance(session, grievance_id=grievance_id), user)
    if message_index < 0 or message_index >= len(grievance.issue_messages):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice note not found")
    message = grievance.issue_messages[message_index]
    if message.get("type") not in ("audio", "voice") or not message.get("local_path"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice note not found")
    audio_path = artifact_path(settings, message["local_path"])
    if not audio_path.is_file():
        logger.warning(
            "grievance_voice_note_missing",
            extra={"grievance_id": str(grievance_id), "audio_path": str(audio_path)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Voice note is unavailable"
        )
    return FileResponse(audio_path, media_type=message.get("mime_type") or "audio/webm")


@router.get("/{grievance_id}/photo")
async def download_photo(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    """The citizen's own evidence photo. Same ownership check as the PDF -- the
    image is personal data and must never be readable by ticket id alone."""
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    if not grievance.photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No photo attached")
    photo_path = artifact_path(settings, grievance.photo_path)
    if not photo_path.is_file():
        logger.warning(
            "grievance_photo_missing",
            extra={"grievance_id": str(grievance_id), "photo_path": str(photo_path)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo artifact is unavailable"
        )
    return FileResponse(
        photo_path, media_type=mimetypes.guess_type(photo_path.name)[0] or "image/jpeg"
    )


@router.get("/{grievance_id}/pdf")
async def download_pdf(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    if not grievance.pdf_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF not generated yet")
    pdf_path = artifact_path(settings, grievance.pdf_path)
    if not pdf_path.is_file():
        logger.warning(
            "grievance_pdf_missing",
            extra={"grievance_id": str(grievance_id), "pdf_path": str(pdf_path)},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PDF artifact is unavailable"
        )
    return FileResponse(
        pdf_path, media_type="application/pdf", filename=f"{grievance.human_id}.pdf"
    )
