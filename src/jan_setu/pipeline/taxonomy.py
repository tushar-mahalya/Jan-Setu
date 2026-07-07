"""Complaint taxonomy: Indian municipal complaint categories mapped to a
department + default priority/term. Deliberately code, not a DB table — this
is a handful of rows reviewed by PR, not admin-editable data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    department_key: str
    default_priority: str  # "priority" | "normal"
    term_hint: str  # "short_term" | "long_term"


@dataclass(frozen=True)
class Department:
    key: str
    name: str
    email: str


CATEGORIES: dict[str, Category] = {
    "roads_potholes": Category(
        "roads_potholes", "Roads & Potholes", "public_works", "normal", "long_term"
    ),
    "streetlights": Category(
        "streetlights", "Street Lighting", "electrical", "normal", "short_term"
    ),
    "sanitation": Category(
        "sanitation", "Sanitation & Public Toilets", "sanitation", "normal", "short_term"
    ),
    "drainage_sewerage": Category(
        "drainage_sewerage", "Drainage & Sewerage", "public_works", "normal", "long_term"
    ),
    "water_supply": Category("water_supply", "Water Supply", "water_works", "normal", "short_term"),
    "garbage_collection": Category(
        "garbage_collection", "Garbage Collection", "sanitation", "normal", "short_term"
    ),
    "stray_animals": Category(
        "stray_animals", "Stray Animal Cruelty & Care", "animal_welfare", "priority", "short_term"
    ),
    "parks": Category("parks", "Parks & Public Spaces", "parks", "normal", "long_term"),
    "encroachment": Category(
        "encroachment", "Encroachment", "town_planning", "normal", "long_term"
    ),
    "electricity": Category("electricity", "Electricity", "electrical", "normal", "short_term"),
    "other": Category("other", "Other", "general", "normal", "short_term"),
}

DEPARTMENTS: dict[str, Department] = {
    "public_works": Department(
        "public_works", "Public Works Department", "public-works@municipal.example"
    ),
    "electrical": Department("electrical", "Electrical Department", "electrical@municipal.example"),
    "sanitation": Department("sanitation", "Sanitation Department", "sanitation@municipal.example"),
    "water_works": Department(
        "water_works", "Water Works Department", "water-works@municipal.example"
    ),
    "animal_welfare": Department(
        "animal_welfare", "Animal Welfare Department", "animal-welfare@municipal.example"
    ),
    "parks": Department("parks", "Parks & Gardens Department", "parks@municipal.example"),
    "town_planning": Department(
        "town_planning", "Town Planning Department", "town-planning@municipal.example"
    ),
    "general": Department("general", "General Grievance Cell", "grievance-cell@municipal.example"),
}


def category_or_default(key: str | None) -> Category:
    return CATEGORIES.get(key or "", CATEGORIES["other"])


def department_for_category(category_key: str) -> Department:
    category = category_or_default(category_key)
    return DEPARTMENTS[category.department_key]
