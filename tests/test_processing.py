"""Unit tests for jan_setu.whatsapp.processing: inbound event driving and the
conversation-turn orchestration around the FSM.

Uses the anyio.run(...) idiom from tests/test_webhook.py (no pytest-asyncio
plugin is configured, so ``async def test_...`` never actually runs).
"""

from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio

from jan_setu.config import Settings
from jan_setu.whatsapp import copy as msg
from jan_setu.whatsapp.client import IncomingWhatsAppMessage
from jan_setu.whatsapp.processing import (
    _handle_inbound,
    _render_status_reply,
    _send_pipeline_followup_message,
    _send_standalone_reply,
    cancel_followup,
    drive_event,
    finalize_followup,
    process_pending_events,
    recheck_followup,
    run_pipeline_followup,
    sweep_stuck_processing,
)

MODULE = "jan_setu.whatsapp.processing"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _session_factory(session):
    """Fake AsyncSessionLocal() -> async context manager yielding ``session``."""

    class CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: CM()


def _multi_session_factory(sessions):
    """Yields a new session from ``sessions`` on each AsyncSessionLocal() call,
    repeating the last one once exhausted."""
    state = {"i": 0}

    class CM:
        async def __aenter__(self):
            idx = min(state["i"], len(sessions) - 1)
            state["i"] += 1
            return sessions[idx]

        async def __aexit__(self, *exc):
            return False

    return lambda: CM()


def _session():
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


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


# ---------------------------------------------------------------------------
# drive_event
# ---------------------------------------------------------------------------


def test_drive_event_returns_early_when_claim_fails():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.claim_event", AsyncMock(return_value=None)),
        ):
            await drive_event(_settings(), MagicMock(), uuid4())

    anyio.run(run)
    session.commit.assert_awaited_once()


def test_drive_event_poisons_after_max_attempts():
    session = _session()
    mark_processed = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(
                f"{MODULE}.claim_event",
                AsyncMock(return_value={"attempt_count": 6, "payload": {}}),
            ),
            patch(f"{MODULE}.mark_event_processed", mark_processed),
        ):
            await drive_event(_settings(), MagicMock(), uuid4())

    anyio.run(run)
    mark_processed.assert_awaited_once()


def test_drive_event_rolls_back_when_store_fails():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(
                f"{MODULE}.claim_event",
                AsyncMock(return_value={"attempt_count": 1, "payload": {}}),
            ),
            patch(f"{MODULE}.iter_incoming_messages", MagicMock(return_value=[])),
            patch(f"{MODULE}.store_incoming_messages", AsyncMock(side_effect=RuntimeError("db"))),
        ):
            await drive_event(_settings(), MagicMock(), uuid4())

    anyio.run(run)
    session.rollback.assert_awaited_once()


def test_drive_event_auto_reply_disabled_marks_processed():
    session = _session()
    mark_processed = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(
                f"{MODULE}.claim_event",
                AsyncMock(return_value={"attempt_count": 1, "payload": {}}),
            ),
            patch(f"{MODULE}.iter_incoming_messages", MagicMock(return_value=[])),
            patch(f"{MODULE}.store_incoming_messages", AsyncMock(return_value=[])),
            patch(f"{MODULE}.mark_event_processed", mark_processed),
        ):
            await drive_event(_settings(auto_reply_enabled=False), MagicMock(), uuid4())

    anyio.run(run)
    mark_processed.assert_awaited_once()


