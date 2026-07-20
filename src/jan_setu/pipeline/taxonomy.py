"""Versioned civic service taxonomy and deterministic routing policy.

Canonical service IDs are national and stable. Actual ownership, department,
SLA, and dispatch targets come from a reviewed jurisdiction profile; the bundled
demo profile must never be used for live external dispatch.
"""

from dataclasses import dataclass
from typing import Literal

TAXONOMY_VERSION = "2026-07-v2"
DEMO_JURISDICTION_ID = "demo-ulb"

SafetyLevel = Literal["none", "possible", "immediate"]
AssetScope = Literal["public", "private", "unknown"]
Disposition = Literal[
    "municipal_ticket",
    "municipal_ticket_and_escalate",
    "redirect",
    "emergency_redirect",
    "needs_human_review",
]


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    department_key: str
    default_priority: str
    term_hint: str
    parent_key: str = "other_needs_review"
    aggregation_key: str | None = None
    hindi_label: str = ""
    synonyms: tuple[str, ...] = ()
    active: bool = True


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    email: str


@dataclass(frozen=True)
class JurisdictionRoute:
    category_key: str
    department_key: str
    owning_agency: str
    sla_hours: int | None = None
    dispatch_enabled: bool = False
    official_service_url: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class JurisdictionProfile:
    key: str
    name: str
    is_demo: bool
    routes: dict[str, JurisdictionRoute]


@dataclass(frozen=True)
class RoutingDecision:
    disposition: Disposition
    priority: str
    dedup_eligible: bool
    needs_official_review: bool
    reason: str


DOMAIN_LABELS = {
    "roads_mobility": "Roads & Mobility",
    "street_lighting_electrical": "Street Lighting & Electrical Hazards",
    "solid_waste_cleanliness": "Solid Waste, Cleanliness & Public Toilets",
    "water_supply": "Water Supply",
    "sewerage_drainage_flooding": "Sewerage, Drainage & Flooding",
    "parks_trees_public_spaces": "Parks, Trees & Public Spaces",
    "public_health_vector_control": "Public Health & Vector Control",
    "animal_welfare": "Animal Welfare",
    "land_use_building_public_realm": "Land Use, Buildings & Public Realm",
    "civic_documents_service_delivery": "Civic Documents & Service Delivery",
    "other_needs_review": "Other / Needs Review",
}


def _category(
    key: str,
    label: str,
    parent: str,
    department: str,
    *,
    priority: str = "normal",
    term: str = "short_term",
    hindi: str = "",
    synonyms: tuple[str, ...] = (),
    aggregation: str | None = None,
) -> Category:
    return Category(
        key=key,
        label=label,
        department_key=department,
        default_priority=priority,
        term_hint=term,
        parent_key=parent,
        aggregation_key=aggregation or key,
        hindi_label=hindi,
        synonyms=synonyms,
    )


