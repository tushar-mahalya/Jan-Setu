from unittest.mock import AsyncMock

import httpx

from jan_setu.config import Settings
from jan_setu.pipeline.classify import parse_classification, parse_extraction, parse_image_match
from jan_setu.pipeline.taxonomy import CATEGORIES


def test_parse_classification_valid_json():
    raw = (
        '{"category": "water_supply", "priority": "priority", "term": "long_term", '
        '"confidence": 0.9, "reasoning": "burst pipe reported"}'
    )
    result = parse_classification(raw)

    assert result is not None
    assert result.category == "water_supply"
    assert result.priority == "priority"
    assert result.term == "long_term"
    assert result.confidence == 0.9
    assert result.reasoning == "burst pipe reported"
    assert result.degraded is False


def test_parse_image_match_valid_json():
    raw = '{"matches": true, "confidence": 0.8, "note": "photo shows a pothole"}'
    result = parse_image_match(raw)

    assert result is not None
    assert result.matches is True
    assert result.confidence == 0.8
    assert result.note == "photo shows a pothole"
    assert result.degraded is False


def test_parse_classification_returns_none_for_non_json_text():
    assert parse_classification("sorry, I cannot help with that") is None


def test_parse_image_match_returns_none_for_non_json_text():
    assert parse_image_match("this is just plain prose, no json here") is None


def test_parse_classification_returns_none_for_unknown_category():
    raw = '{"category": "not_a_real_category", "priority": "normal", "term": "short_term", "confidence": 0.5}'
    assert parse_classification(raw) is None


def test_parse_classification_falls_back_to_category_defaults_when_fields_missing():
    category = CATEGORIES["roads_potholes"]
    raw = '{"category": "roads_potholes"}'

    result = parse_classification(raw)

    assert result is not None
    assert result.priority == category.default_priority
    assert result.term == category.term_hint
    assert result.confidence == 0.5


def test_parse_classification_falls_back_to_category_defaults_when_fields_invalid():
    category = CATEGORIES["streetlights"]
    raw = (
        '{"category": "streetlights", "priority": "urgent", "term": "medium_term", '
        '"confidence": "not-a-number"}'
    )

    result = parse_classification(raw)

    assert result is not None
    assert result.priority == category.default_priority
    assert result.term == category.term_hint
    assert result.confidence == 0.5


def test_parse_classification_clamps_confidence_above_one():
    raw = '{"category": "sanitation", "confidence": 1.5}'
    result = parse_classification(raw)

    assert result is not None
    assert result.confidence == 1.0


def test_parse_classification_clamps_confidence_below_zero():
    raw = '{"category": "sanitation", "confidence": -0.3}'
    result = parse_classification(raw)

    assert result is not None
    assert result.confidence == 0.0


def test_parse_image_match_clamps_confidence_to_range():
    raw_high = '{"matches": false, "confidence": 2.0}'
    raw_low = '{"matches": false, "confidence": -1.0}'

    assert parse_image_match(raw_high).confidence == 1.0
    assert parse_image_match(raw_low).confidence == 0.0


def test_parse_image_match_returns_none_when_matches_key_missing():
    raw = '{"confidence": 0.5, "note": "no matches field here"}'
    assert parse_image_match(raw) is None


def test_parse_image_match_falls_back_confidence_when_invalid():
    raw = '{"matches": true, "confidence": "n/a"}'
    result = parse_image_match(raw)

    assert result is not None
    assert result.confidence == 0.5


def test_parse_classification_extracts_json_wrapped_in_prose_and_code_fence():
    raw = (
        "Sure, here is the classification:\n"
        "```json\n"
        '{"category": "streetlights", "priority": "normal", "term": "short_term", '
        '"confidence": 0.75, "reasoning": "broken light on main road"}\n'
        "```\n"
        "Let me know if you need anything else."
    )

    result = parse_classification(raw)

    assert result is not None
    assert result.category == "streetlights"
    assert result.confidence == 0.75


def test_parse_structured_multilingual_extraction():
    raw = """{
      "summary": "मुख्य सड़क पर खुला मैनहोल है",
      "category_id": "open_or_damaged_manhole",
      "alternative_category_ids": ["drain_cover_on_road"],
      "confidence": 0.94,
      "asset_scope": "public",
      "owner_hint": "ulb",
      "safety": "immediate",
      "requested_action": "Cover the manhole",
      "landmark": "बस स्टैंड",
      "incident_time": null,
      "missing_facts": [],
      "clarification_question": null,
      "evidence": ["खुला मैनहोल"],
      "image_observations": ["Open circular road cavity"],
      "contradictions": [],
      "multiple_issues": false
    }"""
    result = parse_extraction(raw)
    assert result is not None
    assert result.category_id == "open_or_damaged_manhole"
    assert result.safety == "immediate"
    assert result.asset_scope == "public"
    assert result.landmark == "बस स्टैंड"


