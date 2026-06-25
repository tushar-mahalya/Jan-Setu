from datetime import datetime, timezone

from jan_setu import copy as msg
from jan_setu.conversation import (
    STATE_AWAITING_ISSUE,
    STATE_AWAITING_LOCATION,
    STATE_AWAITING_PHOTO,
    STATE_CONFIRMING_LOCATION,
    STATE_REGISTERED,
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


def test_awaiting_issue_accumulates_messages_silently():
    context = _confirming_context()
    context["location"]["confirmed_at"] = "2026-06-25T00:00:00+00:00"
    context["issue"]["messages"] = []

    text_msg = _inbound(meta_message_id="wamid.issue1", text_body="no water for 3 days")
    r1 = advance(
        wa_id="911234567890", state=STATE_AWAITING_ISSUE, context=context, inbound=text_msg
    )
    assert r1.state == STATE_AWAITING_ISSUE
    assert r1.intents == []  # silent accumulation, Done button already shown
    assert r1.context["issue"]["source_message_id"] == "wamid.issue1"

    voice_msg = _inbound(
        meta_message_id="wamid.issue2", message_type="audio", text_body=None, media_id="aud-1"
    )
    r2 = advance(
        wa_id="911234567890", state=STATE_AWAITING_ISSUE, context=r1.context, inbound=voice_msg
    )
    ids = [m["message_id"] for m in r2.context["issue"]["messages"]]
    assert ids == ["wamid.issue1", "wamid.issue2"]
    assert r2.context["issue"]["messages"][1]["media_id"] == "aud-1"


def _done(reply_id=msg.ISSUE_DONE_ID):
    return _inbound(
        meta_message_id="wamid.done", message_type="interactive", text_body=None, reply_id=reply_id
    )


def test_done_with_no_messages_reprompts():
    context = _confirming_context()
    context["issue"]["messages"] = []
    result = advance(
        wa_id="911234567890", state=STATE_AWAITING_ISSUE, context=context, inbound=_done()
    )
    assert result.state == STATE_AWAITING_ISSUE  # guard against empty ticket
    assert _kinds(result) == ["issue_empty"]


def test_done_with_messages_advances_to_photo():
    context = _confirming_context()
    context["issue"]["messages"] = [{"message_id": "wamid.i1", "type": "text"}]
    result = advance(
        wa_id="911234567890", state=STATE_AWAITING_ISSUE, context=context, inbound=_done()
    )
    assert result.state == STATE_AWAITING_PHOTO
    assert _kinds(result) == ["photo_prompt"]
    assert "received" in result.intents[0].text_body.lower()


def test_photo_share_sends_instruction():
    context = _confirming_context()
    reply = _inbound(
        meta_message_id="wamid.ps",
        message_type="interactive",
        text_body=None,
        reply_id=msg.PHOTO_SHARE_ID,
    )
    result = advance(
        wa_id="911234567890", state=STATE_AWAITING_PHOTO, context=context, inbound=reply
    )
    assert result.state == STATE_AWAITING_PHOTO
    assert _kinds(result) == ["photo_instruction"]
    assert result.register is False


def test_photo_image_registers():
    context = _confirming_context()
    image = _inbound(
        meta_message_id="wamid.img", message_type="image", text_body=None, media_id="img-99"
    )
    result = advance(
        wa_id="911234567890", state=STATE_AWAITING_PHOTO, context=context, inbound=image
    )
    assert result.state == STATE_REGISTERED
    assert result.register is True
    assert result.context["photo"]["media_id"] == "img-99"
    assert result.intents == []  # confirmation is sent by the caller (needs the id)


def test_photo_skip_registers_without_photo():
    context = _confirming_context()
    reply = _inbound(
        meta_message_id="wamid.skip",
        message_type="interactive",
        text_body=None,
        reply_id=msg.PHOTO_SKIP_ID,
    )
    result = advance(
        wa_id="911234567890", state=STATE_AWAITING_PHOTO, context=context, inbound=reply
    )
    assert result.state == STATE_REGISTERED
    assert result.register is True
    assert result.context["photo"]["skipped"] is True
    assert result.context["photo"]["media_id"] is None


def test_registered_is_terminal():
    context = _confirming_context()
    result = advance(
        wa_id="911234567890",
        state=STATE_REGISTERED,
        context=context,
        inbound=_inbound(text_body="anything"),
    )
    assert result.state == STATE_REGISTERED
    assert result.intents == []
    assert result.register is False


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