_CATEGORY_ROWS = (
    _category(
        "pothole_surface_damage",
        "Pothole or road surface damage",
        "roads_mobility",
        "public_works",
        term="long_term",
        synonyms=("pothole", "gaddha", "गड्ढा"),
    ),
    _category(
        "road_cave_in",
        "Road cave-in or collapse",
        "roads_mobility",
        "public_works",
        priority="priority",
        term="long_term",
    ),
    _category(
        "footpath_damage_or_obstruction",
        "Footpath damage or obstruction",
        "roads_mobility",
        "public_works",
        term="long_term",
    ),
    _category(
        "median_or_guardrail_damage",
        "Median or guardrail damage",
        "roads_mobility",
        "public_works",
        term="long_term",
    ),
    _category(
        "road_marking_or_signage", "Road marking or signage", "roads_mobility", "public_works"
    ),
    _category(
        "speed_breaker_or_traffic_calming",
        "Speed breaker or traffic calming",
        "roads_mobility",
        "public_works",
        term="long_term",
    ),
    _category("municipal_parking", "Municipal parking", "roads_mobility", "public_works"),
    _category(
        "drain_cover_on_road",
        "Road drain cover",
        "roads_mobility",
        "public_works",
        priority="priority",
    ),
    _category(
        "streetlight_out",
        "Streetlight not working",
        "street_lighting_electrical",
        "electrical",
        synonyms=("street light", "बत्ती"),
    ),
    _category(
        "streetlight_flickering",
        "Streetlight flickering",
        "street_lighting_electrical",
        "electrical",
    ),
    _category(
        "damaged_pole_or_fixture",
        "Damaged lighting pole or fixture",
        "street_lighting_electrical",
        "electrical",
        priority="priority",
    ),
    _category(
        "exposed_or_low_hanging_wire",
        "Exposed or low-hanging wire",
        "street_lighting_electrical",
        "external_referral",
        priority="priority",
    ),
    _category(
        "electrical_box_or_transformer_hazard",
        "Electrical box or transformer hazard",
        "street_lighting_electrical",
        "external_referral",
        priority="priority",
    ),
    _category(
        "unauthorized_connection",
        "Unauthorized electrical connection report",
        "street_lighting_electrical",
        "external_referral",
    ),
    _category(
        "missed_door_to_door_collection",
        "Missed door-to-door waste collection",
        "solid_waste_cleanliness",
        "sanitation",
    ),
    _category(
        "overflowing_community_bin",
        "Overflowing community bin",
        "solid_waste_cleanliness",
        "sanitation",
    ),
    _category(
        "open_dumping_or_litter", "Open dumping or litter", "solid_waste_cleanliness", "sanitation"
    ),
    _category(
        "construction_and_demolition_waste",
        "Construction and demolition waste",
        "solid_waste_cleanliness",
        "sanitation",
    ),
    _category(
        "bulk_or_commercial_waste",
        "Bulk or commercial waste",
        "solid_waste_cleanliness",
        "sanitation",
    ),
    _category(
        "burning_waste",
        "Burning waste",
        "solid_waste_cleanliness",
        "sanitation",
        priority="priority",
    ),
    _category(
        "dead_animal_collection", "Dead animal collection", "solid_waste_cleanliness", "sanitation"
    ),
    _category("street_sweeping", "Street sweeping", "solid_waste_cleanliness", "sanitation"),
    _category(
        "public_toilet_cleanliness_or_maintenance",
        "Public toilet cleanliness or maintenance",
        "solid_waste_cleanliness",
        "sanitation",
    ),
    _category("no_or_low_supply", "No or low water supply", "water_supply", "water_works"),
    _category("pipeline_leak", "Water pipeline leak", "water_supply", "water_works"),
    _category("public_tap_or_standpost", "Public tap or standpost", "water_supply", "water_works"),
    _category(
        "meter_or_connection_issue",
        "Water meter or connection issue",
        "water_supply",
        "water_works",
    ),
    _category(
        "water_quality_or_contamination",
        "Water quality or contamination",
        "water_supply",
        "water_works",
        priority="priority",
    ),
    _category(
        "illegal_water_connection_report",
        "Illegal water connection report",
        "water_supply",
        "water_works",
    ),
    _category(
        "waterlogging_from_supply_leak",
        "Waterlogging from supply leak",
        "water_supply",
        "water_works",
    ),
    _category(
        "blocked_storm_drain", "Blocked storm drain", "sewerage_drainage_flooding", "public_works"
    ),
    _category(
        "stormwater_flooding",
        "Stormwater flooding",
        "sewerage_drainage_flooding",
        "public_works",
        priority="priority",
    ),
    _category(
        "sewage_overflow",
        "Sewage overflow",
        "sewerage_drainage_flooding",
        "public_works",
        priority="priority",
    ),
    _category(
        "blocked_sewer_or_manhole",
        "Blocked sewer or manhole",
        "sewerage_drainage_flooding",
        "public_works",
    ),
    _category(
        "open_or_damaged_manhole",
        "Open or damaged manhole",
        "sewerage_drainage_flooding",
        "public_works",
        priority="priority",
    ),
    _category(
        "septic_or_faecal_sludge_service",
        "Septic or faecal sludge service",
        "sewerage_drainage_flooding",
        "public_works",
    ),
    _category("drain_desilting", "Drain desilting", "sewerage_drainage_flooding", "public_works"),
    _category(
        "mosquito_breeding_site",
        "Mosquito breeding site",
        "sewerage_drainage_flooding",
        "public_health",
    ),
    _category(
        "park_maintenance",
        "Park maintenance",
        "parks_trees_public_spaces",
        "parks",
        term="long_term",
    ),
    _category(
        "playground_or_open_gym_equipment",
        "Playground or open-gym equipment",
        "parks_trees_public_spaces",
        "parks",
        priority="priority",
    ),
    _category(
        "fallen_or_hazardous_tree",
        "Fallen or hazardous tree",
        "parks_trees_public_spaces",
        "parks",
        priority="priority",
    ),
    _category("tree_pruning_request", "Tree pruning request", "parks_trees_public_spaces", "parks"),
    _category(
        "public_space_cleanliness", "Public-space cleanliness", "parks_trees_public_spaces", "parks"
    ),
    _category(
        "public_fountain_or_amenity",
        "Public fountain or amenity",
        "parks_trees_public_spaces",
        "parks",
    ),
    _category(
        "illegal_tree_cutting_report",
        "Illegal tree cutting report",
        "parks_trees_public_spaces",
        "parks",
        priority="priority",
    ),
    _category(
        "mosquito_or_vector_control",
        "Mosquito or vector control",
        "public_health_vector_control",
        "public_health",
    ),
    _category(
        "stray_dog_bite_public_health_referral",
        "Animal bite health referral",
        "public_health_vector_control",
        "external_referral",
        priority="priority",
    ),
    _category(
        "public_nuisance_sanitation",
        "Public sanitation nuisance",
        "public_health_vector_control",
        "public_health",
    ),
    _category(
        "food_safety_public_premises_referral",
        "Food safety referral",
        "public_health_vector_control",
        "external_referral",
    ),
    _category(
        "unsafe_public_toilet",
        "Unsafe public toilet",
        "public_health_vector_control",
        "public_health",
        priority="priority",
    ),
    _category(
        "injured_or_trapped_animal",
        "Injured or trapped animal",
        "animal_welfare",
        "animal_welfare",
        priority="priority",
    ),
    _category(
        "aggressive_or_nuisance_animal",
        "Aggressive or nuisance animal",
        "animal_welfare",
        "animal_welfare",
        priority="priority",
    ),
    _category(
        "stray_dog_population_management",
        "Stray dog population management",
        "animal_welfare",
        "animal_welfare",
    ),
    _category(
        "animal_cruelty_report",
        "Animal cruelty report",
        "animal_welfare",
        "external_referral",
        priority="priority",
    ),
    _category("animal_carcass", "Animal carcass", "animal_welfare", "sanitation"),
    _category(
        "livestock_on_road",
        "Livestock on road",
        "animal_welfare",
        "animal_welfare",
        priority="priority",
    ),
    _category(
        "public_land_encroachment",
        "Public-land encroachment",
        "land_use_building_public_realm",
        "town_planning",
        term="long_term",
    ),
    _category(
        "unsafe_or_illegal_construction_report",
        "Unsafe or illegal construction report",
        "land_use_building_public_realm",
        "town_planning",
        term="long_term",
    ),
    _category(
        "unauthorized_hawking_or_obstruction",
        "Hawking or public-way obstruction",
        "land_use_building_public_realm",
        "town_planning",
    ),
    _category(
        "advertising_or_hoarding",
        "Advertising or hoarding",
        "land_use_building_public_realm",
        "town_planning",
    ),
    _category(
        "abandoned_vehicle_on_public_way",
        "Abandoned vehicle on public way",
        "land_use_building_public_realm",
        "external_referral",
    ),
    _category(
        "public_property_damage",
        "Public-property damage",
        "land_use_building_public_realm",
        "general",
        term="long_term",
    ),
    _category(
        "municipal_tax_or_bill_query",
        "Municipal tax or bill query",
        "civic_documents_service_delivery",
        "citizen_services",
    ),
    _category(
        "birth_death_certificate_referral",
        "Birth or death certificate referral",
        "civic_documents_service_delivery",
        "citizen_services",
    ),
    _category(
        "trade_license_referral",
        "Trade licence referral",
        "civic_documents_service_delivery",
        "citizen_services",
    ),
    _category(
        "building_permission_status",
        "Building permission status",
        "civic_documents_service_delivery",
        "town_planning",
    ),
    _category(
        "grievance_status_or_escalation",
        "Grievance status or escalation",
        "civic_documents_service_delivery",
        "general",
    ),
    _category(
        "accessibility_or_service_centre_issue",
        "Accessibility or service-centre issue",
        "civic_documents_service_delivery",
        "citizen_services",
    ),
    _category(
        "insufficient_information", "Insufficient information", "other_needs_review", "general"
    ),
    _category("multi_issue", "Multiple civic issues", "other_needs_review", "general"),
    _category("unmapped_service", "Unmapped service", "other_needs_review", "general"),
    _category(
        "possible_non_municipal",
        "Possible non-municipal issue",
        "other_needs_review",
        "external_referral",
    ),
)

