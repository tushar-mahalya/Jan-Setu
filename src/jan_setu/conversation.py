"""The conversation finite-state machine — pure transition logic, no I/O.

``advance`` takes the current state + context, the parsed inbound message, and an
optional pre-computed reverse-geocode result, and returns the next state, the new
context, and the outbound replies to send. Persisting, locking, geocoding and
sending all happen in the caller (``processing.py`` / ``dispatch.py``); keeping
this function pure makes every transition unit-testable without a database.

Stale-confirm safety: the staged-location token (the wamid of the location the
user shared) is encoded into the Yes/No button IDs. A tap echoes that token back,
so a "Yes" on an old confirmation card carries an old token and is ignored once a
newer location has been staged — no dispatcher/context write-back needed.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from jan_setu import copy as msg
from jan_setu.database import utc_now
from jan_setu.whatsapp import (
    IncomingWhatsAppMessage,
    build_location_request_payload,
    build_reply_buttons_payload,
    build_text_payload,
)

STATE_AWAITING_LOCATION = "awaiting_location"
STATE_CONFIRMING_LOCATION = "confirming_location"
STATE_AWAITING_ISSUE = "awaiting_issue"
STATE_EXPIRED = "expired"

INITIAL_STATE = STATE_AWAITING_LOCATION


@dataclass
class OutboundIntent:
    reply_kind: str
    message_type: str  # "text" | "interactive"
    payload: dict[str, Any]
    text_body: str | None


@dataclass
class FsmResult:
    state: str
    context: dict[str, Any]
    intents: list[OutboundIntent] = field(default_factory=list)


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
            "source_message_id": None,
            "text": None,
            "language": None,
        },
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
                intents=[_text_intent(wa_id, msg.ASK_ISSUE, "ask_issue")],
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
        # Next slice consumes the issue. Record the first inbound's id so it is not
        # silently dropped; send nothing here.
        if context["issue"].get("source_message_id") is None:
            context["issue"]["source_message_id"] = inbound.meta_message_id
        return FsmResult(state=STATE_AWAITING_ISSUE, context=context, intents=[])

    # Unknown state: do nothing rather than guess.
    return FsmResult(state=state, context=context, intents=[])
