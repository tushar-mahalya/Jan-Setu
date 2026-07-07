"""Driving WhatsApp conversations: one unified path for both the in-request
BackgroundTask and the worker sweep.

``drive_event`` claims a webhook event with the same row-lease pattern as
outbound sends (``claim_event``), then runs the conversation FSM for every
message it contains. An event is marked processed only once every message's
FSM turn has been attempted successfully — a failed turn leaves the event
unprocessed so the next claim (BackgroundTask retry or worker sweep) retries
it, closing the race that used to let a message go through storage without
ever reaching the FSM.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from jan_setu.auth import verify_code_from_whatsapp
from jan_setu.config import Settings
from jan_setu.whatsapp import copy as msg
from jan_setu.whatsapp.conversation import (
    STATE_AWAITING_CONFIRMATION,
    STATE_PHOTO_MISMATCH,
    OutboundIntent,
    advance,
    build_confirmation_intent,
    build_mismatch_intent,
    is_status_query,
    is_verification_code,
)
from jan_setu.db import AsyncSessionLocal, utc_now
from jan_setu.whatsapp.dispatch import send_pending
from jan_setu.pipeline.geocoding import reverse_geocode_cached
from jan_setu.logctx import request_id_var
from jan_setu.pipeline.media import upload_whatsapp_media
from jan_setu.pipeline import (
    FinalizeOutcome,
    PipelineResult,
    cancel_grievance,
    finalize_grievance,
    recheck_image,
    render_confirmation_summary,
    run_pipeline,
)
from jan_setu.repositories import (
    annotate_consumption,
    claim_event,
    claim_inbound,
    create_draft_grievance,
    fetch_stuck_processing,
    fetch_unprocessed_event_ids,
    get_contact,
    get_grievance,
    get_user_by_contact_id,
    list_grievances_for_contact,
    lock_contact_and_get_conversation,
    mark_event_processed,
    set_grievance_fields,
    store_incoming_messages,
    store_outgoing_pending,
    upsert_contact,
    upsert_conversation_state,
)
from jan_setu.whatsapp.client import (
    IncomingWhatsAppMessage,
    WhatsAppCloudClient,
    build_text_payload,
    iter_incoming_messages,
)

logger = logging.getLogger(__name__)

EVENT_LEASE_SECONDS = 60
MAX_EVENT_ATTEMPTS = 5
STUCK_PROCESSING_AFTER_SECONDS = 300


async def drive_event(settings: Settings, http_client: httpx.AsyncClient, event_id: UUID) -> None:
    """Claim and fully process one webhook event. Safe to call concurrently
    for the same event from multiple callers (BackgroundTask + worker) — only
    one wins the claim."""
    request_id_var.set(str(uuid4()))

    async with AsyncSessionLocal() as session:
        claim = await claim_event(session, event_id=event_id, lease_seconds=EVENT_LEASE_SECONDS)
        await session.commit()
    if claim is None:
        return

    if claim["attempt_count"] > MAX_EVENT_ATTEMPTS:
        async with AsyncSessionLocal() as session:
            await mark_event_processed(session, event_id=event_id)
            await session.commit()
        logger.warning(
            "event_poisoned", extra={"event_id": str(event_id), "attempts": claim["attempt_count"]}
        )
        return

    messages = iter_incoming_messages(claim["payload"])
    async with AsyncSessionLocal() as session:
        try:
            stored = await store_incoming_messages(session, messages)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("event_store_failed", extra={"event_id": str(event_id)})
            return  # leave unprocessed; the lease expiry drives a retry

    messages_stored = sum(1 for item in stored if item.created)

    if settings.auto_reply_enabled:
        fresh = [incoming for incoming, item in zip(messages, stored) if item.created]
        fresh.sort(key=lambda m: m.received_at)
        client = WhatsAppCloudClient(settings, http_client)
        all_ok = True
        for incoming in fresh:
            try:
                await _handle_inbound(settings, client, http_client, incoming)
            except Exception:
                all_ok = False
                logger.exception(
                    "auto_reply_failed", extra={"meta_message_id": incoming.meta_message_id}
                )
        if not all_ok:
            return  # leave unprocessed; already-consumed messages are no-ops on retry

    async with AsyncSessionLocal() as session:
        await mark_event_processed(session, event_id=event_id)
        await session.commit()
    logger.info(
        "event_processed", extra={"event_id": str(event_id), "messages_stored": messages_stored}
    )


async def process_pending_events(
    settings: Settings, http_client: httpx.AsyncClient, *, batch_size: int
) -> int:
    """Worker-side sweep: drive any event whose lease is free (never claimed,
    or a crashed claimant's lease expired)."""
    async with AsyncSessionLocal() as session:
        event_ids = await fetch_unprocessed_event_ids(session, limit=batch_size)
    for event_id in event_ids:
        await drive_event(settings, http_client, event_id)
    return len(event_ids)


async def _render_status_reply(contact_id: Any) -> str:
    async with AsyncSessionLocal() as session:
        grievances = await list_grievances_for_contact(session, contact_id=contact_id, limit=5)
    if not grievances:
        return msg.STATUS_EMPTY
    lines = [msg.STATUS_HEADER]
    for grievance in grievances:
        lines.append(
            msg.STATUS_LINE.format(
                human_id=grievance.human_id,
                category=(grievance.category or "uncategorised").replace("_", " "),
                status=grievance.status,
            )
        )
    return "".join(lines)


async def _send_standalone_reply(
    settings: Settings,
    client: WhatsAppCloudClient,
    *,
    wa_id: str,
    body: str,
    reply_kind: str,
    idempotency_key: str,
) -> None:
    async with AsyncSessionLocal() as session:
        contact = await upsert_contact(session, wa_id=wa_id)
        row = await store_outgoing_pending(
            session,
            contact_id=contact.id,
            conversation_id=None,
            reply_kind=reply_kind,
            message_type="text",
            text_body=body,
            payload=build_text_payload(to=wa_id, body=body),
            idempotency_key=idempotency_key,
            in_response_to_message_id=None,
        )
        await session.commit()
        row_id = row.id if row is not None else None
    if row_id is not None:
        async with AsyncSessionLocal() as send_session:
            await send_pending(send_session, settings, client, row_id)


async def _handle_inbound(
    settings: Settings,
    client: WhatsAppCloudClient,
    http_client: httpx.AsyncClient,
    incoming: IncomingWhatsAppMessage,
) -> None:
    # Geocode BEFORE taking the conversation lock — it depends only on lat/lon
    # and would otherwise hold the lock across a slow external call.
    geocode = None
    if incoming.message_type == "location" and incoming.location_latitude is not None:
        async with AsyncSessionLocal() as geo_session:
            geocode = await reverse_geocode_cached(
                geo_session,
                settings,
                incoming.location_latitude,
                incoming.location_longitude,
                http_client,
            )

    pending_ids: list[UUID] = []
    action: str | None = None
    context_after: dict[str, Any] | None = None
    contact_id: UUID | None = None

    async with AsyncSessionLocal() as session:
        try:
            contact = await upsert_contact(
                session, wa_id=incoming.wa_id, profile_name=incoming.profile_name
            )
            contact_id = contact.id
            if not await claim_inbound(session, inbound_message_id=incoming.meta_message_id):
                await session.commit()  # replay: already consumed
                return

            # Pre-FSM intercept: a reverse-OTP verification code can arrive at
            # any conversation state (or none) — it always short-circuits.
            if incoming.text_body and is_verification_code(incoming.text_body):
                reply_body = await verify_code_from_whatsapp(
                    session,
                    wa_id=incoming.wa_id,
                    contact_id=str(contact.id),
                    code_text=incoming.text_body,
                )
                await annotate_consumption(
                    session,
                    inbound_message_id=incoming.meta_message_id,
                    conversation_id=None,
                    state_before=None,
                    state_after=None,
                )
                row = await store_outgoing_pending(
                    session,
                    contact_id=contact.id,
                    conversation_id=None,
                    reply_kind="verify_code",
                    message_type="text",
                    text_body=reply_body,
                    payload=build_text_payload(to=incoming.wa_id, body=reply_body),
                    idempotency_key=f"verify:{incoming.meta_message_id}",
                    in_response_to_message_id=incoming.meta_message_id,
                )
                if row is not None:
                    pending_ids.append(row.id)
                await session.commit()
                for message_id in pending_ids:
                    async with AsyncSessionLocal() as send_session:
                        await send_pending(send_session, settings, client, message_id)
                return

            conversation = await lock_contact_and_get_conversation(
                session, contact_id=contact.id, ttl_hours=settings.conversation_ttl_hours
            )

            # Pre-FSM intercept: "status" with no active conversation.
            if conversation is None and incoming.text_body and is_status_query(incoming.text_body):
                reply_body = await _render_status_reply(contact.id)
                await annotate_consumption(
                    session,
                    inbound_message_id=incoming.meta_message_id,
                    conversation_id=None,
                    state_before=None,
                    state_after=None,
                )
                row = await store_outgoing_pending(
                    session,
                    contact_id=contact.id,
                    conversation_id=None,
                    reply_kind="status_query",
                    message_type="text",
                    text_body=reply_body,
                    payload=build_text_payload(to=incoming.wa_id, body=reply_body),
                    idempotency_key=f"status:{incoming.meta_message_id}",
                    in_response_to_message_id=incoming.meta_message_id,
                )
                if row is not None:
                    pending_ids.append(row.id)
                await session.commit()
                for message_id in pending_ids:
                    async with AsyncSessionLocal() as send_session:
                        await send_pending(send_session, settings, client, message_id)
                return

            state_before = conversation.state if conversation else None
            result = advance(
                wa_id=incoming.wa_id,
                state=state_before,
                context=conversation.context if conversation else None,
                inbound=incoming,
                geocode=geocode,
            )
            conversation = await upsert_conversation_state(
                session,
                conversation=conversation,
                contact_id=contact.id,
                state=result.state,
                context=result.context,
                last_user_message_at=incoming.received_at,
                ttl_hours=settings.conversation_ttl_hours,
                service_window_hours=settings.service_window_hours,
            )

            if result.action == "start_pipeline":
                user = await get_user_by_contact_id(session, contact_id=contact.id)
                grievance, _created = await create_draft_grievance(
                    session,
                    contact_id=contact.id,
                    conversation_id=conversation.id,
                    user_id=user.id if user else None,
                    source="whatsapp",
                    context=result.context,
                )
                draft = {**result.context.get("draft", {}), "grievance_id": str(grievance.id)}
                conversation.context = {**result.context, "draft": draft}
            elif result.action == "recheck_photo":
                # The citizen sent a replacement photo while in photo_mismatch —
                # write the new WhatsApp media id onto the grievance row so the
                # upcoming recheck_image() looks at THIS photo, not the original.
                await set_grievance_fields(
                    session,
                    grievance_id=result.context["draft"]["grievance_id"],
                    photo_media_id=result.context["photo"].get("media_id"),
                    photo_path=None,
                )

            await annotate_consumption(
                session,
                inbound_message_id=incoming.meta_message_id,
                conversation_id=conversation.id,
                state_before=state_before,
                state_after=result.state,
            )

            for intent in result.intents:
                idempotency_key = (
                    f"{conversation.id}:{incoming.meta_message_id}:{intent.reply_kind}"
                )
                row = await store_outgoing_pending(
                    session,
                    contact_id=contact.id,
                    conversation_id=conversation.id,
                    reply_kind=intent.reply_kind,
                    message_type=intent.message_type,
                    text_body=intent.text_body,
                    payload=intent.payload,
                    idempotency_key=idempotency_key,
                    in_response_to_message_id=incoming.meta_message_id,
                )
                if row is not None:
                    pending_ids.append(row.id)

            if result.close:
                conversation.active = False

            action = result.action
            context_after = conversation.context
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Persist-before-send: replies are committed as `pending`; send them now. A
    # crash here leaves them for the worker sweep, never lost.
    for message_id in pending_ids:
        async with AsyncSessionLocal() as send_session:
            await send_pending(send_session, settings, client, message_id)

    if action in ("start_pipeline", "recheck_photo", "proceed_without_photo"):
        assert context_after is not None
        draft_id = context_after["draft"]["grievance_id"]
        if action == "start_pipeline":
            await run_pipeline_followup(
                settings,
                client,
                http_client,
                contact_id=contact_id,
                wa_id=incoming.wa_id,
                grievance_id=draft_id,
            )
        else:
            await recheck_followup(
                settings,
                client,
                http_client,
                contact_id=contact_id,
                wa_id=incoming.wa_id,
                grievance_id=draft_id,
                proceed_without_photo=(action == "proceed_without_photo"),
            )
    elif action == "finalize":
        assert context_after is not None
        await finalize_followup(
            settings,
            client,
            http_client,
            wa_id=incoming.wa_id,
            grievance_id=context_after["draft"]["grievance_id"],
        )
    elif action == "cancel":
        assert context_after is not None
        await cancel_followup(
            settings,
            client,
            wa_id=incoming.wa_id,
            grievance_id=context_after["draft"]["grievance_id"],
        )


async def run_pipeline_followup(
    settings: Settings,
    client: WhatsAppCloudClient,
    http_client: httpx.AsyncClient,
    *,
    contact_id: UUID,
    wa_id: str,
    grievance_id: str,
) -> None:
    try:
        result = await run_pipeline(grievance_id, settings, http_client)
    except Exception:
        logger.exception("pipeline_run_failed", extra={"grievance_id": grievance_id})
        return
    await _send_pipeline_followup_message(
        settings,
        client,
        http_client,
        contact_id=contact_id,
        wa_id=wa_id,
        grievance_id=grievance_id,
        result=result,
    )


async def recheck_followup(
    settings: Settings,
    client: WhatsAppCloudClient,
    http_client: httpx.AsyncClient,
    *,
    contact_id: UUID,
    wa_id: str,
    grievance_id: str,
    proceed_without_photo: bool,
) -> None:
    try:
        result = await recheck_image(
            grievance_id, settings, http_client, proceed_without_photo=proceed_without_photo
        )
    except Exception:
        logger.exception("pipeline_recheck_failed", extra={"grievance_id": grievance_id})
        return
    await _send_pipeline_followup_message(
        settings,
        client,
        http_client,
        contact_id=contact_id,
        wa_id=wa_id,
        grievance_id=grievance_id,
        result=result,
    )


async def _send_pipeline_followup_message(
    settings: Settings,
    client: WhatsAppCloudClient,
    http_client: httpx.AsyncClient,
    *,
    contact_id: UUID,
    wa_id: str,
    grievance_id: str,
    result: PipelineResult,
) -> None:
    async with AsyncSessionLocal() as session:
        conversation = await lock_contact_and_get_conversation(
            session, contact_id=contact_id, ttl_hours=settings.conversation_ttl_hours
        )
        if conversation is None:
            logger.warning(
                "pipeline_followup_no_conversation", extra={"grievance_id": grievance_id}
            )
            return

        intent: OutboundIntent
        if result.status == "photo_mismatch":
            conversation.state = STATE_PHOTO_MISMATCH
            intent = build_mismatch_intent(wa_id)
        else:
            grievance = await get_grievance(session, grievance_id=grievance_id)
            summary_text = render_confirmation_summary(grievance)
            pdf_media_id: str | None = None
            if grievance.pdf_path:
                try:
                    pdf_bytes = Path(grievance.pdf_path).read_bytes()
                    pdf_media_id = await upload_whatsapp_media(
                        http_client,
                        settings,
                        data=pdf_bytes,
                        filename=f"{grievance.human_id}.pdf",
                        mime_type="application/pdf",
                    )
                except Exception:
                    logger.warning("pdf_upload_failed", extra={"grievance_id": grievance_id})
            conversation.state = STATE_AWAITING_CONFIRMATION
            body = msg.PDF_CONFIRM.format(summary=summary_text)
            intent = build_confirmation_intent(
                wa_id=wa_id, draft_id=str(grievance_id), header_media_id=pdf_media_id, body=body
            )

        idempotency_key = f"{conversation.id}:pipeline:{result.status}:{grievance_id}"
        row = await store_outgoing_pending(
            session,
            contact_id=contact_id,
            conversation_id=conversation.id,
            reply_kind=intent.reply_kind,
            message_type=intent.message_type,
            text_body=intent.text_body,
            payload=intent.payload,
            idempotency_key=idempotency_key,
            in_response_to_message_id=None,
        )
        await session.commit()
        row_id = row.id if row is not None else None

    if row_id is not None:
        async with AsyncSessionLocal() as send_session:
            await send_pending(send_session, settings, client, row_id)


async def finalize_followup(
    settings: Settings,
    client: WhatsAppCloudClient,
    http_client: httpx.AsyncClient,
    *,
    wa_id: str,
    grievance_id: str,
) -> None:
    try:
        outcome: FinalizeOutcome = await finalize_grievance(
            settings, http_client, grievance_id=grievance_id
        )
    except Exception:
        logger.exception("finalize_failed", extra={"grievance_id": grievance_id})
        return
    body = msg.REGISTERED_FINAL.format(grievance_id=outcome.human_id)
    if outcome.status == "duplicate" and outcome.report_count:
        body += msg.DUPLICATE_NOTE.format(count=outcome.report_count)
    await _send_standalone_reply(
        settings,
        client,
        wa_id=wa_id,
        body=body,
        reply_kind="registered_final",
        idempotency_key=f"registered_final:{grievance_id}",
    )


async def cancel_followup(
    settings: Settings, client: WhatsAppCloudClient, *, wa_id: str, grievance_id: str
) -> None:
    await cancel_grievance(grievance_id=grievance_id)
    await _send_standalone_reply(
        settings,
        client,
        wa_id=wa_id,
        body=msg.CANCELLED,
        reply_kind="cancelled",
        idempotency_key=f"cancelled:{grievance_id}",
    )


async def sweep_stuck_processing(
    settings: Settings, http_client: httpx.AsyncClient, *, limit: int
) -> int:
    """Recovery for a crash mid-pipeline (draft/processing grievance whose
    follow-up message was never sent): re-run the pipeline and resend the
    follow-up. Called from the worker loop."""
    threshold = utc_now() - timedelta(seconds=STUCK_PROCESSING_AFTER_SECONDS)
    async with AsyncSessionLocal() as session:
        grievance_ids = await fetch_stuck_processing(session, older_than=threshold, limit=limit)
        contacts: dict[str, tuple[UUID, str]] = {}
        for grievance_id in grievance_ids:
            grievance = await get_grievance(session, grievance_id=grievance_id)
            if grievance is None:
                continue
            contact = await get_contact(session, contact_id=grievance.contact_id)
            if contact is not None:
                contacts[str(grievance_id)] = (grievance.contact_id, contact.wa_id)

    if not contacts:
        return 0

    client = WhatsAppCloudClient(settings, http_client)
    for grievance_id, (contact_id, wa_id) in contacts.items():
        try:
            await run_pipeline_followup(
                settings,
                client,
                http_client,
                contact_id=contact_id,
                wa_id=wa_id,
                grievance_id=grievance_id,
            )
        except Exception:
            logger.exception(
                "stuck_processing_recovery_failed", extra={"grievance_id": grievance_id}
            )
    return len(contacts)