CANONICAL_CATEGORIES: dict[str, Category] = {category.key: category for category in _CATEGORY_ROWS}

DEPARTMENTS: dict[str, Department] = {
    "public_works": Department(
        "public_works", "Public Works Department", "public-works@municipal.example"
    ),
    "electrical": Department(
        "electrical", "Street Lighting Department", "electrical@municipal.example"
    ),
    "sanitation": Department("sanitation", "Sanitation Department", "sanitation@municipal.example"),
    "water_works": Department(
        "water_works", "Water Works Department", "water-works@municipal.example"
    ),
    "public_health": Department(
        "public_health", "Public Health Department", "public-health@municipal.example"
    ),
    "animal_welfare": Department(
        "animal_welfare", "Animal Welfare Department", "animal-welfare@municipal.example"
    ),
    "parks": Department("parks", "Parks & Gardens Department", "parks@municipal.example"),
    "town_planning": Department(
        "town_planning", "Town Planning Department", "town-planning@municipal.example"
    ),
    "citizen_services": Department(
        "citizen_services", "Citizen Services", "citizen-services@municipal.example"
    ),
    "general": Department("general", "General Grievance Cell", "grievance-cell@municipal.example"),
    "external_referral": Department(
        "external_referral", "External Authority Referral", "referrals@municipal.example"
    ),
}