def test_drive_event_auto_reply_success_marks_processed():
    session = _session()
    mark_processed = AsyncMock()
    incoming = _inbound()

    class Stored:
        created = True

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(
                f"{MODULE}.claim_event",
                AsyncMock(return_value={"attempt_count": 1, "payload": {}}),
            ),
            patch(f"{MODULE}.iter_incoming_messages", MagicMock(return_value=[incoming])),
            patch(f"{MODULE}.store_incoming_messages", AsyncMock(return_value=[Stored()])),
            patch(f"{MODULE}.mark_event_processed", mark_processed),
            patch(f"{MODULE}.WhatsAppCloudClient", MagicMock()),
            patch(f"{MODULE}._handle_inbound", AsyncMock(return_value=None)) as handle,
        ):
            await drive_event(_settings(auto_reply_enabled=True), MagicMock(), uuid4())
            return handle

    handle = anyio.run(run)
    handle.assert_awaited_once()
    mark_processed.assert_awaited_once()


def test_drive_event_auto_reply_failure_leaves_unprocessed():
    session = _session()
    mark_processed = AsyncMock()
    incoming = _inbound()

    class Stored:
        created = True

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(
                f"{MODULE}.claim_event",
                AsyncMock(return_value={"attempt_count": 1, "payload": {}}),
            ),
            patch(f"{MODULE}.iter_incoming_messages", MagicMock(return_value=[incoming])),
            patch(f"{MODULE}.store_incoming_messages", AsyncMock(return_value=[Stored()])),
            patch(f"{MODULE}.mark_event_processed", mark_processed),
            patch(f"{MODULE}.WhatsAppCloudClient", MagicMock()),
            patch(f"{MODULE}._handle_inbound", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            await drive_event(_settings(auto_reply_enabled=True), MagicMock(), uuid4())

    anyio.run(run)
    mark_processed.assert_not_awaited()


# ---------------------------------------------------------------------------
# process_pending_events
# ---------------------------------------------------------------------------


def test_process_pending_events_drives_each_id():
    session = _session()
    ids = [uuid4(), uuid4()]

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_unprocessed_event_ids", AsyncMock(return_value=ids)),
            patch(f"{MODULE}.drive_event", AsyncMock()) as drive_mock,
        ):
            count = await process_pending_events(_settings(), MagicMock(), batch_size=10)
            return count, drive_mock

    count, drive_mock = anyio.run(run)
    assert count == 2
    assert drive_mock.await_count == 2


def test_process_pending_events_no_ids_returns_zero():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_unprocessed_event_ids", AsyncMock(return_value=[])),
        ):
            return await process_pending_events(_settings(), MagicMock(), batch_size=10)

    assert anyio.run(run) == 0


# ---------------------------------------------------------------------------
# _render_status_reply
# ---------------------------------------------------------------------------


def test_render_status_reply_empty():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.list_grievances_for_contact", AsyncMock(return_value=[])),
        ):
            return await _render_status_reply(uuid4())

    assert anyio.run(run) == msg.STATUS_EMPTY


def test_render_status_reply_lists_grievances_with_missing_category():
    session = _session()
    grievance = SimpleNamespace(human_id="JS-1", category=None, status="submitted")

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.list_grievances_for_contact", AsyncMock(return_value=[grievance])),
        ):
            return await _render_status_reply(uuid4())

    body = anyio.run(run)
    assert "JS-1" in body
    assert "uncategorised" in body


# ---------------------------------------------------------------------------
# _send_standalone_reply
# ---------------------------------------------------------------------------


def test_send_standalone_reply_sends_when_row_created():
    contact_session = _session()
    contact_session.commit = AsyncMock()
    row = SimpleNamespace(id=uuid4())
    send_session = _session()

    async def run():
        with (
            patch(
                f"{MODULE}.AsyncSessionLocal",
                _multi_session_factory([contact_session, send_session]),
            ),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=SimpleNamespace(id=uuid4()))),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_standalone_reply(
                _settings(),
                MagicMock(),
                wa_id="911234567890",
                body="hello",
                reply_kind="registered_final",
                idempotency_key="k1",
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_send_standalone_reply_skips_send_when_replay():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=SimpleNamespace(id=uuid4()))),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=None)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_standalone_reply(
                _settings(),
                MagicMock(),
                wa_id="911234567890",
                body="hello",
                reply_kind="registered_final",
                idempotency_key="k1",
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_inbound
# ---------------------------------------------------------------------------


def _contact(cid=None):
    return SimpleNamespace(id=cid or uuid4())


def test_handle_inbound_replay_short_circuits():
    session = _session()
    contact = _contact()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=False)),
        ):
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())

    anyio.run(run)
    session.commit.assert_awaited_once()