def test_structured_extraction_rejects_unknown_taxonomy_id():
    raw = '{"summary":"x","category_id":"invented_department","confidence":0.9}'
    assert parse_extraction(raw) is None


def test_structured_extraction_normalizes_untrusted_enums():
    raw = '{"summary":"wire","category_id":"exposed_or_low_hanging_wire","confidence":5,"asset_scope":"government","owner_hint":"made_up","safety":"urgent","alternative_category_ids":[]}'
    result = parse_extraction(raw)
    assert result is not None
    assert result.confidence == 1.0
    assert result.asset_scope == "unknown"
    assert result.owner_hint == "unknown"
    assert result.safety == "possible"


def test_parse_image_match_extracts_json_wrapped_in_prose_and_code_fence():
    raw = (
        "Here you go:\n"
        "```json\n"
        '{"matches": true, "confidence": 0.6, "note": "looks consistent"}\n'
        "```\n"
        "Hope that helps!"
    )

    result = parse_image_match(raw)

    assert result is not None
    assert result.matches is True
    assert result.confidence == 0.6


def test_combines_typed_text_and_every_voice_transcript_before_extraction(monkeypatch):
    import asyncio

    from jan_setu.pipeline.core import _combine_issue_text
    from jan_setu.pipeline.stt import TranscriptionResult

    async def download(*_args):
        return b"voice", "audio/webm"

    results = iter(
        [
            TranscriptionResult(ok=True, text="स्ट्रीट लाइट बंद है", detected_language="hi-IN"),
            TranscriptionResult(ok=True, text="near the bus stop", detected_language="en-IN"),
        ]
    )

    async def transcribe(*_args, **_kwargs):
        return next(results)

    monkeypatch.setattr("jan_setu.pipeline.core.download_whatsapp_media", download)
    monkeypatch.setattr("jan_setu.pipeline.core.transcribe_clip", transcribe)
    combined, language, flags, transcripts = asyncio.run(
        _combine_issue_text(
            object(),
            Settings(_env_file=None),
            object(),
            [
                {"type": "text", "text": "Please fix this urgently."},
                {"type": "audio", "media_id": "voice-one"},
                {"type": "voice", "media_id": "voice-two"},
            ],
        )
    )

    assert combined == "Please fix this urgently.\nस्ट्रीट लाइट बंद है\nnear the bus stop"
    assert language == "hi-IN"
    assert flags == []
    assert [item["text"] for item in transcripts] == ["स्ट्रीट लाइट बंद है", "near the bus stop"]


def test_stt_uses_original_language_transcription(monkeypatch):
    import asyncio

    from jan_setu.pipeline.stt import transcribe_clip

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"transcript": "स्ट्रीट लाइट खराब है", "language_code": "hi-IN"}

    class Client:
        async def post(self, url, **kwargs):
            assert kwargs["data"] == {"model": "saaras:v3", "mode": "transcribe"}
            assert kwargs["files"]["file"][2] == "audio/webm"
            return Response()

    class Session:
        pass

    async def no_wait(*_args):
        return 0

    monkeypatch.setattr("jan_setu.pipeline.stt.reserve_slot", no_wait)
    result = asyncio.run(
        transcribe_clip(
            Session(),
            Settings(_env_file=None, sarvam_api_key="key"),
            Client(),
            audio_bytes=b"voice",
            mime_type="audio/webm",
        )
    )

    assert result.ok
    assert result.text == "स्ट्रीट लाइट खराब है"
    assert result.detected_language == "hi-IN"


def _settings(**overrides):
    from jan_setu.config import Settings

    return Settings(_env_file=None, **overrides)


def test_attempts_groq_first_then_openrouter_failsafe():
    from jan_setu.pipeline.classify import EXTRACTION_SCHEMA, build_extraction_attempts

    settings = _settings(groq_api_key="gk", openrouter_api_key="ok")
    attempts = build_extraction_attempts(settings, schema=EXTRACTION_SCHEMA)

    providers = [attempt["provider"] for attempt in attempts]
    assert providers == ["groq", "groq", "groq", "openrouter"]
    primary = attempts[0]["body"]
    assert primary["model"] == "openai/gpt-oss-120b"
    assert primary["reasoning_effort"] == "low"
    assert primary["response_format"]["type"] == "json_schema"
    assert primary["response_format"]["json_schema"]["strict"] is True
    # llama can't enforce json_schema on Groq — falls back to json_object mode
    assert attempts[2]["body"]["response_format"] == {"type": "json_object"}


