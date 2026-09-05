"""Unit tests for jan_setu.pipeline.core — the channel-agnostic grievance
pipeline (transcribe -> classify -> geocode -> image-check -> pdf -> dedup |
dispatch).

Every stage opens its own `AsyncSessionLocal()`, so tests replace that name
(module-level, patched via monkeypatch so it never leaks to other modules
that import the same symbol) with a fake async-context-manager session, and
replace the repository/collaborator functions core.py calls by name with
AsyncMocks. PDF generation is stubbed out via `core._build_and_store_pdf`
so these tests exercise pipeline branching, not reportlab.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from jan_setu.config import Settings
from jan_setu.pipeline.taxonomy import DEMO_JURISDICTION_ID
from jan_setu.pipeline import core
from jan_setu.pipeline.classify import StructuredExtraction
from jan_setu.pipeline.dedup import DuplicateMatch
from jan_setu.pipeline.dispatchers import DispatchError
from jan_setu.pipeline.stt import TranscriptionResult

pytestmark = pytest.mark.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    def __init__(self, contact=None):
        self.added = []
        self.committed = False
        self.flushed = False
        self._contact = contact

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        self.flushed = True

    async def get(self, _model, _id):
        return self._contact

    async def execute(self, _statement):
        # No jurisdiction_routes rows: routing falls back to the bundled
        # profile, which is the behaviour these tests were written against.
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


class FakeSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *_exc):
        return False


def _patch_session(monkeypatch, contact=None):
    session = FakeAsyncSession(contact=contact)
    monkeypatch.setattr(core, "AsyncSessionLocal", lambda: FakeSessionCM(session))
    return session


def _settings(**overrides):
    return Settings(_env_file=None, **overrides)


def _grievance(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        human_id="JS-20260812-00001",
        contact_id=uuid.uuid4(),
        jurisdiction_id=DEMO_JURISDICTION_ID,
        issue_messages=[],
        issue_text="Pothole outside my house",
        location_address="MG Road",
        location_latitude=None,
        location_longitude=None,
        photo_media_id=None,
        photo_path=None,
        category="pothole_surface_damage",
        category_id="pothole_surface_damage",
        department_key="public_works",
        priority="normal",
        term="long_term",
        confidence=0.8,
        image_match_status="none",
        flags=[],
        status="awaiting_confirmation",
        disposition="proceed",
        review_status="citizen_review",
        created_at=datetime.now(timezone.utc),
        pdf_path=None,
        dispatch_attempts=0,
        report_count=1,
        duplicate_of_id=None,
        routing_snapshot={},
        structured_facts={},
        state_version=0,
        asset_scope="unknown",
        safety_level="none",
        window_expires_at=None,
        source_language=None,
        transcript_metadata=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _extraction(**overrides):
    defaults = dict(
        summary="Pothole reported",
        category_id="pothole_surface_damage",
        alternatives=(),
        confidence=0.85,
        asset_scope="public",
        owner_hint="ulb",
        safety="none",
        requested_action=None,
        landmark=None,
        incident_time=None,
        missing_facts=(),
        clarification_question=None,
        evidence=(),
        image_observations=(),
        contradictions=(),
        multiple_issues=False,
        degraded=False,
        degradation_reason=None,
        actual_model="model-x",
        actual_provider="groq",
        latency_ms=100,
        requested_models=("groq:model-x",),
        raw={},
    )
    defaults.update(overrides)
    return StructuredExtraction(**defaults)


def _patch_grievance_flow(monkeypatch, grievance, *, extraction=None):
    """Common wiring for run_pipeline / recheck_image tests."""
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock(return_value=grievance)
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    add_event = AsyncMock()
    monkeypatch.setattr(core, "add_grievance_event", add_event)
    build_pdf = AsyncMock()
    monkeypatch.setattr(core, "_build_and_store_pdf", build_pdf)
    if extraction is not None:
        monkeypatch.setattr(core, "extract_issue", AsyncMock(return_value=extraction))
    return set_fields, add_event, build_pdf


# ---------------------------------------------------------------------------
# render_confirmation_summary
# ---------------------------------------------------------------------------


def test_render_confirmation_summary_uses_populated_fields():
    grievance = _grievance(
        category="pothole_surface_damage",
        priority="priority",
        location_address="Near City Hall",
        issue_text="Large pothole causing accidents",
    )
    summary = core.render_confirmation_summary(grievance)
    assert "Near City Hall" in summary
    assert "priority" in summary
    assert "Large pothole causing accidents" in summary


def test_render_confirmation_summary_falls_back_when_fields_missing():
    grievance = _grievance(category=None, priority=None, location_address=None, issue_text=None)
    summary = core.render_confirmation_summary(grievance)
    assert "unresolved" in summary
    assert "normal" in summary
    assert "(no description)" in summary


# ---------------------------------------------------------------------------
# _contact_phone
# ---------------------------------------------------------------------------


def test_contact_phone_returns_wa_id_when_contact_found():
    contact = SimpleNamespace(wa_id="919876543210")
    session = FakeAsyncSession(contact=contact)
    phone = asyncio.run(core._contact_phone(session, uuid.uuid4()))
    assert phone == "919876543210"


def test_contact_phone_returns_empty_string_when_contact_missing():
    session = FakeAsyncSession(contact=None)
    phone = asyncio.run(core._contact_phone(session, uuid.uuid4()))
    assert phone == ""


# ---------------------------------------------------------------------------
# _fetch_photo
# ---------------------------------------------------------------------------


def test_fetch_photo_reads_local_upload_successfully(tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"fake-jpeg-bytes")
    settings = _settings()
    data, mime = asyncio.run(
        core._fetch_photo(settings, object(), photo_media_id=None, photo_path=str(photo))
    )
    assert data == b"fake-jpeg-bytes"
    assert mime == "image/jpeg"


def test_fetch_photo_returns_none_on_local_read_failure(tmp_path):
    missing = tmp_path / "missing.jpg"
    settings = _settings()
    data, mime = asyncio.run(
        core._fetch_photo(settings, object(), photo_media_id=None, photo_path=str(missing))
    )
    assert data is None
    assert mime is None


def test_fetch_photo_resolves_a_path_stored_under_a_different_upload_root(tmp_path):
    """The host API stores "data/uploads/<id>/<file>" relative to its own root;
    the worker container runs with upload_dir="/data/uploads". Reading the stored
    string directly resolves to nothing there, which silently dropped every photo
    from extraction and from the PDF. The path must be re-rooted."""
    worker_root = tmp_path / "container" / "data" / "uploads"
    (worker_root / "abc123").mkdir(parents=True)
    (worker_root / "abc123" / "evidence.jpg").write_bytes(b"real-photo-bytes")

    settings = _settings(upload_dir=str(worker_root))
    stored_by_the_other_process = "data/uploads/abc123/evidence.jpg"

    data, mime = asyncio.run(
        core._fetch_photo(
            settings, object(), photo_media_id=None, photo_path=stored_by_the_other_process
        )
    )
    assert data == b"real-photo-bytes"
    assert mime == "image/jpeg"


def test_fetch_photo_returns_none_when_neither_path_nor_media_id():
    settings = _settings()
    data, mime = asyncio.run(
        core._fetch_photo(settings, object(), photo_media_id=None, photo_path=None)
    )
    assert data is None
    assert mime is None


def test_fetch_photo_downloads_whatsapp_media_successfully(monkeypatch):
    async def fake_download(*_args):
        return b"media-bytes", "image/png"

    monkeypatch.setattr(core, "download_whatsapp_media", fake_download)
    settings = _settings()
    data, mime = asyncio.run(
        core._fetch_photo(settings, object(), photo_media_id="media-1", photo_path=None)
    )
    assert data == b"media-bytes"
    assert mime == "image/png"


def test_fetch_photo_returns_none_on_whatsapp_download_failure(monkeypatch):
    async def fake_download(*_args):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(core, "download_whatsapp_media", fake_download)
    settings = _settings()
    data, mime = asyncio.run(
        core._fetch_photo(settings, object(), photo_media_id="media-1", photo_path=None)
    )
    assert data is None
    assert mime is None


# ---------------------------------------------------------------------------
# _combine_issue_text
# ---------------------------------------------------------------------------


def test_combine_issue_text_reads_local_audio_upload(monkeypatch, tmp_path):
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"audio-bytes")
    monkeypatch.setattr(core, "artifact_path", lambda _settings, _path: audio_file)

    async def fake_transcribe(*_args, **_kwargs):
        return TranscriptionResult(ok=True, text="water leaking", detected_language="en-IN")

    monkeypatch.setattr(core, "transcribe_clip", fake_transcribe)
    text, language, flags, transcripts = asyncio.run(
        core._combine_issue_text(
            object(),
            _settings(),
            object(),
            [{"type": "audio", "local_path": "grievance/voice.ogg", "mime_type": "audio/ogg"}],
        )
    )
    assert text == "water leaking"
    assert language == "en-IN"
    assert flags == []
    assert transcripts[0]["text"] == "water leaking"


def test_combine_issue_text_flags_local_audio_read_failure(monkeypatch):
    monkeypatch.setattr(
        core, "artifact_path", lambda _settings, path: __import__("pathlib").Path(path)
    )
    text, language, flags, transcripts = asyncio.run(
        core._combine_issue_text(
            object(),
            _settings(),
            object(),
            [{"type": "voice", "local_path": "does/not/exist.ogg"}],
        )
    )
    assert text == ""
    assert language is None
    assert flags == ["transcription_failed"]
    assert transcripts == []


def test_combine_issue_text_flags_whatsapp_download_failure(monkeypatch):
    async def fake_download(*_args):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(core, "download_whatsapp_media", fake_download)
    text, _language, flags, _transcripts = asyncio.run(
        core._combine_issue_text(
            object(),
            _settings(),
            object(),
            [{"type": "audio", "media_id": "media-1"}],
        )
    )
    assert text == ""
    assert flags == ["transcription_failed"]


def test_combine_issue_text_skips_audio_message_without_source(monkeypatch):
    transcribe_mock = AsyncMock()
    monkeypatch.setattr(core, "transcribe_clip", transcribe_mock)
    text, _language, flags, transcripts = asyncio.run(
        core._combine_issue_text(object(), _settings(), object(), [{"type": "audio"}])
    )
    assert text == ""
    assert flags == []
    assert transcripts == []
    transcribe_mock.assert_not_awaited()


def test_combine_issue_text_flags_failed_transcription_result(monkeypatch):
    async def fake_download(*_args):
        return b"bytes", "audio/ogg"

    async def fake_transcribe(*_args, **_kwargs):
        return TranscriptionResult(ok=False, text=None)

    monkeypatch.setattr(core, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(core, "transcribe_clip", fake_transcribe)
    text, _language, flags, transcripts = asyncio.run(
        core._combine_issue_text(
            object(), _settings(), object(), [{"type": "voice", "media_id": "m-1"}]
        )
    )
    assert text == ""
    assert flags == ["transcription_failed"]
    assert transcripts == []


def test_combine_issue_text_ignores_unrelated_and_empty_messages():
    text, _language, flags, transcripts = asyncio.run(
        core._combine_issue_text(
            object(),
            _settings(),
            object(),
            [
                {"type": "image", "media_id": "irrelevant"},
                {"type": "text", "text": ""},
                {"type": "text", "text": "Streetlight out"},
            ],
        )
    )
    assert text == "Streetlight out"
    assert flags == []
    assert transcripts == []


# ---------------------------------------------------------------------------
# _build_and_store_pdf
# ---------------------------------------------------------------------------


def test_build_and_store_pdf_saves_pdf_and_updates_grievance(monkeypatch):
    contact = SimpleNamespace(wa_id="919876543210")
    session = FakeAsyncSession(contact=contact)
    grievance = _grievance()
    monkeypatch.setattr(core, "build_grievance_pdf", lambda *_a, **_k: b"%PDF-fake")
    monkeypatch.setattr(core, "save_upload", lambda *_a, **_k: "data/uploads/x/summary.pdf")
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)

    asyncio.run(core._build_and_store_pdf(session, _settings(), grievance, b"photo"))

    set_fields.assert_awaited_once()
    _, kwargs = set_fields.call_args
    assert kwargs["pdf_path"] == "data/uploads/x/summary.pdf"


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


def test_run_pipeline_raises_when_grievance_missing(monkeypatch):
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=None))
    _patch_session(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(core.run_pipeline(uuid.uuid4(), _settings(), object()))


def test_run_pipeline_happy_path_no_photo_awaiting_confirmation(monkeypatch):
    grievance = _grievance(
        issue_messages=[{"type": "text", "text": "Pothole here"}],
        location_address="MG Road",
        photo_media_id=None,
        photo_path=None,
    )
    extraction = _extraction()
    set_fields, add_event, build_pdf = _patch_grievance_flow(
        monkeypatch, grievance, extraction=extraction
    )
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))

    result = asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    assert result.status == "awaiting_confirmation"
    assert result.image_match_status == "none"
    build_pdf.assert_awaited_once()
    add_event.assert_awaited_once()
    kwargs = set_fields.call_args.kwargs
    assert kwargs["status"] == "awaiting_confirmation"


def test_run_pipeline_geocodes_when_address_missing_but_lat_present(monkeypatch):
    grievance = _grievance(location_address=None, location_latitude=18.52, location_longitude=73.85)
    extraction = _extraction()
    _patch_grievance_flow(monkeypatch, grievance, extraction=extraction)
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))
    geocode_mock = AsyncMock(return_value=SimpleNamespace(display_address="Resolved Rd"))
    monkeypatch.setattr(core, "reverse_geocode_cached", geocode_mock)

    asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    geocode_mock.assert_awaited_once()


def test_run_pipeline_does_not_geocode_when_address_already_present(monkeypatch):
    grievance = _grievance(location_address="Already known", location_latitude=18.5)
    extraction = _extraction()
    _patch_grievance_flow(monkeypatch, grievance, extraction=extraction)
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))
    geocode_mock = AsyncMock()
    monkeypatch.setattr(core, "reverse_geocode_cached", geocode_mock)

    asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    geocode_mock.assert_not_awaited()


def test_run_pipeline_photo_mismatch_skips_pdf(monkeypatch):
    grievance = _grievance(photo_media_id="media-1")
    extraction = _extraction(contradictions=("photo doesn't show a pothole",))
    set_fields, add_event, build_pdf = _patch_grievance_flow(
        monkeypatch, grievance, extraction=extraction
    )
    _patch_session(monkeypatch)
    monkeypatch.setattr(
        core, "_fetch_photo", AsyncMock(return_value=(b"photo-bytes", "image/jpeg"))
    )

    result = asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    assert result.status == "photo_mismatch"
    assert result.image_match_status == "mismatched"
    build_pdf.assert_not_awaited()


def test_run_pipeline_photo_matches_builds_pdf(monkeypatch):
    grievance = _grievance(photo_media_id="media-1")
    extraction = _extraction(contradictions=())
    _set_fields, _add_event, build_pdf = _patch_grievance_flow(
        monkeypatch, grievance, extraction=extraction
    )
    _patch_session(monkeypatch)
    monkeypatch.setattr(
        core, "_fetch_photo", AsyncMock(return_value=(b"photo-bytes", "image/jpeg"))
    )

    result = asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    assert result.status == "awaiting_confirmation"
    assert result.image_match_status == "matched"
    build_pdf.assert_awaited_once()


def test_run_pipeline_flags_degraded_review_and_multiple_issues(monkeypatch):
    grievance = _grievance()
    extraction = _extraction(
        degraded=True,
        multiple_issues=True,
        category_id="insufficient_information",
        confidence=0.1,
    )
    set_fields, _add_event, _build_pdf = _patch_grievance_flow(
        monkeypatch, grievance, extraction=extraction
    )
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))

    result = asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    assert "classification_failed" in result.flags
    assert "multiple_issues" in result.flags
    assert "official_review_required" in result.flags
    kwargs = set_fields.call_args.kwargs
    assert kwargs["review_status"] == "pending_official"


def test_run_pipeline_routing_snapshot_when_no_route_for_category(monkeypatch):
    grievance = _grievance()
    extraction = _extraction(category_id="totally_unmapped_bogus_category_xyz")
    set_fields, _add_event, _build_pdf = _patch_grievance_flow(
        monkeypatch, grievance, extraction=extraction
    )
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))

    asyncio.run(core.run_pipeline(grievance.id, _settings(), object()))

    snapshot = set_fields.call_args.kwargs["routing_snapshot"]
    assert snapshot["dispatch_enabled"] is False
    assert snapshot["owning_agency"] is None


# ---------------------------------------------------------------------------
# recheck_image
# ---------------------------------------------------------------------------


def test_recheck_image_raises_when_grievance_missing(monkeypatch):
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=None))
    _patch_session(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(core.recheck_image(uuid.uuid4(), _settings(), object()))


def test_recheck_image_proceed_without_photo_marks_skipped(monkeypatch):
    grievance = _grievance()
    set_fields, add_event, build_pdf = _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)
    fetch_photo = AsyncMock()
    monkeypatch.setattr(core, "_fetch_photo", fetch_photo)

    result = asyncio.run(
        core.recheck_image(grievance.id, _settings(), object(), proceed_without_photo=True)
    )

    assert result.status == "awaiting_confirmation"
    assert result.image_match_status == "skipped"
    fetch_photo.assert_not_awaited()
    build_pdf.assert_awaited_once()


def test_recheck_image_photo_matches(monkeypatch):
    grievance = _grievance(photo_media_id="media-1")
    _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)
    monkeypatch.setattr(
        core, "_fetch_photo", AsyncMock(return_value=(b"photo-bytes", "image/jpeg"))
    )
    monkeypatch.setattr(
        core,
        "check_image_match",
        AsyncMock(return_value=SimpleNamespace(matches=True, degraded=False)),
    )

    result = asyncio.run(core.recheck_image(grievance.id, _settings(), object()))

    assert result.status == "awaiting_confirmation"
    assert result.image_match_status == "matched"


def test_recheck_image_photo_mismatched_skips_pdf(monkeypatch):
    grievance = _grievance(photo_media_id="media-1")
    _set_fields, _add_event, build_pdf = _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)
    monkeypatch.setattr(
        core, "_fetch_photo", AsyncMock(return_value=(b"photo-bytes", "image/jpeg"))
    )
    monkeypatch.setattr(
        core,
        "check_image_match",
        AsyncMock(return_value=SimpleNamespace(matches=False, degraded=False)),
    )

    result = asyncio.run(core.recheck_image(grievance.id, _settings(), object()))

    assert result.status == "photo_mismatch"
    assert result.image_match_status == "mismatched"
    build_pdf.assert_not_awaited()


def test_accept_photo_mismatch_keeps_photo_and_builds_pdf(monkeypatch):
    grievance = _grievance(
        status="photo_mismatch", image_match_status="mismatched", photo_media_id="media-1"
    )
    set_fields, add_event, build_pdf = _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)
    monkeypatch.setattr(
        core, "_fetch_photo", AsyncMock(return_value=(b"photo-bytes", "image/jpeg"))
    )

    asyncio.run(core.accept_photo_mismatch(grievance.id, _settings(), object()))

    kwargs = set_fields.call_args.kwargs
    assert kwargs["status"] == "awaiting_confirmation"
    assert "photo_mismatch_accepted" in kwargs["flags"]
    assert "image_match_status" not in kwargs  # mismatch stays on record
    assert build_pdf.await_args.args[-1] == b"photo-bytes"
    add_event.assert_awaited_once()


def test_accept_photo_mismatch_is_noop_in_other_status(monkeypatch):
    grievance = _grievance(status="awaiting_confirmation")
    set_fields, _add_event, build_pdf = _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)

    asyncio.run(core.accept_photo_mismatch(grievance.id, _settings(), object()))

    set_fields.assert_not_awaited()
    build_pdf.assert_not_awaited()


def test_recheck_image_no_photo_available_stays_skipped(monkeypatch):
    grievance = _grievance(photo_media_id=None, photo_path=None)
    _patch_grievance_flow(monkeypatch, grievance)
    _patch_session(monkeypatch)
    monkeypatch.setattr(core, "_fetch_photo", AsyncMock(return_value=(None, None)))

    result = asyncio.run(core.recheck_image(grievance.id, _settings(), object()))

    assert result.image_match_status == "skipped"
    assert result.status == "awaiting_confirmation"


# ---------------------------------------------------------------------------
# reextract_grievance
# ---------------------------------------------------------------------------


def test_reextract_grievance_returns_when_grievance_missing(monkeypatch):
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=None))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(uuid.uuid4(), _settings(), object()))

    set_fields.assert_not_awaited()


def test_reextract_grievance_returns_when_issue_text_missing(monkeypatch):
    grievance = _grievance(issue_text=None)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(grievance.id, _settings(), object()))

    set_fields.assert_not_awaited()


def test_reextract_grievance_returns_when_extraction_degraded(monkeypatch):
    grievance = _grievance()
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    monkeypatch.setattr(core, "extract_issue", AsyncMock(return_value=_extraction(degraded=True)))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(grievance.id, _settings(), object()))

    set_fields.assert_not_awaited()


def test_reextract_grievance_flags_dispute_when_model_disagrees_with_citizen(monkeypatch):
    grievance = _grievance(
        category_id="pothole_surface_damage",
        flags=[],
        structured_facts={"clarification_question": "Where?", "clarification_answer": "Main Rd"},
        asset_scope="public",
        location_address="Main Rd",
        state_version=2,
    )
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    monkeypatch.setattr(
        core,
        "extract_issue",
        AsyncMock(return_value=_extraction(category_id="open_or_damaged_manhole")),
    )
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    add_event = AsyncMock()
    monkeypatch.setattr(core, "add_grievance_event", add_event)
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(grievance.id, _settings(), object()))

    kwargs = set_fields.call_args.kwargs
    assert kwargs["category"] == "pothole_surface_damage"
    assert "category_dispute" in kwargs["flags"]
    assert kwargs["state_version"] == 3
    add_event.assert_awaited_once()


def test_reextract_grievance_adopts_model_category_for_fallback_categories(monkeypatch):
    grievance = _grievance(
        category_id="insufficient_information",
        flags=[],
        structured_facts={},
        asset_scope="unknown",
    )
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    extraction = _extraction(category_id="pothole_surface_damage", asset_scope="public")
    monkeypatch.setattr(core, "extract_issue", AsyncMock(return_value=extraction))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(grievance.id, _settings(), object()))

    kwargs = set_fields.call_args.kwargs
    assert kwargs["category"] == "pothole_surface_damage"
    assert "category_dispute" not in kwargs["flags"]
    assert kwargs["asset_scope"] == "public"


def test_reextract_grievance_without_citizen_category_uses_extraction(monkeypatch):
    grievance = _grievance(category_id=None, flags=[], structured_facts={"summary": "old"})
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    extraction = _extraction(category_id="pothole_surface_damage")
    monkeypatch.setattr(core, "extract_issue", AsyncMock(return_value=extraction))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    _patch_session(monkeypatch)

    asyncio.run(core.reextract_grievance(grievance.id, _settings(), object()))

    kwargs = set_fields.call_args.kwargs
    assert kwargs["category"] == "pothole_surface_damage"
    # existing summary is preserved, not overwritten by extraction's summary
    assert kwargs["structured_facts"]["summary"] == "old"


# ---------------------------------------------------------------------------
# finalize_grievance
# ---------------------------------------------------------------------------


def test_finalize_grievance_raises_when_missing(monkeypatch):
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=None))
    _patch_session(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(core.finalize_grievance(_settings(), object(), grievance_id=uuid.uuid4()))


def test_finalize_grievance_pending_official_registers(monkeypatch):
    grievance = _grievance(review_status="pending_official")
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.finalize_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "registered"
    assert set_fields.call_args.kwargs["status"] == "registered"


def test_finalize_grievance_redirect_disposition_registers_pending_official(monkeypatch):
    grievance = _grievance(review_status="citizen_review", disposition="redirect")
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.finalize_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "registered"
    assert set_fields.call_args.kwargs["review_status"] == "pending_official"


def test_finalize_grievance_priority_delegates_to_dispatch(monkeypatch):
    grievance = _grievance(
        review_status="citizen_review", disposition="proceed", priority="priority"
    )
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    monkeypatch.setattr(core, "set_grievance_fields", AsyncMock())
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    _patch_session(monkeypatch)
    sentinel = core.FinalizeOutcome(status="submitted", human_id=grievance.human_id)
    dispatch_mock = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(core, "dispatch_grievance", dispatch_mock)

    settings = _settings()
    http_client = object()
    outcome = asyncio.run(core.finalize_grievance(settings, http_client, grievance_id=grievance.id))

    assert outcome is sentinel
    dispatch_mock.assert_awaited_once_with(settings, http_client, grievance_id=grievance.id)


def test_finalize_grievance_marks_duplicate(monkeypatch):
    grievance = _grievance(
        review_status="citizen_review",
        disposition="proceed",
        priority="normal",
        location_latitude=18.5,
        location_longitude=73.8,
    )
    master = _grievance(human_id="JS-20260812-00000", report_count=2)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    monkeypatch.setattr(
        core,
        "find_duplicate",
        AsyncMock(return_value=DuplicateMatch(master=master, distance_m=42.0)),
    )
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.finalize_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "duplicate"
    assert outcome.duplicate_of_human_id == master.human_id
    assert outcome.report_count == 3


def test_finalize_grievance_no_duplicate_enters_pending_window(monkeypatch):
    grievance = _grievance(
        review_status="citizen_review",
        disposition="proceed",
        priority="normal",
        location_latitude=18.5,
        location_longitude=73.8,
    )
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    monkeypatch.setattr(core, "find_duplicate", AsyncMock(return_value=None))
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.finalize_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "pending_window"
    assert set_fields.call_args.kwargs["status"] == "pending_window"


# ---------------------------------------------------------------------------
# cancel_grievance
# ---------------------------------------------------------------------------


def test_cancel_grievance_sets_cancelled_status(monkeypatch):
    set_fields = AsyncMock()
    add_event = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", add_event)
    session = _patch_session(monkeypatch)

    asyncio.run(core.cancel_grievance(grievance_id=uuid.uuid4()))

    assert set_fields.call_args.kwargs["status"] == "cancelled"
    add_event.assert_awaited_once()
    assert session.committed is True


# ---------------------------------------------------------------------------
# dispatch_grievance
# ---------------------------------------------------------------------------


def test_dispatch_grievance_raises_when_missing(monkeypatch):
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=None))
    _patch_session(monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=uuid.uuid4()))


def test_dispatch_grievance_disabled_snapshot_registers_for_review(monkeypatch):
    grievance = _grievance(routing_snapshot={"dispatch_enabled": False})
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    dispatcher_factory = AsyncMock()
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher_factory)
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "registered"
    assert set_fields.call_args.kwargs["review_status"] == "pending_official"
    dispatcher_factory.assert_not_called()


def test_dispatch_grievance_empty_snapshot_proceeds_to_dispatch(monkeypatch):
    grievance = _grievance(routing_snapshot={}, pdf_path=None)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    dispatcher = SimpleNamespace(dispatch=AsyncMock(return_value="MUN-1"))
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher)
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "submitted"
    dispatcher.dispatch.assert_awaited_once()
    assert set_fields.call_args.kwargs["dispatch_ref"] == "MUN-1"


def test_dispatch_grievance_commits_dispatching_status_before_external_call(monkeypatch):
    """The 'dispatching' status must be durably committed BEFORE the dispatcher
    call, not just flushed — otherwise a crash mid-call leaves the grievance in
    its old status, invisible to sweep_stuck_dispatching, and the complaint is
    silently never retried (see dispatch_grievance's comment)."""
    grievance = _grievance(routing_snapshot={}, pdf_path=None)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    monkeypatch.setattr(core, "set_grievance_fields", AsyncMock())
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())

    calls: list[str] = []

    async def fake_dispatch(**_kwargs):
        calls.append("dispatch")
        return "MUN-1"

    dispatcher = SimpleNamespace(dispatch=fake_dispatch)
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher)
    session = _patch_session(monkeypatch)

    real_commit = session.commit

    async def tracking_commit():
        calls.append("commit")
        await real_commit()

    session.commit = tracking_commit

    asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert calls.index("commit") < calls.index("dispatch")