def test_handle_inbound_exception_rolls_back_and_reraises():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.upsert_contact", AsyncMock(side_effect=RuntimeError("db down"))),
        ):
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())

    try:
        anyio.run(run)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    session.rollback.assert_awaited_once()


def test_handle_inbound_geocodes_location_messages():
    session = _session()
    contact = _contact()
    geo_session = _session()
    reverse_geocode = AsyncMock(return_value="geo-result")

    async def run():
        with (
            patch(
                f"{MODULE}.AsyncSessionLocal",
                _multi_session_factory([geo_session, session]),
            ),
            patch(f"{MODULE}.reverse_geocode_cached", reverse_geocode),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=False)),
        ):
            incoming = _inbound(
                message_type="location",
                text_body=None,
                location_latitude=18.5,
                location_longitude=73.8,
            )
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), incoming)

    anyio.run(run)
    reverse_geocode.assert_awaited_once()


def _login_reply(decision_id="login_yes"):
    return _inbound(
        message_type="interactive",
        text_body=None,
        reply_id=f"{decision_id}:challenge-1:verifier-1",
        context_message_id="wamid.prompt",
    )


def test_handle_inbound_login_approval_approved_sends_reply():
    session = _session()
    contact = _contact()
    send_session = _session()
    approval = SimpleNamespace()
    row = SimpleNamespace(id=uuid4())

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=True)),
            patch(
                f"{MODULE}.parse_login_approval_id",
                MagicMock(return_value=("login_yes", "challenge-1", "verifier-1")),
            ),
            patch(f"{MODULE}.decide_login_approval", AsyncMock(return_value=approval)),
            patch(f"{MODULE}.annotate_consumption", AsyncMock()),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _login_reply())
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_handle_inbound_login_approval_invalid_challenge():
    session = _session()
    contact = _contact()
    send_session = _session()
    row = SimpleNamespace(id=uuid4())

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=True)),
            patch(
                f"{MODULE}.parse_login_approval_id",
                MagicMock(return_value=("login_no", "challenge-1", "verifier-1")),
            ),
            patch(f"{MODULE}.decide_login_approval", AsyncMock(return_value=None)),
            patch(f"{MODULE}.annotate_consumption", AsyncMock()),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)) as store_mock,
            patch(f"{MODULE}.send_pending", AsyncMock()),
        ):
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _login_reply("login_no"))
            return store_mock

    store_mock = anyio.run(run)
    body = store_mock.await_args.kwargs["text_body"]
    assert "invalid" in body.lower()


