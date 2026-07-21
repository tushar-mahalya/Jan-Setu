import pytest

from jan_setu.config import Settings
from pathlib import Path

from jan_setu.pipeline.media import (
    UploadTypeNotAllowed,
    artifact_path,
    guess_extension,
    normalize_mime_type,
    validate_upload,
)


def test_artifact_path_translates_host_upload_path_for_worker():
    settings = Settings(upload_dir="/data/uploads")

    assert artifact_path(settings, "data/uploads/grievance-123/voice.webm") == Path(
        "/data/uploads/grievance-123/voice.webm"
    )


def test_artifact_path_translates_worker_upload_path_for_host():
    settings = Settings(upload_dir="data/uploads")

    assert artifact_path(settings, "/data/uploads/grievance-123/summary.pdf") == Path(
        "data/uploads/grievance-123/summary.pdf"
    )


def test_normalize_mime_type_strips_browser_codec_parameter():
    assert normalize_mime_type("audio/webm;codecs=opus") == "audio/webm"


def test_audio_upload_accepts_browser_codec_parameter():
    validate_upload(
        mime_type="audio/webm;codecs=opus",
        size_bytes=1024,
        kind="audio",
        settings=Settings(),
    )


def test_extension_lookup_accepts_browser_codec_parameter():
    assert guess_extension("audio/webm;codecs=opus") == ".webm"


def test_audio_upload_still_rejects_disallowed_base_type():
    with pytest.raises(UploadTypeNotAllowed):
        validate_upload(
            mime_type="application/octet-stream;codecs=opus",
            size_bytes=1024,
            kind="audio",
            settings=Settings(),
        )
