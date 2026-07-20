from jan_setu.pipeline.taxonomy import (
    CANONICAL_CATEGORIES,
    DEMO_PROFILE,
    TAXONOMY_VERSION,
    canonical_category_key,
    evaluate_routing_policy,
    validate_taxonomy,
)


def test_taxonomy_registry_is_valid_and_versioned():
    validate_taxonomy()
    assert TAXONOMY_VERSION
    assert len(CANONICAL_CATEGORIES) >= 60
    assert DEMO_PROFILE.is_demo
    assert not any(route.dispatch_enabled for route in DEMO_PROFILE.routes.values())


def test_legacy_category_resolves_to_stable_leaf():
    assert canonical_category_key("roads_potholes") == "pothole_surface_damage"
    assert canonical_category_key("streetlights") == "streetlight_out"


def test_immediate_safety_never_auto_dispatches_or_deduplicates():
    decision = evaluate_routing_policy(
        category_key="open_or_damaged_manhole",
        safety="immediate",
        asset_scope="public",
        extraction_confidence=0.99,
    )
    assert decision.disposition == "emergency_redirect"
    assert decision.priority == "priority"
    assert not decision.dedup_eligible
    assert decision.needs_official_review


def test_clear_public_municipal_issue_can_enter_normal_flow():
    decision = evaluate_routing_policy(
        category_key="pothole_surface_damage",
        safety="none",
        asset_scope="public",
        extraction_confidence=0.9,
    )
    assert decision.disposition == "municipal_ticket"
    assert decision.dedup_eligible
    assert not decision.needs_official_review


def test_unknown_ownership_requires_review():
    decision = evaluate_routing_policy(
        category_key="pothole_surface_damage",
        asset_scope="unknown",
        extraction_confidence=0.9,
    )
    assert decision.disposition == "needs_human_review"
    assert decision.needs_official_review


def test_external_authority_category_redirects():
    decision = evaluate_routing_policy(
        category_key="electrical_box_or_transformer_hazard",
        safety="possible",
        asset_scope="public",
        extraction_confidence=0.9,
    )
    assert decision.disposition == "emergency_redirect"
    assert decision.priority == "priority"
    assert not decision.dedup_eligible
