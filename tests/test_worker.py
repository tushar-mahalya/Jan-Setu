"""Tests for the background worker loop (src/jan_setu/worker.py).

``run_worker`` is an infinite ``while True`` polling loop, so every test here
breaks out after exactly one iteration by making the patched
``asyncio.sleep`` raise a private sentinel exception.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import anyio
import pytest

from jan_setu import worker


class _StopLoop(Exception):
    """Sentinel raised from the patched ``asyncio.sleep`` to end the while loop."""


class _AsyncCM:
    """A minimal async context manager wrapping a fixed value, standing in for
    ``AsyncSessionLocal()`` and ``httpx.AsyncClient()``."""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc_info):
        return False


def _run(coro_fn, *args, **kwargs):
    return anyio.run(lambda: coro_fn(*args, **kwargs))


def _job(stage="extract"):
    return SimpleNamespace(id=uuid4(), grievance_id=uuid4(), stage=stage)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    return session


def test_run_worker_processes_extract_job_and_completes(mock_session):
    job = _job(stage="extract")
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[job])),
        patch("jan_setu.worker.run_pipeline", AsyncMock()) as mock_run_pipeline,
        patch("jan_setu.worker.reextract_grievance", AsyncMock()) as mock_reextract,
        patch("jan_setu.worker.complete_pipeline_job", AsyncMock()) as mock_complete,
        patch("jan_setu.worker.fail_pipeline_job", AsyncMock()) as mock_fail,
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_run_pipeline.assert_awaited_once()
    mock_reextract.assert_not_called()
    mock_complete.assert_awaited_once()
    mock_fail.assert_not_called()


def test_run_worker_reextract_stage_calls_reextract_grievance(mock_session):
    job = _job(stage="reextract")
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[job])),
        patch("jan_setu.worker.run_pipeline", AsyncMock()) as mock_run_pipeline,
        patch("jan_setu.worker.reextract_grievance", AsyncMock()) as mock_reextract,
        patch("jan_setu.worker.complete_pipeline_job", AsyncMock()),
        patch("jan_setu.worker.fail_pipeline_job", AsyncMock()),
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_reextract.assert_awaited_once()
    mock_run_pipeline.assert_not_called()


def test_run_worker_job_failure_calls_fail_pipeline_job(mock_session):
    job = _job(stage="extract")
    boom = RuntimeError("pipeline exploded")
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[job])),
        patch("jan_setu.worker.run_pipeline", AsyncMock(side_effect=boom)),
        patch("jan_setu.worker.reextract_grievance", AsyncMock()),
        patch("jan_setu.worker.complete_pipeline_job", AsyncMock()) as mock_complete,
        patch("jan_setu.worker.fail_pipeline_job", AsyncMock()) as mock_fail,
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_fail.assert_awaited_once()
    assert mock_fail.await_args.kwargs["error"] is boom
    mock_complete.assert_not_called()


def test_run_worker_skips_complete_when_job_row_already_gone(mock_session):
    job = _job(stage="extract")
    mock_session.get = AsyncMock(return_value=None)
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[job])),
        patch("jan_setu.worker.run_pipeline", AsyncMock()),
        patch("jan_setu.worker.complete_pipeline_job", AsyncMock()) as mock_complete,
        patch("jan_setu.worker.fail_pipeline_job", AsyncMock()) as mock_fail,
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_complete.assert_not_called()
    mock_fail.assert_not_called()


def test_run_worker_skips_fail_when_job_row_already_gone_after_error(mock_session):
    job = _job(stage="extract")
    mock_session.get = AsyncMock(return_value=None)
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[job])),
        patch("jan_setu.worker.run_pipeline", AsyncMock(side_effect=RuntimeError("boom"))),
        patch("jan_setu.worker.complete_pipeline_job", AsyncMock()),
        patch("jan_setu.worker.fail_pipeline_job", AsyncMock()) as mock_fail,
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_fail.assert_not_called()


def test_run_worker_no_jobs_skips_job_loop_entirely(mock_session):
    with (
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch("jan_setu.worker.run_pipeline", AsyncMock()) as mock_run_pipeline,
        patch("jan_setu.worker.process_pending_events", AsyncMock()) as mock_events,
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_run_pipeline.assert_not_called()
    mock_events.assert_awaited_once()


def test_run_worker_event_sweep_failure_is_logged_not_raised(mock_session):
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch(
            "jan_setu.worker.process_pending_events",
            AsyncMock(side_effect=RuntimeError("sweep failed")),
        ),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()) as mock_outbound,
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        mock_get_settings.return_value = SimpleNamespace(
            worker_poll_seconds=0,
            worker_batch_size=10,
            request_timeout_seconds=1.0,
            auto_reply_enabled=False,
        )
        # Should not raise despite process_pending_events failing.
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    # auto_reply_enabled is explicitly False here, so the outbound sweep is
    # gated off (same gate as the pipeline sweeps below).
    mock_outbound.assert_not_called()


def test_run_worker_auto_reply_disabled_skips_outbound_and_pipeline_sweeps(mock_session):
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()) as mock_outbound,
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()) as mock_stuck,
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()) as mock_expired,
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()) as mock_dispatching,
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        mock_get_settings.return_value = SimpleNamespace(
            worker_poll_seconds=0,
            worker_batch_size=10,
            request_timeout_seconds=1.0,
            auto_reply_enabled=False,
        )
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_outbound.assert_not_called()
    mock_stuck.assert_not_called()
    mock_expired.assert_not_called()
    mock_dispatching.assert_not_called()


def test_run_worker_auto_reply_enabled_runs_sweeps(mock_session):
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()) as mock_outbound,
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()) as mock_stuck,
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()) as mock_expired,
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()) as mock_dispatching,
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        mock_get_settings.return_value = SimpleNamespace(
            worker_poll_seconds=0,
            worker_batch_size=10,
            request_timeout_seconds=1.0,
            auto_reply_enabled=True,
        )
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_outbound.assert_awaited_once()
    mock_stuck.assert_awaited_once()
    mock_expired.assert_awaited_once()
    mock_dispatching.assert_awaited_once()


def test_run_worker_outbound_sweep_failure_rolls_back_session(mock_session):
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch(
            "jan_setu.worker.sweep_pending_outbound",
            AsyncMock(side_effect=RuntimeError("outbound failed")),
        ),
        patch("jan_setu.worker.sweep_stuck_processing", AsyncMock()),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        mock_get_settings.return_value = SimpleNamespace(
            worker_poll_seconds=0,
            worker_batch_size=10,
            request_timeout_seconds=1.0,
            auto_reply_enabled=True,
        )
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)

    mock_session.rollback.assert_awaited_once()


def test_run_worker_pipeline_sweep_failure_is_logged_not_raised(mock_session):
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.claim_pipeline_jobs", AsyncMock(return_value=[])),
        patch("jan_setu.worker.process_pending_events", AsyncMock()),
        patch("jan_setu.worker.sweep_pending_outbound", AsyncMock()),
        patch(
            "jan_setu.worker.sweep_stuck_processing",
            AsyncMock(side_effect=RuntimeError("stuck sweep failed")),
        ),
        patch("jan_setu.worker.sweep_expired_windows", AsyncMock()),
        patch("jan_setu.worker.sweep_stuck_dispatching", AsyncMock()),
        patch("jan_setu.worker.AsyncSessionLocal", side_effect=lambda: _AsyncCM(mock_session)),
        patch("jan_setu.worker.httpx.AsyncClient", return_value=_AsyncCM(AsyncMock())),
        patch("jan_setu.worker.asyncio.sleep", AsyncMock(side_effect=_StopLoop)),
    ):
        mock_get_settings.return_value = SimpleNamespace(
            worker_poll_seconds=0,
            worker_batch_size=10,
            request_timeout_seconds=1.0,
            auto_reply_enabled=True,
        )
        # Should not raise despite the sweep failing -- logged and swallowed.
        with pytest.raises(_StopLoop):
            _run(worker.run_worker)


def test_run_stops_cleanly_on_keyboard_interrupt():
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.configure_logging") as mock_configure_logging,
        patch("jan_setu.worker.asyncio.run", side_effect=KeyboardInterrupt) as mock_asyncio_run,
    ):
        mock_get_settings.return_value = SimpleNamespace(log_level="INFO", log_format="text")
        worker.run()

    mock_configure_logging.assert_called_once()
    mock_asyncio_run.assert_called_once()


def test_run_propagates_non_keyboard_interrupt_errors():
    with (
        patch("jan_setu.worker.get_settings") as mock_get_settings,
        patch("jan_setu.worker.configure_logging"),
        patch("jan_setu.worker.asyncio.run", side_effect=RuntimeError("fatal")),
    ):
        mock_get_settings.return_value = SimpleNamespace(log_level="INFO", log_format="text")
        with pytest.raises(RuntimeError):
            worker.run()
