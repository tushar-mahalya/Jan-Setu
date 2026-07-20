"""Web channel: file a complaint through a proper form (not chat).

Shares the same pipeline services as the WhatsApp channel via ``jan_setu.pipeline``
— this module and ``jan_setu.whatsapp.processing`` are both thin, channel-specific
adapters over the same orchestrator, so "what happens to a filed complaint" is
implemented exactly once.
"""

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
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.auth import get_current_user
from jan_setu.config import Settings, get_settings
from jan_setu.db import get_session
from jan_setu.db.models import Grievance, User
from jan_setu.pipeline import finalize_grievance, recheck_image
from jan_setu.pipeline.media import (
    UploadTooLarge,
    UploadTypeNotAllowed,
    new_filename,
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
    GrievanceDetail,
    GrievanceDraftResponse,
    GrievanceEventRead,
    GrievanceReviewPatch,
    GrievanceSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/grievances", tags=["grievances"])


def _require_owner(grievance: Grievance | None, user: User) -> Grievance:
    if grievance is None or grievance.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grievance not found")
    return grievance


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
    )


@router.post("/draft", response_model=GrievanceDraftResponse)
async def create_draft(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
    lat: Annotated[float, Form()],
    lon: Annotated[float, Form()],
    text: Annotated[str | None, Form()] = None,
    photo: Annotated[UploadFile | None, File()] = None,
    audio: Annotated[list[UploadFile] | None, File()] = None,
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
        photo_bytes = await photo.read()
        photo_mime = photo.content_type or "image/jpeg"
        try:
            validate_upload(
                mime_type=photo_mime, size_bytes=len(photo_bytes), kind="image", settings=settings
            )
        except (UploadTooLarge, UploadTypeNotAllowed) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    audio_clips: list[tuple[bytes, str]] = []
    for clip in audio or []:
        if not clip.filename:
            continue
        data = await clip.read()
        mime_type = normalize_mime_type(clip.content_type) or "audio/ogg"
        try:
            validate_upload(
                mime_type=mime_type, size_bytes=len(data), kind="audio", settings=settings
            )
        except (UploadTooLarge, UploadTypeNotAllowed) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        audio_clips.append((data, mime_type))

    if not text_messages and not audio_clips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a description (text or voice note).",
        )

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
    for data, mime_type in audio_clips:
        path = save_upload(
            settings, grievance_id=str(grievance.id), name=new_filename(mime_type), data=data
        )
        issue_messages.append({"type": "audio", "mime_type": mime_type, "local_path": path})

    photo_path = None
    if photo_bytes is not None:
        photo_path = save_upload(
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

    data = await photo.read()
    mime_type = photo.content_type or "image/jpeg"
    try:
        validate_upload(mime_type=mime_type, size_bytes=len(data), kind="image", settings=settings)
    except (UploadTooLarge, UploadTypeNotAllowed) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    path = save_upload(
        settings, grievance_id=str(grievance_id), name=new_filename(mime_type), data=data
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

    return await _draft_response(session, grievance_id)


@router.post("/{grievance_id}/confirm")
async def confirm_draft(
    grievance_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str | int | None]:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    if grievance.status != "awaiting_confirmation":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot confirm a grievance in status {grievance.status!r}",
        )

    http_client = request.app.state.http_client
    outcome = await finalize_grievance(settings, http_client, grievance_id=grievance_id)
    return {
        "status": outcome.status,
        "human_id": outcome.human_id,
        "duplicate_of_human_id": outcome.duplicate_of_human_id,
        "report_count": outcome.report_count,
    }


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
        term=grievance.term,
        confidence=grievance.confidence,
        image_match_status=grievance.image_match_status,
        flags=list(grievance.flags or []),
        report_count=grievance.report_count,
        dispatch_ref=grievance.dispatch_ref,
        events=[GrievanceEventRead.model_validate(event) for event in events],
        pdf_url=f"/api/grievances/{grievance.id}/pdf" if grievance.pdf_path else None,
    )


@router.get("/{grievance_id}/pdf")
async def download_pdf(
    grievance_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    grievance = await get_grievance(session, grievance_id=grievance_id)
    grievance = _require_owner(grievance, user)
    if not grievance.pdf_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF not generated yet")
    return FileResponse(
        grievance.pdf_path, media_type="application/pdf", filename=f"{grievance.human_id}.pdf"
    )