def test_handle_inbound_verification_code_short_circuits():
    session = _session()
    contact = _contact()
    send_session = _session()
    row = SimpleNamespace(id=uuid4())

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.parse_login_approval_id", MagicMock(return_value=None)),
            patch(f"{MODULE}.is_verification_code", MagicMock(return_value=True)),
            patch(f"{MODULE}.verify_code_from_whatsapp", AsyncMock(return_value="Code verified.")),
            patch(f"{MODULE}.annotate_consumption", AsyncMock()),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            incoming = _inbound(text_body="JS-AB12CD")
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), incoming)
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_handle_inbound_status_query_with_no_conversation():
    session = _session()
    contact = _contact()
    send_session = _session()
    status_session = _session()
    row = SimpleNamespace(id=uuid4())

    async def run():
        with (
            patch(
                f"{MODULE}.AsyncSessionLocal",
                _multi_session_factory([session, status_session, send_session]),
            ),
            patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.parse_login_approval_id", MagicMock(return_value=None)),
            patch(f"{MODULE}.is_verification_code", MagicMock(return_value=False)),
            patch(f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=None)),
            patch(f"{MODULE}.is_status_query", MagicMock(return_value=True)),
            patch(f"{MODULE}.list_grievances_for_contact", AsyncMock(return_value=[])),
            patch(f"{MODULE}.annotate_consumption", AsyncMock()),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            incoming = _inbound(text_body="status")
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), incoming)
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def _fsm_result(**overrides):
    base = dict(
        state="awaiting_issue",
        context={"draft": {}},
        intents=[],
        action=None,
        close=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_DEFAULT_ROW = object()


def _enter_fsm_common(stack, conversation, advance_result, row=_DEFAULT_ROW):
    """Enter the patches shared by every FSM-path _handle_inbound test onto
    ``stack`` (a contextlib.ExitStack). Python's parenthesized ``with`` block
    does not support unpacking a list of context managers, hence ExitStack."""
    if row is _DEFAULT_ROW:
        row = SimpleNamespace(id=uuid4())
    stack.enter_context(patch(f"{MODULE}.upsert_contact", AsyncMock(return_value=_contact())))
    stack.enter_context(patch(f"{MODULE}.claim_inbound", AsyncMock(return_value=True)))
    stack.enter_context(patch(f"{MODULE}.parse_login_approval_id", MagicMock(return_value=None)))
    stack.enter_context(patch(f"{MODULE}.is_verification_code", MagicMock(return_value=False)))
    stack.enter_context(
        patch(f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=conversation))
    )
    stack.enter_context(patch(f"{MODULE}.advance", MagicMock(return_value=advance_result)))

    async def _upsert(*args, **kwargs):
        # Mirror the real repository: the returned conversation row carries the
        # FSM's new context (processing.py reads conversation.context afterwards).
        conversation.context = advance_result.context
        return conversation

    stack.enter_context(
        patch(f"{MODULE}.upsert_conversation_state", AsyncMock(side_effect=_upsert))
    )
    stack.enter_context(patch(f"{MODULE}.annotate_consumption", AsyncMock()))
    stack.enter_context(patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)))


def test_handle_inbound_fsm_no_action_no_intents_no_followup():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="awaiting_issue", context={}, active=True)
    result = _fsm_result(intents=[])

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result)
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())

    anyio.run(run)
    session.commit.assert_awaited_once()