def test_dispatch_grievance_reads_existing_pdf_bytes(monkeypatch, tmp_path):
    pdf_file = tmp_path / "summary.pdf"
    pdf_file.write_bytes(b"%PDF-bytes")
    grievance = _grievance(routing_snapshot={}, pdf_path=str(pdf_file))
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    monkeypatch.setattr(core, "set_grievance_fields", AsyncMock())
    monkeypatch.setattr(core, "add_grievance_event", AsyncMock())
    monkeypatch.setattr(core, "artifact_path", lambda _s, path: pdf_file)
    captured = {}

    async def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return "MUN-2"

    dispatcher = SimpleNamespace(dispatch=fake_dispatch)
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher)
    _patch_session(monkeypatch)

    asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert captured["pdf_bytes"] == b"%PDF-bytes"


def test_dispatch_grievance_error_below_max_attempts_stays_dispatching(monkeypatch):
    grievance = _grievance(routing_snapshot={}, dispatch_attempts=0)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    add_event = AsyncMock()
    monkeypatch.setattr(core, "add_grievance_event", add_event)
    dispatcher = SimpleNamespace(dispatch=AsyncMock(side_effect=DispatchError("nope")))
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher)
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "dispatching"
    assert set_fields.call_args.kwargs["dispatch_attempts"] == 1
    add_event.assert_not_awaited()