def test_attempts_image_requests_skip_groq_no_vision_models():
    from jan_setu.pipeline.classify import build_extraction_attempts

    settings = _settings(groq_api_key="gk", openrouter_api_key="ok")
    attempts = build_extraction_attempts(settings, has_image=True)

    assert [attempt["provider"] for attempt in attempts] == ["openrouter"]


def test_attempts_escalated_uses_high_reasoning_effort():
    from jan_setu.pipeline.classify import build_extraction_attempts

    settings = _settings(groq_api_key="gk")
    attempts = build_extraction_attempts(settings, escalated=True)

    assert attempts[0]["body"]["reasoning_effort"] == "high"


def test_attempts_openrouter_models_array_capped_at_three():
    from jan_setu.pipeline.classify import build_extraction_attempts

    settings = _settings(openrouter_api_key="ok", openrouter_models="a,b,c,d,e")
    attempts = build_extraction_attempts(settings)

    assert attempts[0]["body"]["models"] == ["a", "b", "c"]


def test_attempts_empty_without_any_provider_key():
    from jan_setu.pipeline.classify import build_extraction_attempts

    assert build_extraction_attempts(_settings()) == []


# ---------------------------------------------------------------------------
# _extract_json edge case: text matches `{...}` regex but is invalid JSON.
# ---------------------------------------------------------------------------


def test_extract_json_returns_none_on_malformed_json_syntax():
    from jan_setu.pipeline.classify import _extract_json

    assert _extract_json("here is your answer: {not valid json at all}") is None


# ---------------------------------------------------------------------------
# extract_issue / classify_issue / check_image_match — cheap no-API-key paths
# ---------------------------------------------------------------------------


def test_extract_issue_returns_degraded_for_missing_text():
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    result = asyncio.run(extract_issue(object(), _settings(), object(), text="   "))
    assert result.degraded is True
    assert result.degradation_reason == "missing_text"
    assert result.category_id == "insufficient_information"


def test_extract_issue_degrades_when_no_provider_configured_and_detects_safety_terms():
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    result = asyncio.run(
        extract_issue(object(), _settings(), object(), text="There is a live wire on the road")
    )
    assert result.degraded is True
    assert result.degradation_reason == "llm_not_configured"
    assert result.safety == "possible"


def test_extract_issue_degrades_without_safety_terms():
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    result = asyncio.run(extract_issue(object(), _settings(), object(), text="Just a pothole"))
    assert result.safety == "none"


def test_classify_issue_falls_back_to_default_classification_when_degraded():
    import asyncio

    from jan_setu.pipeline.classify import classify_issue

    result = asyncio.run(
        classify_issue(object(), _settings(), object(), text="Streetlight is broken")
    )
    assert result.degraded is True
    assert result.category == "insufficient_information"


def test_check_image_match_returns_degraded_default_without_any_provider():
    import asyncio

    from jan_setu.pipeline.classify import check_image_match

    result = asyncio.run(
        check_image_match(
            object(),
            _settings(),
            object(),
            text="pothole",
            image_bytes=b"x",
            mime_type="image/jpeg",
        )
    )
    assert result.matches is True
    assert result.confidence == 0.0
    assert result.degraded is True


# ---------------------------------------------------------------------------
# extract_issue / check_image_match with a fake HTTP client — exercises
# _run_attempt, the retry loop, and every failure branch it can take.
# ---------------------------------------------------------------------------


