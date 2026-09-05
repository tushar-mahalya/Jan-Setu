"""Unit tests for jan_setu.whatsapp.dispatch: outbound reply claim/send/record.

Follows the anyio.run(...) idiom used in tests/test_webhook.py and
tests/test_conversation.py (there is no pytest-asyncio plugin configured, so
``async def test_...`` would silently never run).
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio
import httpx

from jan_setu.config import Settings
from jan_setu.db import utc_now
from jan_setu.whatsapp.client import WhatsAppClientUnavailable
from jan_setu.whatsapp.dispatch import (
    _provider_message_id,
    send_pending,
    sweep_pending_outbound,
)

MODULE = "jan_setu.whatsapp.dispatch"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _result(value):
    """A fake sqlalchemy Result whose scalar_one_or_none() returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _message(**overrides):
    message = MagicMock()
    message.id = overrides.pop("id", uuid4())
    message.attempt_count = overrides.pop("attempt_count", 1)
    message.reply_kind = overrides.pop("reply_kind", "ask_issue")
    message.conversation_id = overrides.pop("conversation_id", uuid4())
    message.raw_payload = overrides.pop("raw_payload", {"type": "text"})
    for key, value in overrides.items():
        setattr(message, key, value)
    return message


def _client(send_result=None, send_exc=None):
    client = MagicMock()
    if send_exc is not None:
        client.send_raw = AsyncMock(side_effect=send_exc)
    else:
        client.send_raw = AsyncMock(return_value=send_result or {"messages": [{"id": "wamid.out"}]})
    return client


# ---------------------------------------------------------------------------
# _provider_message_id
# ---------------------------------------------------------------------------


def test_provider_message_id_extracts_id():
    assert _provider_message_id({"messages": [{"id": "wamid.1"}]}) == "wamid.1"


def test_provider_message_id_missing_messages_key():
    assert _provider_message_id({}) is None


def test_provider_message_id_non_dict_response():
    assert _provider_message_id("not-a-dict") is None


# ---------------------------------------------------------------------------
# send_pending
# ---------------------------------------------------------------------------


def test_send_pending_returns_skipped_when_claim_fails():
    session = MagicMock()
    session.commit = AsyncMock()

    async def run():
        with patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=False)):
            return await send_pending(session, _settings(), _client(), uuid4())

    status = anyio.run(run)
    assert status == "skipped"
    session.commit.assert_awaited_once()


def test_send_pending_returns_skipped_when_message_missing():
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)

    async def run():
        with patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)):
            return await send_pending(session, _settings(), _client(), uuid4())

    status = anyio.run(run)
    assert status == "skipped"


def test_send_pending_gives_up_after_max_attempts():
    message = _message(attempt_count=6)
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    mark_outbound = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), _client(), message.id)

    status = anyio.run(run)
    assert status == "failed"
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="failed")


def test_send_pending_at_max_attempts_boundary_still_sends():
    """attempt_count == MAX_SEND_ATTEMPTS (5) must NOT trip the give-up branch —
    only attempt_count > MAX_SEND_ATTEMPTS (6) should. This is the off-by-one
    line coverage alone can't catch, since both values execute the same lines."""
    message = _message(attempt_count=5, conversation_id=None)
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(side_effect=[_result(None)])
    mark_outbound = AsyncMock()
    client = _client()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), client, message.id)

    status = anyio.run(run)
    assert status == "sent"
    mark_outbound.assert_awaited_once_with(
        session, message_id=message.id, status="sent", meta_message_id="wamid.out"
    )


def test_send_pending_blocked_when_service_window_expired():
    message = _message()
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    expired = utc_now() - timedelta(hours=1)
    session.execute = AsyncMock(side_effect=[_result(expired)])
    mark_outbound = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), _client(), message.id)

    status = anyio.run(run)
    assert status == "blocked_24h"
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="blocked_24h")


def test_send_pending_login_approval_no_matching_challenge_fails():
    message = _message(reply_kind="login_approval")
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(
        side_effect=[
            _result(None),  # window_expiry: no conversation -> no gate
            _result(None),  # challenge lookup: none pending
        ]
    )
    mark_outbound = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), _client(), message.id)

    status = anyio.run(run)
    assert status == "failed"
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="failed")


