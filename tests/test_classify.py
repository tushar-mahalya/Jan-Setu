from jan_setu.pipeline.classify import parse_classification, parse_image_match
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