class _FakeHTTPClient:
    """Replays a fixed sequence of responses/exceptions for successive posts."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _llm_response(content: str, model: str = "test-model") -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "model": model},
        request=httpx.Request("POST", "http://test.local"),
    )


def _http_status_error_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("POST", "http://test.local"))


_VALID_EXTRACTION_JSON = (
    '{"summary":"pothole on main road","category_id":"pothole_surface_damage",'
    '"alternative_category_ids":[],"confidence":0.9,"asset_scope":"public",'
    '"owner_hint":"ulb","safety":"none","requested_action":null,"landmark":null,'
    '"incident_time":null,"missing_facts":[],"clarification_question":null,'
    '"evidence":[],"image_observations":[],"contradictions":[],"multiple_issues":false}'
)


def test_extract_issue_succeeds_on_first_attempt(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient([_llm_response(_VALID_EXTRACTION_JSON)])
    settings = _settings(groq_api_key="gk")

    result = asyncio.run(
        extract_issue(object(), settings, client, text="There is a pothole on main road")
    )

    assert result.degraded is False
    assert result.category_id == "pothole_surface_damage"
    assert result.actual_provider == "groq"
    assert len(result.requested_models) == 3


def test_extract_issue_retries_past_http_error_and_unparseable_response(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient(
        [
            httpx.ConnectError("boom"),
            _llm_response("not json at all, sorry"),
            _llm_response(_VALID_EXTRACTION_JSON),
        ]
    )
    settings = _settings(groq_api_key="gk")

    result = asyncio.run(
        extract_issue(object(), settings, client, text="There is a pothole on main road")
    )

    assert result.degraded is False
    assert result.category_id == "pothole_surface_damage"
    assert len(client.calls) == 3


def test_extract_issue_all_attempts_quota_exhausted(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    settings = _settings(groq_api_key="gk", openrouter_api_key="ok")
    client = _FakeHTTPClient([_http_status_error_response(429) for _ in range(4)])

    result = asyncio.run(extract_issue(object(), settings, client, text="Pothole issue"))

    assert result.degraded is True
    assert result.degradation_reason == "provider_quota_exhausted"
    assert len(result.requested_models) == 4


def test_extract_issue_all_attempts_fail_generically(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    settings = _settings(groq_api_key="gk")
    client = _FakeHTTPClient([_llm_response("garbage") for _ in range(3)])

    result = asyncio.run(extract_issue(object(), settings, client, text="Pothole issue"))

    assert result.degraded is True
    assert result.degradation_reason == "all_models_failed"


def test_extract_issue_with_image_sends_multipart_content_and_skips_groq(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient([_llm_response(_VALID_EXTRACTION_JSON)])
    settings = _settings(groq_api_key="gk", openrouter_api_key="ok")

    result = asyncio.run(
        extract_issue(
            object(),
            settings,
            client,
            text="Pothole with photo",
            image_bytes=b"fake-bytes",
            image_mime_type="image/png",
        )
    )

    assert result.degraded is False
    assert result.actual_provider == "openrouter"
    sent_content = client.calls[0][1]["json"]["messages"][1]["content"]
    assert isinstance(sent_content, list)
    assert sent_content[1]["type"] == "image_url"


def test_extract_issue_appends_correction_context_for_escalated_reextraction(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient([_llm_response(_VALID_EXTRACTION_JSON)])
    settings = _settings(groq_api_key="gk")

    asyncio.run(
        extract_issue(
            object(),
            settings,
            client,
            text="Pothole issue",
            escalated=True,
            correction_context="Citizen insists this is a manhole, not a pothole.",
        )
    )

    sent_content = client.calls[0][1]["json"]["messages"][1]["content"]
    assert "Citizen review follow-up:" in sent_content
    assert "manhole" in sent_content
    # escalated reasoning effort was requested on the primary gpt-oss attempt
    assert client.calls[0][1]["json"]["reasoning_effort"] == "high"


def test_run_attempt_sleeps_for_reserved_wait_duration(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import extract_issue

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0.75))
    sleep_mock = AsyncMock()
    monkeypatch.setattr("jan_setu.pipeline.classify.asyncio.sleep", sleep_mock)
    client = _FakeHTTPClient([_llm_response(_VALID_EXTRACTION_JSON)])
    settings = _settings(groq_api_key="gk")

    asyncio.run(extract_issue(object(), settings, client, text="Pothole issue"))

    sleep_mock.assert_awaited_once_with(0.75)


def test_check_image_match_succeeds(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import check_image_match

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient(
        [_llm_response('{"matches": true, "confidence": 0.8, "note": "looks right"}')]
    )
    settings = _settings(openrouter_api_key="ok")

    result = asyncio.run(
        check_image_match(
            object(), settings, client, text="pothole", image_bytes=b"x", mime_type="image/jpeg"
        )
    )

    assert result.matches is True
    assert result.confidence == 0.8


def test_check_image_match_falls_back_to_degraded_on_repeated_failures(monkeypatch):
    import asyncio

    from jan_setu.pipeline.classify import check_image_match

    monkeypatch.setattr("jan_setu.pipeline.classify.reserve_slot", AsyncMock(return_value=0))
    client = _FakeHTTPClient([httpx.ConnectError("boom")])
    settings = _settings(openrouter_api_key="ok")

    result = asyncio.run(
        check_image_match(
            object(), settings, client, text="pothole", image_bytes=b"x", mime_type="image/jpeg"
        )
    )

    assert result.matches is True
    assert result.degraded is True