def test_dispatch_grievance_error_at_max_attempts_marks_failed(monkeypatch):
    grievance = _grievance(routing_snapshot={}, dispatch_attempts=core.MAX_DISPATCH_ATTEMPTS - 1)
    monkeypatch.setattr(core, "get_grievance", AsyncMock(return_value=grievance))
    set_fields = AsyncMock()
    monkeypatch.setattr(core, "set_grievance_fields", set_fields)
    add_event = AsyncMock()
    monkeypatch.setattr(core, "add_grievance_event", add_event)
    dispatcher = SimpleNamespace(dispatch=AsyncMock(side_effect=DispatchError("nope")))
    monkeypatch.setattr(core, "get_dispatcher", lambda *_a: dispatcher)
    _patch_session(monkeypatch)

    outcome = asyncio.run(core.dispatch_grievance(_settings(), object(), grievance_id=grievance.id))

    assert outcome.status == "dispatch_failed"
    add_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# sweep_expired_windows / sweep_stuck_dispatching
# ---------------------------------------------------------------------------


def test_sweep_expired_windows_returns_zero_when_none_expired(monkeypatch):
    monkeypatch.setattr(core, "fetch_expired_windows", AsyncMock(return_value=[]))
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(core, "dispatch_grievance", dispatch_mock)
    _patch_session(monkeypatch)

    count = asyncio.run(core.sweep_expired_windows(_settings(), object(), limit=10))

    assert count == 0
    dispatch_mock.assert_not_awaited()


