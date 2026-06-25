from datetime import datetime, timezone

from jan_setu import copy as msg
from jan_setu.conversation import (
    STATE_AWAITING_ISSUE,
    STATE_AWAITING_LOCATION,
    STATE_CONFIRMING_LOCATION,
    advance,
)
from jan_setu.geocoding import ReverseGeocode
from jan_setu.whatsapp import IncomingWhatsAppMessage


def _inbound(**overrides) -> IncomingWhatsAppMessage:
    base = {
        "wa_id": "911234567890",
        "profile_name": "Tushar",
        "meta_message_id": "wamid.1",
        "message_type": "text",
        "text_body": "hi",
        "raw_payload": {},
        "received_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return IncomingWhatsAppMessage(**base)


def _location(meta_message_id="wamid.loc", lat=18.5204, lon=73.8567) -> IncomingWhatsAppMessage:
    return _inbound(
        meta_message_id=meta_message_id,
        message_type="location",
        text_body=None,
        location_latitude=lat,
        location_longitude=lon,
    )


def _kinds(result):
    return [intent.reply_kind for intent in result.intents]


def test_new_contact_greets_and_requests_location():
    result = advance(wa_id="911234567890", state=None, context=None, inbound=_inbound())

    assert result.state == STATE_AWAITING_LOCATION
    # Greeting is merged into the single location-request message (WhatsApp does
    # not guarantee ordering of separate messages sent back-to-back).
    assert len(result.intents) == 1
    intent = result.intents[0]
    assert intent.payload["interactive"]["type"] == "location_request_message"
    assert "नमस्ते" in intent.text_body  # greeting present
    assert "location" in intent.text_body.lower()  # ask present


def test_location_triggers_geocode_confirm():
    geocode = ReverseGeocode(status="ok", display_address="Shivajinagar, Pune")
    result = advance(
        wa_id="911234567890",
        state=STATE_AWAITING_LOCATION,
        context=None,
        inbound=_location(),
        geocode=geocode,
    )

    assert result.state == STATE_CONFIRMING_LOCATION
    assert _kinds(result) == ["confirm_location"]
    assert "Shivajinagar, Pune" in result.intents[0].text_body
    loc = result.context["location"]
    assert loc["source_message_id"] == "wamid.loc"
    assert loc["lat"] == 18.5204
    # buttons carry the staged-location token
    buttons = result.intents[0].payload["interactive"]["action"]["buttons"]
    assert buttons[0]["reply"]["id"] == f"{msg.CONFIRM_YES_ID}:wamid.loc"


def test_geocode_failure_falls_back_to_raw_coordinates():
    result = advance(
        wa_id="911234567890",
        state=STATE_AWAITING_LOCATION,
        context=None,
        inbound=_location(),
        geocode=ReverseGeocode(status="failed"),
    )

    assert result.state == STATE_CONFIRMING_LOCATION
    assert "18.52040" in result.intents[0].text_body  # raw coordinate fallback


def test_non_location_while_awaiting_location_reprompts():
    result = advance(
        wa_id="911234567890",
        state=STATE_AWAITING_LOCATION,
        context=None,
        inbound=_inbound(text_body="my road is flooded"),
    )

    assert result.state == STATE_AWAITING_LOCATION
    assert _kinds(result) == ["location_reprompt"]


def _confirming_context(token="wamid.loc"):
    result = advance(
        wa_id="911234567890",
        state=STATE_AWAITING_LOCATION,
        context=None,
        inbound=_location(meta_message_id=token),
        geocode=ReverseGeocode(status="ok", display_address="Shivajinagar, Pune"),
    )
    return result.context


def test_confirm_yes_with_matching_token_advances_to_issue():
    context = _confirming_context(token="wamid.loc")
    reply = _inbound(
        meta_message_id="wamid.yes",
        message_type="interactive",
        text_body=None,
        reply_id=f"{msg.CONFIRM_YES_ID}:wamid.loc",
    )

    result = advance(
        wa_id="911234567890",
        state=STATE_CONFIRMING_LOCATION,
        context=context,
        inbound=reply,
    )

    assert result.state == STATE_AWAITING_ISSUE
    assert _kinds(result) == ["ask_issue"]
    assert result.context["location"]["confirmed_at"] is not None


def test_stale_yes_does_not_advance():
    context = _confirming_context(token="wamid.loc_new")
    stale_reply = _inbound(
        meta_message_id="wamid.yes",
        message_type="interactive",
        text_body=None,
        reply_id=f"{msg.CONFIRM_YES_ID}:wamid.loc_old",  # old token
    )

    result = advance(
        wa_id="911234567890",
        state=STATE_CONFIRMING_LOCATION,
        context=context,
        inbound=stale_reply,
    )

    assert result.state == STATE_CONFIRMING_LOCATION  # no advance
    assert _kinds(result) == ["confirm_location"]  # re-prompts instead


def test_confirm_no_restarts_location():
    context = _confirming_context(token="wamid.loc")
    reply = _inbound(
        meta_message_id="wamid.no",
        message_type="interactive",
        text_body=None,
        reply_id=f"{msg.CONFIRM_NO_ID}:wamid.loc",
    )

    result = advance(
        wa_id="911234567890",
        state=STATE_CONFIRMING_LOCATION,
        context=context,
        inbound=reply,
    )

    assert result.state == STATE_AWAITING_LOCATION
    assert _kinds(result) == ["location_request"]
    assert result.context["location"]["source_message_id"] is None


def test_awaiting_issue_parks_and_records_first_message():
    context = _confirming_context()
    context["location"]["confirmed_at"] = "2026-06-25T00:00:00+00:00"
    grievance = _inbound(meta_message_id="wamid.issue", text_body="no water for 3 days")

    result = advance(
        wa_id="911234567890",
        state=STATE_AWAITING_ISSUE,
        context=context,
        inbound=grievance,
    )

    assert result.state == STATE_AWAITING_ISSUE
    assert result.intents == []  # next slice handles the reply
    assert result.context["issue"]["source_message_id"] == "wamid.issue"


def test_new_contact_sharing_location_first_greets_then_confirms():
    result = advance(
        wa_id="911234567890",
        state=None,
        context=None,
        inbound=_location(),
        geocode=ReverseGeocode(status="ok", display_address="Shivajinagar, Pune"),
    )

    assert result.state == STATE_CONFIRMING_LOCATION
    # Single confirm message with the greeting merged into its body.
    assert _kinds(result) == ["confirm_location"]
    assert "नमस्ते" in result.intents[0].text_body
    assert "Shivajinagar, Pune" in result.intents[0].text_body
