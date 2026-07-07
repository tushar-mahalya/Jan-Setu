"""LLM classification and image-match checking via OpenRouter.

Free OpenRouter models rotate and don't reliably honor ``response_format``, so
the robust approach is: prompt for JSON, then parse defensively
(``parse_classification``/``parse_image_match`` are pure and unit-tested). A
config-driven model chain (``settings.openrouter_model_chain``) is tried in
order; total failure degrades to a safe default rather than blocking the
citizen's complaint from being filed.
"""

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jan_setu.config import Settings
from jan_setu.pipeline.taxonomy import CATEGORIES
from jan_setu.pipeline.throttle import reserve_slot

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM_PROMPT = (
    "You are a civic complaint triage assistant for Indian municipal corporations. "
    "Classify the complaint text into exactly one category from this list: "
    f"{', '.join(CATEGORIES)}. "
    "Respond with ONLY a JSON object, no prose, matching this shape: "
    '{"category": "<one of the listed keys>", "priority": "priority"|"normal", '
    '"term": "short_term"|"long_term", "confidence": <0..1>, "reasoning": "<one sentence>"}. '
    "Use priority only for urgent/animal-welfare/safety issues; term reflects whether this "
    "looks like a quick fix or a longer infrastructure project."
)

IMAGE_MATCH_SYSTEM_PROMPT = (
    "You check whether a photo plausibly matches a civic complaint's text description. "
    "Respond with ONLY a JSON object: "
    '{"matches": true|false, "confidence": <0..1>, "note": "<one short sentence>"}.'
)


@dataclass(frozen=True)
class Classification:
    category: str
    priority: str
    term: str
    confidence: float
    reasoning: str | None = None
    degraded: bool = False


@dataclass(frozen=True)
class ImageMatch:
    matches: bool
    confidence: float
    note: str | None = None
    degraded: bool = False


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction: some free models wrap JSON in prose/fences."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def parse_classification(raw_text: str) -> Classification | None:
    data = _extract_json(raw_text)
    if not data:
        return None
    category = data.get("category")
    if category not in CATEGORIES:
        return None
    default = CATEGORIES[category]
    priority = (
        data.get("priority")
        if data.get("priority") in ("priority", "normal")
        else default.default_priority
    )
    term = (
        data.get("term") if data.get("term") in ("short_term", "long_term") else default.term_hint
    )
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return Classification(
        category=category,
        priority=priority,
        term=term,
        confidence=max(0.0, min(1.0, confidence)),
        reasoning=data.get("reasoning"),
    )


def parse_image_match(raw_text: str) -> ImageMatch | None:
    data = _extract_json(raw_text)
    if not data or "matches" not in data:
        return None
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return ImageMatch(
        matches=bool(data["matches"]),
        confidence=max(0.0, min(1.0, confidence)),
        note=data.get("note"),
    )


async def _chat_completion(
    session: AsyncSession,
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    model: str,
    system_prompt: str,
    user_content: str | list[dict[str, Any]],
) -> str:
    wait = await reserve_slot(session, "openrouter", settings.openrouter_min_interval_seconds)
    if wait > 0:
        await asyncio.sleep(wait)

    assert settings.openrouter_api_key is not None
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    response = await http_client.post(
        url, headers=headers, json=body, timeout=settings.openrouter_timeout_seconds
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def classify_issue(
    session: AsyncSession, settings: Settings, http_client: httpx.AsyncClient, *, text: str | None
) -> Classification:
    degraded = Classification(
        category="other", priority="normal", term="short_term", confidence=0.0, degraded=True
    )
    if not settings.openrouter_api_key or not text or not text.strip():
        return degraded

    for model in settings.openrouter_model_chain:
        try:
            raw = await _chat_completion(
                session,
                settings,
                http_client,
                model=model,
                system_prompt=CLASSIFY_SYSTEM_PROMPT,
                user_content=text,
            )
        except (httpx.HTTPError, KeyError, IndexError):
            logger.warning("classify_model_failed", extra={"model": model})
            continue
        parsed = parse_classification(raw)
        if parsed is not None:
            return parsed

    logger.warning("classify_all_models_failed")
    return degraded


async def check_image_match(
    session: AsyncSession,
    settings: Settings,
    http_client: httpx.AsyncClient,
    *,
    text: str | None,
    image_bytes: bytes,
    mime_type: str,
) -> ImageMatch:
    # A checker we can't run is not evidence of a mismatch — never block filing
    # on a broken/unconfigured vision model.
    degraded = ImageMatch(matches=True, confidence=0.0, degraded=True)
    if not settings.openrouter_api_key:
        return degraded

    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    user_content = [
        {"type": "text", "text": f"Complaint description: {text or '(none provided)'}"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    for model in settings.openrouter_model_chain:
        try:
            raw = await _chat_completion(
                session,
                settings,
                http_client,
                model=model,
                system_prompt=IMAGE_MATCH_SYSTEM_PROMPT,
                user_content=user_content,
            )
        except (httpx.HTTPError, KeyError, IndexError):
            logger.warning("image_match_model_failed", extra={"model": model})
            continue
        parsed = parse_image_match(raw)
        if parsed is not None:
            return parsed

    logger.warning("image_match_all_models_failed")
    return degraded