def test_sweep_expired_windows_dispatches_each_id(monkeypatch):
    ids = [uuid.uuid4(), uuid.uuid4()]
    monkeypatch.setattr(core, "fetch_expired_windows", AsyncMock(return_value=ids))
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(core, "dispatch_grievance", dispatch_mock)
    _patch_session(monkeypatch)

    count = asyncio.run(core.sweep_expired_windows(_settings(), object(), limit=10))

    assert count == 2
    assert dispatch_mock.await_count == 2


def test_sweep_expired_windows_logs_and_continues_on_dispatch_failure(monkeypatch):
    ids = [uuid.uuid4()]
    monkeypatch.setattr(core, "fetch_expired_windows", AsyncMock(return_value=ids))
    monkeypatch.setattr(core, "dispatch_grievance", AsyncMock(side_effect=RuntimeError("boom")))
    _patch_session(monkeypatch)

    count = asyncio.run(core.sweep_expired_windows(_settings(), object(), limit=10))

    assert count == 1


def test_sweep_stuck_dispatching_returns_zero_when_none_stuck(monkeypatch):
    monkeypatch.setattr(core, "fetch_stuck_dispatching", AsyncMock(return_value=[]))
    dispatch_mock = AsyncMock()
    monkeypatch.setattr(core, "dispatch_grievance", dispatch_mock)
    _patch_session(monkeypatch)

    count = asyncio.run(core.sweep_stuck_dispatching(_settings(), object(), limit=5))

    assert count == 0
    dispatch_mock.assert_not_awaited()