LEGACY_CATEGORY_ALIASES = {
    "roads_potholes": "pothole_surface_damage",
    "streetlights": "streetlight_out",
    "drainage_sewerage": "blocked_storm_drain",
    "water_supply": "no_or_low_supply",
    "garbage_collection": "missed_door_to_door_collection",
    "stray_animals": "stray_dog_population_management",
    "parks": "park_maintenance",
}
AMBIGUOUS_LEGACY_CATEGORIES = frozenset({"sanitation", "encroachment", "electricity", "other"})
# Compatibility view for the current API/parser while v2 fields roll out. New
# extraction prompts use CANONICAL_CATEGORIES only.
CATEGORIES: dict[str, Category] = {
    **CANONICAL_CATEGORIES,
    **{
        legacy: CANONICAL_CATEGORIES[canonical]
        for legacy, canonical in LEGACY_CATEGORY_ALIASES.items()
    },
    "water_supply": CANONICAL_CATEGORIES["no_or_low_supply"],
    "sanitation": CANONICAL_CATEGORIES["public_nuisance_sanitation"],
    "encroachment": CANONICAL_CATEGORIES["public_land_encroachment"],
    "electricity": CANONICAL_CATEGORIES["electrical_box_or_transformer_hazard"],
    "other": CANONICAL_CATEGORIES["unmapped_service"],
}

DEMO_PROFILE = JurisdictionProfile(
    key=DEMO_JURISDICTION_ID,
    name="Demo Municipal Corporation (non-production)",
    is_demo=True,
    routes={
        category.key: JurisdictionRoute(
            category_key=category.key,
            department_key=category.department_key,
            owning_agency="Demo Municipal Corporation",
            sla_hours=24 if category.default_priority == "priority" else 72,
            dispatch_enabled=False,
        )
        for category in _CATEGORY_ROWS
    },
)

IMMEDIATE_SAFETY_CATEGORIES = frozenset(
    {
        "road_cave_in",
        "exposed_or_low_hanging_wire",
        "electrical_box_or_transformer_hazard",
        "open_or_damaged_manhole",
        "stray_dog_bite_public_health_referral",
    }
)
EXTERNAL_REFERRAL_CATEGORIES = frozenset(
    category.key for category in _CATEGORY_ROWS if category.department_key == "external_referral"
)


def canonical_category_key(key: str | None) -> str | None:
    if not key:
        return None
    if key in CANONICAL_CATEGORIES:
        return key
    if key in LEGACY_CATEGORY_ALIASES:
        return LEGACY_CATEGORY_ALIASES[key]
    legacy_defaults = {
        "sanitation": "public_nuisance_sanitation",
        "encroachment": "public_land_encroachment",
        "electricity": "electrical_box_or_transformer_hazard",
        "other": "unmapped_service",
    }
    return legacy_defaults.get(key)