def test_handle_inbound_fsm_sends_intents_and_closes():
    session = _session()
    send_session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="done", context={}, active=True)
    intent = SimpleNamespace(
        reply_kind="ask_issue", message_type="text", text_body="ok", payload={}
    )
    result = _fsm_result(intents=[intent], close=True)

    async def run():
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])
                )
            )
            _enter_fsm_common(stack, conversation, result)
            send_mock = stack.enter_context(patch(f"{MODULE}.send_pending", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()
    assert conversation.active is False


def test_handle_inbound_fsm_start_pipeline_action_triggers_followup():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing", context={}, active=True)
    result = _fsm_result(
        action="start_pipeline",
        context={"draft": {"grievance_id": "g-1"}},
        intents=[],
    )

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result)
            stack.enter_context(
                patch(f"{MODULE}.get_user_by_contact_id", AsyncMock(return_value=None))
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.create_draft_grievance",
                    AsyncMock(return_value=(SimpleNamespace(id="g-1"), True)),
                )
            )
            followup = stack.enter_context(patch(f"{MODULE}.run_pipeline_followup", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return followup

    followup = anyio.run(run)
    followup.assert_awaited_once()


def test_handle_inbound_fsm_recheck_photo_action_writes_media_and_followup():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing", context={}, active=True)
    result = _fsm_result(
        action="recheck_photo",
        context={"draft": {"grievance_id": "g-1"}, "photo": {"media_id": "m-9"}},
        intents=[],
    )

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result)
            set_fields = stack.enter_context(patch(f"{MODULE}.set_grievance_fields", AsyncMock()))
            followup = stack.enter_context(patch(f"{MODULE}.recheck_followup", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return set_fields, followup

    set_fields, followup = anyio.run(run)
    set_fields.assert_awaited_once()
    followup.assert_awaited_once()
    assert followup.await_args.kwargs["proceed_without_photo"] is False


def test_handle_inbound_fsm_finalize_action_triggers_finalize_followup():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="done", context={}, active=True)
    result = _fsm_result(
        action="finalize",
        context={"draft": {"grievance_id": "g-1"}},
        intents=[],
        close=True,
    )

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result)
            followup = stack.enter_context(patch(f"{MODULE}.finalize_followup", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return followup

    followup = anyio.run(run)
    followup.assert_awaited_once()


def test_handle_inbound_fsm_cancel_action_triggers_cancel_followup():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="cancelled", context={}, active=True)
    result = _fsm_result(
        action="cancel",
        context={"draft": {"grievance_id": "g-1"}},
        intents=[],
        close=True,
    )

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result)
            followup = stack.enter_context(patch(f"{MODULE}.cancel_followup", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return followup

    followup = anyio.run(run)
    followup.assert_awaited_once()


def test_handle_inbound_fsm_store_outgoing_returns_none_no_send():
    session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="awaiting_issue", context={}, active=True)
    intent = SimpleNamespace(
        reply_kind="ask_issue", message_type="text", text_body="ok", payload={}
    )
    result = _fsm_result(intents=[intent])

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)))
            _enter_fsm_common(stack, conversation, result, row=None)
            send_mock = stack.enter_context(patch(f"{MODULE}.send_pending", AsyncMock()))
            await _handle_inbound(_settings(), MagicMock(), MagicMock(), _inbound())
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# run_pipeline_followup / recheck_followup
# ---------------------------------------------------------------------------