def test_sweep_stuck_dispatching_retries_each_id_and_survives_errors(monkeypatch):
    ids = [uuid.uuid4(), uuid.uuid4()]
    monkeypatch.setattr(core, "fetch_stuck_dispatching", AsyncMock(return_value=ids))
    monkeypatch.setattr(
        core, "dispatch_grievance", AsyncMock(side_effect=[None, RuntimeError("boom")])
    )
    _patch_session(monkeypatch)

    count = asyncio.run(core.sweep_stuck_dispatching(_settings(), object(), limit=5))

    assert count == 2


# ---------------------------------------------------------------------------
# MockApiDispatcher
# ---------------------------------------------------------------------------


def test_mock_api_dispatcher_malformed_json_raises_dispatch_error():
    """A 2xx with an unparseable body must surface as DispatchError (so
    dispatch_grievance's attempt-counting/give-up logic still applies), not
    an uncaught ValueError."""
    from jan_setu.pipeline.dispatchers import MockApiDispatcher

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    class Client:
        async def post(self, *_args, **_kwargs):
            return Response()

    dispatcher = MockApiDispatcher(_settings(), Client())
    department = SimpleNamespace(key="public_works")

    with pytest.raises(DispatchError):
        asyncio.run(
            dispatcher.dispatch(human_id="JS-1", department=department, summary="x", pdf_bytes=b"")
        )
