"""The conversation finite-state machine — pure transition logic, no I/O.

``advance`` takes the current state + context, the parsed inbound message, and an
optional pre-computed reverse-geocode result, and returns the next state, the new
context, and the outbound replies to send. Persisting, locking, geocoding,
running the classification pipeline and sending all happen in the caller
(``processing.py``/``pipeline.py``); keeping this function pure makes every
transition unit-testable without a database.

Stale-confirm safety: the staged-location token (the wamid of the location the
user shared) is encoded into the Yes/No button IDs. A tap echoes that token back,
so a "Yes" on an old confirmation card carries an old token and is ignored once a
newer location has been staged — no dispatcher/context write-back needed. The
same technique guards the post-pipeline Confirm/Cancel card: its buttons carry
the draft grievance id, so a stale card from a superseded draft is a no-op.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from jan_setu.db import utc_now
from jan_setu.whatsapp import copy as msg
from jan_setu.whatsapp.client import (
    IncomingWhatsAppMessage,
    build_document_button_payload,
    build_location_request_payload,
    build_reply_buttons_payload,
    build_text_payload,
)

STATE_AWAITING_LOCATION = "awaiting_location"
STATE_CONFIRMING_LOCATION = "confirming_location"
STATE_AWAITING_ISSUE = "awaiting_issue"
STATE_AWAITING_PHOTO = "awaiting_photo"
STATE_PROCESSING = "processing"
STATE_PHOTO_MISMATCH = "photo_mismatch"
STATE_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATE_DONE = "done"
STATE_EXPIRED = "expired"

INITIAL_STATE = STATE_AWAITING_LOCATION

# Inbound types that count as grievance content while accumulating the issue.
ISSUE_CONTENT_TYPES = frozenset({"text", "audio", "voice", "image", "video", "document"})

CONFIRM_GRV_YES_ID = "grv_confirm"
CONFIRM_GRV_NO_ID = "grv_cancel"
PHOTO_CONTINUE_ID = "photo_continue"


@dataclass
class OutboundIntent:
    reply_kind: str
    message_type: str  # "text" | "interactive" | "document"
    payload: dict[str, Any]
    text_body: str | None


@dataclass
class FsmResult:
    state: str
    context: dict[str, Any]
    intents: list[OutboundIntent] = field(default_factory=list)
    # A side effect the driver (processing.py) must perform outside this pure
    # function: "start_pipeline" | "recheck_photo" | "proceed_without_photo" |
    # "finalize" | "cancel" | None.
    action: str | None = None
    # When True the driver deactivates the conversation after handling `action`,
    # so the contact can immediately start a new complaint.
    close: bool = False


def default_context() -> dict[str, Any]:
    return {
        "location": {
            "lat": None,
            "lon": None,
            "display_address": None,
            "source_message_id": None,
            "geocode_status": None,
            "geocoder_provider": None,
            "confirmed_at": None,
        },
        "issue": {
            "status": "awaiting_input",
            "messages": [],
            "source_message_id": None,
            "text": None,
            "language": None,
        },
        "photo": {"media_id": None, "mime_type": None, "skipped": None},
        "draft": {"grievance_id": None, "recheck_count": 0},
    }


def parse_confirm_reply(reply_id: str | None) -> tuple[str | None, str | None]:
    """Split a confirm button id ``"<base>:<token>"`` into (base, token)."""
    if not reply_id:
        return None, None
    base, _, token = reply_id.partition(":")
    return base, (token or None)


def _address_text(geocode: Any, lat: float, lon: float) -> str:
    if geocode is not None and getattr(geocode, "display_address", None):
        return geocode.display_address
    return msg.RAW_COORDINATES.format(lat=lat, lon=lon)


def _stage_location_and_confirm(
    *,
    wa_id: str,
    context: dict[str, Any],
    inbound: IncomingWhatsAppMessage,
    geocode: Any,
    body_prefix: str = "",
) -> FsmResult:
    lat = inbound.location_latitude
    lon = inbound.location_longitude
    token = inbound.meta_message_id

    context["location"].update(
        {
            "lat": lat,
            "lon": lon,
            "display_address": getattr(geocode, "display_address", None),
            "source_message_id": token,
            "geocode_status": getattr(geocode, "status", None),
            "confirmed_at": None,
        }
    )

    body = body_prefix + msg.CONFIRM_LOCATION.format(address=_address_text(geocode, lat, lon))
    buttons = [
        (f"{msg.CONFIRM_YES_ID}:{token}", msg.CONFIRM_YES_TITLE),
        (f"{msg.CONFIRM_NO_ID}:{token}", msg.CONFIRM_NO_TITLE),
    ]
    intent = OutboundIntent(
        reply_kind="confirm_location",
        message_type="interactive",
        payload=build_reply_buttons_payload(to=wa_id, body=body, buttons=buttons),
        text_body=body,
    )
    return FsmResult(state=STATE_CONFIRMING_LOCATION, context=context, intents=[intent])


def _location_request_intent(wa_id: str, body: str, reply_kind: str) -> OutboundIntent:
    return OutboundIntent(
        reply_kind=reply_kind,
        message_type="interactive",
        payload=build_location_request_payload(to=wa_id, body=body),
        text_body=body,
    )


def _text_intent(wa_id: str, body: str, reply_kind: str) -> OutboundIntent:
    return OutboundIntent(
        reply_kind=reply_kind,
        message_type="text",
        payload=build_text_payload(to=wa_id, body=body),
        text_body=body,
    )


def _buttons_intent(
    wa_id: str, body: str, buttons: list[tuple[str, str]], reply_kind: str
) -> OutboundIntent:
    return OutboundIntent(
        reply_kind=reply_kind,
        message_type="interactive",
        payload=build_reply_buttons_payload(to=wa_id, body=body, buttons=buttons),
        text_body=body,
    )


def _ask_issue_intent(wa_id: str) -> OutboundIntent:
    return _buttons_intent(
        wa_id, msg.ASK_ISSUE, [(msg.ISSUE_DONE_ID, msg.ISSUE_DONE_TITLE)], "ask_issue"
    )


def _photo_prompt_intent(wa_id: str, body: str, reply_kind: str) -> OutboundIntent:
    return _buttons_intent(
        wa_id,
        body,
        [(msg.PHOTO_SHARE_ID, msg.PHOTO_SHARE_TITLE), (msg.PHOTO_SKIP_ID, msg.PHOTO_SKIP_TITLE)],
        reply_kind,
    )


def _still_processing_intent(wa_id: str) -> OutboundIntent:
    return _text_intent(wa_id, msg.STILL_PROCESSING, "still_processing")


def _mismatch_prompt_intent(wa_id: str, note: str | None = None) -> OutboundIntent:
    body = msg.IMAGE_MISMATCH_PROMPT.format(note=note or "")
    return _buttons_intent(
        wa_id,
        body,
        [
            (msg.PHOTO_SHARE_ID, msg.PHOTO_SHARE_TITLE),
            (PHOTO_CONTINUE_ID, msg.PHOTO_CONTINUE_TITLE),
        ],
        "image_mismatch",
    )


def is_verification_code(text_body: str | None) -> bool:
    import re

    return bool(text_body and re.fullmatch(r"JS-[A-Z0-9]{6}", text_body.strip().upper()))


def is_status_query(text_body: str | None) -> bool:
    if not text_body:
        return False
    normalized = text_body.strip().lower()
    return normalized in {"status", "स्थिति"}


def advance(
    *,
    wa_id: str,
    state: str | None,
    context: dict[str, Any] | None,
    inbound: IncomingWhatsAppMessage,
    geocode: Any = None,
) -> FsmResult:
    """Compute the next state + replies for one inbound message.

    ``state is None`` means there is no active conversation yet (new or expired).
    ``geocode`` is the pre-computed reverse-geocode result for a location inbound,
    or None.
    """
    context = deepcopy(context) if context else default_context()
    context.setdefault("draft", {"grievance_id": None, "recheck_count": 0})
    is_location = inbound.message_type == "location" and inbound.location_latitude is not None

    # New / expired conversation: greet AND ask in a single message. WhatsApp does
    # not guarantee display order for messages sent in the same second, so the
    # greeting is merged into the first functional message rather than sent as a
    # separate bubble that could render after it.
    if state is None or state == STATE_EXPIRED:
        greeting_prefix = f"{msg.GREETING}\n\n"
        if is_location:
            return _stage_location_and_confirm(
                wa_id=wa_id,
                context=context,
                inbound=inbound,
                geocode=geocode,
                body_prefix=greeting_prefix,
            )
        return FsmResult(
            state=STATE_AWAITING_LOCATION,
            context=context,
            intents=[
                _location_request_intent(
                    wa_id, f"{greeting_prefix}{msg.LOCATION_REQUEST}", "greeting_location"
                )
            ],
        )

    if state == STATE_AWAITING_LOCATION:
        if is_location:
            return _stage_location_and_confirm(
                wa_id=wa_id, context=context, inbound=inbound, geocode=geocode
            )
        return FsmResult(
            state=STATE_AWAITING_LOCATION,
            context=context,
            intents=[_location_request_intent(wa_id, msg.LOCATION_REPROMPT, "location_reprompt")],
        )

    if state == STATE_CONFIRMING_LOCATION:
        if is_location:
            # A fresh location supersedes the staged one (new token).
            return _stage_location_and_confirm(
                wa_id=wa_id, context=context, inbound=inbound, geocode=geocode
            )

        base, token = parse_confirm_reply(inbound.reply_id)
        staged_token = context["location"].get("source_message_id")
        if token == staged_token and base == msg.CONFIRM_YES_ID:
            context["location"]["confirmed_at"] = utc_now().isoformat()
            return FsmResult(
                state=STATE_AWAITING_ISSUE,
                context=context,
                intents=[_ask_issue_intent(wa_id)],
            )
        if token == staged_token and base == msg.CONFIRM_NO_ID:
            context["location"] = default_context()["location"]
            return FsmResult(
                state=STATE_AWAITING_LOCATION,
                context=context,
                intents=[_location_request_intent(wa_id, msg.LOCATION_REQUEST, "location_request")],
            )

        # Stale token, unknown reply, or free text while confirming: re-show the
        # confirmation for the currently staged location (no state change).
        lat = context["location"].get("lat")
        lon = context["location"].get("lon")
        address = context["location"].get("display_address") or (
            msg.RAW_COORDINATES.format(lat=lat, lon=lon) if lat is not None else ""
        )
        body = msg.CONFIRM_LOCATION.format(address=address)
        buttons = [
            (f"{msg.CONFIRM_YES_ID}:{staged_token}", msg.CONFIRM_YES_TITLE),
            (f"{msg.CONFIRM_NO_ID}:{staged_token}", msg.CONFIRM_NO_TITLE),
        ]
        return FsmResult(
            state=STATE_CONFIRMING_LOCATION,
            context=context,
            intents=[
                OutboundIntent(
                    reply_kind="confirm_location",
                    message_type="interactive",
                    payload=build_reply_buttons_payload(to=wa_id, body=body, buttons=buttons),
                    text_body=body,
                )
            ],
        )

    if state == STATE_AWAITING_ISSUE:
        issue = context["issue"]
        issue.setdefault("messages", [])  # backward-compat for slice-1 conversations
        base, _ = parse_confirm_reply(inbound.reply_id)

        if base == msg.ISSUE_DONE_ID:
            if not issue["messages"]:
                # Done tapped with nothing captured — guard against empty tickets.
                return FsmResult(
                    state=STATE_AWAITING_ISSUE,
                    context=context,
                    intents=[_text_intent(wa_id, msg.ISSUE_EMPTY, "issue_empty")],
                )
            body = f"{msg.ISSUE_RECEIVED}\n\n{msg.PHOTO_PROMPT}"
            return FsmResult(
                state=STATE_AWAITING_PHOTO,
                context=context,
                intents=[_photo_prompt_intent(wa_id, body, "photo_prompt")],
            )

        if inbound.message_type in ISSUE_CONTENT_TYPES:
            issue["messages"].append(
                {
                    "message_id": inbound.meta_message_id,
                    "received_at": inbound.received_at.isoformat(),
                    "type": inbound.message_type,
                    "text": inbound.text_body,
                    "media_id": inbound.media_id,
                    "mime_type": inbound.media_mime_type,
                }
            )
            if issue.get("source_message_id") is None:
                issue["source_message_id"] = inbound.meta_message_id
            # Accumulate silently; the Done button (already shown) ends the step.
            return FsmResult(state=STATE_AWAITING_ISSUE, context=context, intents=[])

        # Unrecognised input (e.g. a stale button) — ignore.
        return FsmResult(state=STATE_AWAITING_ISSUE, context=context, intents=[])

    if state == STATE_AWAITING_PHOTO:
        base, _ = parse_confirm_reply(inbound.reply_id)

        if inbound.message_type == "image" and inbound.media_id:
            context["photo"] = {
                "media_id": inbound.media_id,
                "mime_type": inbound.media_mime_type,
                "skipped": False,
            }
            return FsmResult(
                state=STATE_PROCESSING,
                context=context,
                intents=[_text_intent(wa_id, msg.PROCESSING_WAIT, "processing_wait")],
                action="start_pipeline",
            )

        if base == msg.PHOTO_SKIP_ID:
            context["photo"] = {"media_id": None, "mime_type": None, "skipped": True}
            return FsmResult(
                state=STATE_PROCESSING,
                context=context,
                intents=[_text_intent(wa_id, msg.PROCESSING_WAIT, "processing_wait")],
                action="start_pipeline",
            )

        if base == msg.PHOTO_SHARE_ID:
            return FsmResult(
                state=STATE_AWAITING_PHOTO,
                context=context,
                intents=[_text_intent(wa_id, msg.PHOTO_INSTRUCTION, "photo_instruction")],
            )

        # Anything else while waiting for a photo: re-show the photo choice.
        return FsmResult(
            state=STATE_AWAITING_PHOTO,
            context=context,
            intents=[_photo_prompt_intent(wa_id, msg.PHOTO_PROMPT, "photo_prompt")],
        )

    if state == STATE_PROCESSING:
        # The pipeline (STT/classification/image-check) is running outside the
        # FSM; any inbound that arrives before it finishes just gets a "please
        # wait" — the follow-up transition to awaiting_confirmation/
        # photo_mismatch is driven by the pipeline result, not by an inbound.
        return FsmResult(
            state=STATE_PROCESSING, context=context, intents=[_still_processing_intent(wa_id)]
        )

    if state == STATE_PHOTO_MISMATCH:
        base, _ = parse_confirm_reply(inbound.reply_id)

        if inbound.message_type == "image" and inbound.media_id:
            context["photo"] = {
                "media_id": inbound.media_id,
                "mime_type": inbound.media_mime_type,
                "skipped": False,
            }
            context["draft"]["recheck_count"] = context["draft"].get("recheck_count", 0) + 1
            return FsmResult(
                state=STATE_PROCESSING,
                context=context,
                intents=[_text_intent(wa_id, msg.PROCESSING_WAIT, "processing_wait")],
                action="recheck_photo",
            )

        if base == PHOTO_CONTINUE_ID:
            return FsmResult(
                state=STATE_PROCESSING,
                context=context,
                intents=[_text_intent(wa_id, msg.PROCESSING_WAIT, "processing_wait")],
                action="proceed_without_photo",
            )

        # Anything else: re-show the mismatch prompt (no state change).
        return FsmResult(
            state=STATE_PHOTO_MISMATCH, context=context, intents=[_mismatch_prompt_intent(wa_id)]
        )

    if state == STATE_AWAITING_CONFIRMATION:
        base, token = parse_confirm_reply(inbound.reply_id)
        draft_id = context["draft"].get("grievance_id")

        if token == draft_id and base == CONFIRM_GRV_YES_ID:
            return FsmResult(state=STATE_DONE, context=context, action="finalize", close=True)
        if token == draft_id and base == CONFIRM_GRV_NO_ID:
            return FsmResult(state=STATE_DONE, context=context, action="cancel", close=True)

        # Stale token or anything else: no re-prompt here (the confirm card,
        # including the PDF, was already sent by the pipeline follow-up and is
        # not reconstructible purely — the driver may resend it if needed).
        return FsmResult(state=STATE_AWAITING_CONFIRMATION, context=context, intents=[])

    if state == STATE_DONE:
        # Terminal: ignore further messages (the driver closes the conversation
        # on entry to this state, so a new inbound normally starts a fresh one).
        return FsmResult(state=STATE_DONE, context=context, intents=[])

    # Unknown state: do nothing rather than guess.
    return FsmResult(state=state, context=context, intents=[])


def build_confirmation_intent(
    *, wa_id: str, draft_id: str, header_media_id: str | None, body: str
) -> OutboundIntent:
    """The post-pipeline PDF confirm card (driven by the pipeline follow-up in
    processing.py, not by an inbound message, so it lives outside ``advance``).
    Falls back to a plain buttons message (no PDF header) if the PDF upload
    to WhatsApp failed — the citizen can still confirm/cancel from the text."""
    buttons = [
        (f"{CONFIRM_GRV_YES_ID}:{draft_id}", msg.CONFIRM_GRV_YES_TITLE),
        (f"{CONFIRM_GRV_NO_ID}:{draft_id}", msg.CONFIRM_GRV_NO_TITLE),
    ]
    if header_media_id is None:
        return _buttons_intent(wa_id, body, buttons, "pdf_confirm")
    return OutboundIntent(
        reply_kind="pdf_confirm",
        message_type="interactive",
        payload=build_document_button_payload(
            to=wa_id,
            header_media_id=header_media_id,
            header_filename=f"{draft_id}.pdf",
            body=body,
            buttons=buttons,
        ),
        text_body=body,
    )


def build_mismatch_intent(wa_id: str, note: str | None = None) -> OutboundIntent:
    """The image-mismatch prompt, sent by the pipeline follow-up on first entry
    into ``STATE_PHOTO_MISMATCH`` (re-prompts from within ``advance`` reuse the
    same builder)."""
    return _mismatch_prompt_intent(wa_id, note)