def test_run_pipeline_followup_success_sends_message():
    result = SimpleNamespace(status="ok")

    async def run():
        with (
            patch(f"{MODULE}.run_pipeline", AsyncMock(return_value=result)),
            patch(f"{MODULE}._send_pipeline_followup_message", AsyncMock()) as send_mock,
        ):
            await run_pipeline_followup(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_run_pipeline_followup_exception_logged_and_returns():
    async def run():
        with (
            patch(f"{MODULE}.run_pipeline", AsyncMock(side_effect=RuntimeError("boom"))),
            patch(f"{MODULE}._send_pipeline_followup_message", AsyncMock()) as send_mock,
        ):
            await run_pipeline_followup(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


def test_recheck_followup_success_sends_message():
    result = SimpleNamespace(status="ok")

    async def run():
        with (
            patch(f"{MODULE}.recheck_image", AsyncMock(return_value=result)),
            patch(f"{MODULE}._send_pipeline_followup_message", AsyncMock()) as send_mock,
        ):
            await recheck_followup(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                proceed_without_photo=False,
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_recheck_followup_exception_logged_and_returns():
    async def run():
        with (
            patch(f"{MODULE}.recheck_image", AsyncMock(side_effect=RuntimeError("boom"))),
            patch(f"{MODULE}._send_pipeline_followup_message", AsyncMock()) as send_mock,
        ):
            await recheck_followup(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                proceed_without_photo=True,
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _send_pipeline_followup_message
# ---------------------------------------------------------------------------


def test_send_pipeline_followup_message_no_conversation_warns_and_returns():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=None)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_pipeline_followup_message(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                result=SimpleNamespace(status="ok"),
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


def test_send_pipeline_followup_message_photo_mismatch():
    session = _session()
    send_session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing")
    row = SimpleNamespace(id=uuid4())

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(
                f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=conversation)
            ),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_pipeline_followup_message(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                result=SimpleNamespace(status="photo_mismatch"),
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_send_pipeline_followup_message_confirmation_with_pdf_upload_ok():
    session = _session()
    send_session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing")
    row = SimpleNamespace(id=uuid4())
    grievance = SimpleNamespace(pdf_path="pdfs/g.pdf", human_id="JS-1")
    fake_path = MagicMock()
    fake_path.read_bytes.return_value = b"%PDF-"

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(
                f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=conversation)
            ),
            patch(f"{MODULE}.get_grievance", AsyncMock(return_value=grievance)),
            patch(f"{MODULE}.render_confirmation_summary", MagicMock(return_value="summary")),
            patch(f"{MODULE}.artifact_path", MagicMock(return_value=fake_path)),
            patch(f"{MODULE}.upload_whatsapp_media", AsyncMock(return_value="media-1")),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_pipeline_followup_message(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                result=SimpleNamespace(status="ok"),
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_send_pipeline_followup_message_pdf_upload_failure_still_sends():
    session = _session()
    send_session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing")
    row = SimpleNamespace(id=uuid4())
    grievance = SimpleNamespace(pdf_path="pdfs/g.pdf", human_id="JS-1")
    fake_path = MagicMock()
    fake_path.read_bytes.return_value = b"%PDF-"

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(
                f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=conversation)
            ),
            patch(f"{MODULE}.get_grievance", AsyncMock(return_value=grievance)),
            patch(f"{MODULE}.render_confirmation_summary", MagicMock(return_value="summary")),
            patch(f"{MODULE}.artifact_path", MagicMock(return_value=fake_path)),
            patch(f"{MODULE}.upload_whatsapp_media", AsyncMock(side_effect=RuntimeError("no net"))),
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()) as send_mock,
        ):
            await _send_pipeline_followup_message(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                result=SimpleNamespace(status="ok"),
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()


def test_send_pipeline_followup_message_no_pdf_path_skips_upload():
    session = _session()
    send_session = _session()
    conversation = SimpleNamespace(id=uuid4(), state="processing")
    row = SimpleNamespace(id=uuid4())
    grievance = SimpleNamespace(pdf_path=None, human_id="JS-1")

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _multi_session_factory([session, send_session])),
            patch(
                f"{MODULE}.lock_contact_and_get_conversation", AsyncMock(return_value=conversation)
            ),
            patch(f"{MODULE}.get_grievance", AsyncMock(return_value=grievance)),
            patch(f"{MODULE}.render_confirmation_summary", MagicMock(return_value="summary")),
            patch(f"{MODULE}.upload_whatsapp_media", AsyncMock()) as upload_mock,
            patch(f"{MODULE}.store_outgoing_pending", AsyncMock(return_value=row)),
            patch(f"{MODULE}.send_pending", AsyncMock()),
        ):
            await _send_pipeline_followup_message(
                _settings(),
                MagicMock(),
                MagicMock(),
                contact_id=uuid4(),
                wa_id="w",
                grievance_id="g",
                result=SimpleNamespace(status="ok"),
            )
            return upload_mock

    upload_mock = anyio.run(run)
    upload_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# finalize_followup / cancel_followup
# ---------------------------------------------------------------------------