def test_send_pending_login_approval_no_inbound_blocks_and_marks_fallback():
    message = _message(reply_kind="login_approval")
    challenge = MagicMock(contact_id=uuid4(), status="pending")
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(
        side_effect=[
            _result(None),  # window_expiry
            _result(challenge),  # challenge lookup
            _result(None),  # latest inbound: none
        ]
    )
    mark_outbound = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), _client(), message.id)

    status = anyio.run(run)
    assert status == "blocked_24h"
    assert challenge.status == "fallback"
    assert challenge.decided_at is not None
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="blocked_24h")


def test_send_pending_login_approval_stale_inbound_blocks():
    message = _message(reply_kind="login_approval")
    challenge = MagicMock(contact_id=uuid4(), status="pending")
    stale_inbound = utc_now() - timedelta(hours=48)
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(
        side_effect=[
            _result(None),
            _result(challenge),
            _result(stale_inbound),
        ]
    )
    mark_outbound = AsyncMock()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(
                session, _settings(service_window_hours=24), _client(), message.id
            )

    status = anyio.run(run)
    assert status == "blocked_24h"


def test_send_pending_login_approval_happy_path_sends():
    message = _message(reply_kind="login_approval")
    challenge = MagicMock(contact_id=uuid4(), status="pending")
    fresh_inbound = utc_now()
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(
        side_effect=[
            _result(None),
            _result(challenge),
            _result(fresh_inbound),
        ]
    )
    mark_outbound = AsyncMock()
    client = _client()

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(
                session, _settings(service_window_hours=24), client, message.id
            )

    status = anyio.run(run)
    assert status == "sent"
    mark_outbound.assert_awaited_once_with(
        session, message_id=message.id, status="sent", meta_message_id="wamid.out"
    )
    client.send_raw.assert_awaited_once_with(message.raw_payload)


def test_send_pending_http_error_marks_pending_for_retry():
    message = _message()
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(side_effect=[_result(None)])
    mark_outbound = AsyncMock()
    client = _client(send_exc=httpx.ConnectError("boom"))

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), client, message.id)

    status = anyio.run(run)
    assert status == "failed"
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="pending")


def test_send_pending_client_unavailable_marks_pending_for_retry():
    message = _message()
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(side_effect=[_result(None)])
    mark_outbound = AsyncMock()
    client = _client(send_exc=WhatsAppClientUnavailable("no token"))

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), client, message.id)

    status = anyio.run(run)
    assert status == "failed"


def test_send_pending_malformed_json_response_marks_pending_for_retry():
    """A 2xx Graph response with an unparseable body must degrade the same
    way as a transport error, not raise ValueError out of send_pending."""
    message = _message()
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(side_effect=[_result(None)])
    mark_outbound = AsyncMock()
    client = _client(send_exc=ValueError("Expecting value: line 1 column 1"))

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), client, message.id)

    status = anyio.run(run)
    assert status == "failed"
    mark_outbound.assert_awaited_once_with(session, message_id=message.id, status="pending")


def test_send_pending_happy_path_no_conversation_sends():
    message = _message(conversation_id=None)
    session = MagicMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=message)
    session.execute = AsyncMock(side_effect=[_result(None)])
    mark_outbound = AsyncMock()
    client = _client(send_result={"messages": [{"id": "wamid.z"}]})

    async def run():
        with (
            patch(f"{MODULE}.claim_outbound", AsyncMock(return_value=True)),
            patch(f"{MODULE}.mark_outbound", mark_outbound),
        ):
            return await send_pending(session, _settings(), client, message.id)

    status = anyio.run(run)
    assert status == "sent"
    mark_outbound.assert_awaited_once_with(
        session, message_id=message.id, status="sent", meta_message_id="wamid.z"
    )


# ---------------------------------------------------------------------------
# sweep_pending_outbound
# ---------------------------------------------------------------------------


def test_sweep_pending_outbound_sends_each_row():
    session = MagicMock()
    rows = [_message(id=uuid4()), _message(id=uuid4())]

    async def run():
        with (
            patch(f"{MODULE}.fetch_sweepable_outbound", AsyncMock(return_value=rows)),
            patch(f"{MODULE}.send_pending", AsyncMock(return_value="sent")) as send_mock,
        ):
            count = await sweep_pending_outbound(session, _settings(), _client(), limit=10)
            return count, send_mock

    count, send_mock = anyio.run(run)
    assert count == 2
    assert send_mock.await_count == 2


def test_sweep_pending_outbound_no_rows_returns_zero():
    session = MagicMock()

    async def run():
        with patch(f"{MODULE}.fetch_sweepable_outbound", AsyncMock(return_value=[])):
            return await sweep_pending_outbound(session, _settings(), _client(), limit=10)

    count = anyio.run(run)
    assert count == 0