def category_or_default(key: str | None) -> Category:
    canonical = canonical_category_key(key)
    return CANONICAL_CATEGORIES.get(canonical or "", CANONICAL_CATEGORIES["unmapped_service"])


def department_for_category(category_key: str) -> Department:
    return DEPARTMENTS[category_or_default(category_key).department_key]


def route_for_category(
    category_key: str, profile: JurisdictionProfile = DEMO_PROFILE
) -> JurisdictionRoute | None:
    canonical = canonical_category_key(category_key)
    return profile.routes.get(canonical or "")


def evaluate_routing_policy(
    *,
    category_key: str | None,
    safety: SafetyLevel = "none",
    asset_scope: AssetScope = "unknown",
    jurisdiction_known: bool = True,
    extraction_confidence: float = 1.0,
    profile: JurisdictionProfile = DEMO_PROFILE,
) -> RoutingDecision:
    """Convert uncertain model facts into deterministic operational behavior."""
    canonical = canonical_category_key(category_key)
    if safety == "immediate" or canonical in IMMEDIATE_SAFETY_CATEGORIES:
        return RoutingDecision(
            disposition="emergency_redirect",
            priority="priority",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Immediate safety indicator requires emergency guidance and official escalation.",
        )
    if not jurisdiction_known:
        return RoutingDecision(
            disposition="redirect",
            priority="normal",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Location is outside or not resolved to a configured jurisdiction.",
        )
    if canonical is None or canonical in {
        "insufficient_information",
        "multi_issue",
        "unmapped_service",
        "possible_non_municipal",
    }:
        return RoutingDecision(
            disposition="needs_human_review",
            priority="normal",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Issue is ambiguous, multi-issue, or outside the configured taxonomy.",
        )
    if asset_scope == "private":
        return RoutingDecision(
            disposition="redirect",
            priority="normal",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Reported asset appears private and ownership must be verified.",
        )
    if canonical in EXTERNAL_REFERRAL_CATEGORIES:
        return RoutingDecision(
            disposition="redirect",
            priority="priority" if safety == "possible" else "normal",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Configured service belongs to an external authority.",
        )
    route = route_for_category(canonical, profile)
    if route is None or extraction_confidence < 0.65 or asset_scope == "unknown":
        return RoutingDecision(
            disposition="needs_human_review",
            priority=category_or_default(canonical).default_priority,
            dedup_eligible=False,
            needs_official_review=True,
            reason="Category confidence or public-asset ownership is insufficient for automatic routing.",
        )
    if safety == "possible":
        return RoutingDecision(
            disposition="municipal_ticket_and_escalate",
            priority="priority",
            dedup_eligible=False,
            needs_official_review=True,
            reason="Possible safety risk requires expedited official review.",
        )
    return RoutingDecision(
        disposition="municipal_ticket",
        priority=category_or_default(canonical).default_priority,
        dedup_eligible=category_or_default(canonical).default_priority != "priority",
        needs_official_review=False,
        reason="Configured public municipal service with sufficient evidence.",
    )


def validate_taxonomy() -> None:
    if len(CANONICAL_CATEGORIES) != len(_CATEGORY_ROWS):
        raise ValueError("Duplicate canonical category key")
    for category in CANONICAL_CATEGORIES.values():
        if category.parent_key not in DOMAIN_LABELS:
            raise ValueError(f"Unknown parent domain for {category.key}")
        if category.department_key not in DEPARTMENTS:
            raise ValueError(f"Unknown department for {category.key}")
        if not category.aggregation_key:
            raise ValueError(f"Missing aggregation key for {category.key}")
    for legacy, canonical in LEGACY_CATEGORY_ALIASES.items():
        if legacy in CANONICAL_CATEGORIES or canonical not in CANONICAL_CATEGORIES:
            raise ValueError(f"Invalid legacy alias {legacy!r} -> {canonical!r}")
    if not DEMO_PROFILE.is_demo or any(
        route.dispatch_enabled for route in DEMO_PROFILE.routes.values()
    ):
        raise ValueError("Bundled demo jurisdiction must not enable live dispatch")


validate_taxonomy()