def test_finalize_followup_success_sends_registered_message():
    outcome = SimpleNamespace(human_id="JS-1", status="ok", report_count=None)

    async def run():
        with (
            patch(f"{MODULE}.finalize_grievance", AsyncMock(return_value=outcome)),
            patch(f"{MODULE}._send_standalone_reply", AsyncMock()) as send_mock,
        ):
            await finalize_followup(
                _settings(), MagicMock(), MagicMock(), wa_id="w", grievance_id="g"
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_awaited_once()
    body = send_mock.await_args.kwargs["body"]
    assert "JS-1" in body


def test_finalize_followup_duplicate_appends_note():
    outcome = SimpleNamespace(human_id="JS-1", status="duplicate", report_count=3)

    async def run():
        with (
            patch(f"{MODULE}.finalize_grievance", AsyncMock(return_value=outcome)),
            patch(f"{MODULE}._send_standalone_reply", AsyncMock()) as send_mock,
        ):
            await finalize_followup(
                _settings(), MagicMock(), MagicMock(), wa_id="w", grievance_id="g"
            )
            return send_mock

    send_mock = anyio.run(run)
    body = send_mock.await_args.kwargs["body"]
    assert "3" in body


def test_finalize_followup_exception_logged_and_returns():
    async def run():
        with (
            patch(f"{MODULE}.finalize_grievance", AsyncMock(side_effect=RuntimeError("boom"))),
            patch(f"{MODULE}._send_standalone_reply", AsyncMock()) as send_mock,
        ):
            await finalize_followup(
                _settings(), MagicMock(), MagicMock(), wa_id="w", grievance_id="g"
            )
            return send_mock

    send_mock = anyio.run(run)
    send_mock.assert_not_awaited()


def test_cancel_followup_cancels_and_sends():
    async def run():
        with (
            patch(f"{MODULE}.cancel_grievance", AsyncMock()) as cancel_mock,
            patch(f"{MODULE}._send_standalone_reply", AsyncMock()) as send_mock,
        ):
            await cancel_followup(_settings(), MagicMock(), wa_id="w", grievance_id="g")
            return cancel_mock, send_mock

    cancel_mock, send_mock = anyio.run(run)
    cancel_mock.assert_awaited_once()
    send_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# sweep_stuck_processing
# ---------------------------------------------------------------------------


def test_sweep_stuck_processing_no_grievances_returns_zero():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_stuck_processing", AsyncMock(return_value=[])),
        ):
            return await sweep_stuck_processing(_settings(), MagicMock(), limit=10)

    assert anyio.run(run) == 0


def test_sweep_stuck_processing_skips_missing_grievance_and_contact():
    session = _session()

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_stuck_processing", AsyncMock(return_value=["g-1", "g-2"])),
            patch(
                f"{MODULE}.get_grievance",
                AsyncMock(
                    side_effect=[
                        None,
                        SimpleNamespace(contact_id=uuid4()),
                    ]
                ),
            ),
            patch(f"{MODULE}.get_contact", AsyncMock(return_value=None)),
        ):
            return await sweep_stuck_processing(_settings(), MagicMock(), limit=10)

    assert anyio.run(run) == 0


def test_sweep_stuck_processing_recovers_and_logs_followup_failures():
    session = _session()
    grievance = SimpleNamespace(contact_id=uuid4())
    contact = SimpleNamespace(wa_id="911234567890")

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_stuck_processing", AsyncMock(return_value=["g-1"])),
            patch(f"{MODULE}.get_grievance", AsyncMock(return_value=grievance)),
            patch(f"{MODULE}.get_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.WhatsAppCloudClient", MagicMock()),
            patch(f"{MODULE}.run_pipeline_followup", AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            return await sweep_stuck_processing(_settings(), MagicMock(), limit=10)

    assert anyio.run(run) == 1


def test_sweep_stuck_processing_happy_path():
    session = _session()
    grievance = SimpleNamespace(contact_id=uuid4())
    contact = SimpleNamespace(wa_id="911234567890")

    async def run():
        with (
            patch(f"{MODULE}.AsyncSessionLocal", _session_factory(session)),
            patch(f"{MODULE}.fetch_stuck_processing", AsyncMock(return_value=["g-1"])),
            patch(f"{MODULE}.get_grievance", AsyncMock(return_value=grievance)),
            patch(f"{MODULE}.get_contact", AsyncMock(return_value=contact)),
            patch(f"{MODULE}.WhatsAppCloudClient", MagicMock()),
            patch(f"{MODULE}.run_pipeline_followup", AsyncMock()) as followup,
        ):
            count = await sweep_stuck_processing(_settings(), MagicMock(), limit=10)
            return count, followup

    count, followup = anyio.run(run)
    assert count == 1
    followup.assert_awaited_once()
