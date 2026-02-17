#!/usr/bin/env python3
"""
Gemini utterance handler.

Accepts plain text and returns plain text. All OpenFloor event handling is in
template_agent.py.
"""

import logging
import os
from typing import Optional

from google import genai
import globals

DEFAULT_MODEL = "models/gemini-2.0-flash-lite"
FALLBACK_MODELS = (
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
SYSTEM_PROMPT = (
    "You are a helpful geography assistant. "
    "Answer clearly and concisely. "
    "If the question is not about geography, say so. "
    "Reply in this format:\n"
    "GEO=YES or GEO=NO\n"
    "RESPONSE: <your response>"
)

logger = logging.getLogger(__name__)

_RESPONSE_CACHE: dict[str, str] = {}
_GEO_KEYWORDS = {
    "map", "maps", "geography", "geo", "country", "countries", "capital",
    "capitals", "continent", "continents", "ocean", "oceans", "sea", "seas",
    "river", "rivers", "mountain", "mountains", "lake", "lakes", "desert",
    "deserts", "island", "islands", "border", "borders", "boundary",
    "boundaries", "latitude", "longitude", "coordinates", "region",
    "regions", "state", "states", "province", "provinces", "city", "cities",
    "population", "climate", "weather", "terrain", "elevation", "hemisphere",
    "atlas", "globe", "time zone", "timezone", "time zones", "country code",
    "flags", "flag", "coast", "coastline",
}


def _get_api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY")


def _get_model_name() -> str:
    return _normalize_model_name(os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))


def _normalize_model_name(model_name: str) -> str:
    if model_name.startswith("models/"):
        return model_name
    return f"models/{model_name}"


def _get_model_candidates() -> tuple[str, ...]:
    env_model = os.environ.get("GEMINI_MODEL")
    if env_model:
        # Try the env model first, but keep fallbacks to avoid hard failures.
        return tuple(_normalize_model_name(name) for name in ((env_model,) + (DEFAULT_MODEL,) + FALLBACK_MODELS))
    return tuple(_normalize_model_name(name) for name in ((DEFAULT_MODEL,) + FALLBACK_MODELS))


def _build_client() -> genai.Client:
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def _extract_text_from_response(response) -> Optional[str]:
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return None
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None)
        if not parts:
            continue
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text
    return None


def _is_rate_limited(exc: Exception) -> bool:
    message = str(exc).lower()
    return "rate" in message or "quota" in message or "429" in message


def _parse_geo_response(response_text: str) -> tuple[bool, str]:
    lines = [line.strip() for line in response_text.splitlines() if line.strip()]
    is_geo = False
    content = response_text.strip()
    for line in lines[:3]:
        if line.upper().startswith("GEO="):
            is_geo = line.upper().endswith("YES")
            break
    for line in lines:
        if line.upper().startswith("RESPONSE:"):
            content = line.split(":", 1)[1].strip()
            break
    return is_geo, content


def _normalize_query(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _is_geo_question(text: str) -> bool:
    normalized = _normalize_query(text)
    if not normalized:
        return False
    for keyword in _GEO_KEYWORDS:
        if keyword in normalized:
            return True
    return False


def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
    normalized_query = _normalize_query(user_text)
    cached = _RESPONSE_CACHE.get(normalized_query)
    if cached is not None:
        return cached

    if not _is_geo_question(user_text):
        if globals.number_conversants > 1:
            _RESPONSE_CACHE[normalized_query] = ""
            return ""
        response = "That question is not about geography."
        _RESPONSE_CACHE[normalized_query] = response
        return response

    try:
        client = _build_client()
    except RuntimeError:
        return (
            "GEMINI_API_KEY is not set. "
            "Set it in your environment and try again."
        )

    model_candidates = _get_model_candidates()
    logger.info("Gemini model candidates: %s", ", ".join(model_candidates))
    logger.info("Conversants count: %s", globals.number_conversants)

    last_error: Optional[Exception] = None
    last_model_name: Optional[str] = None

    response = None
    for model_name in model_candidates:
        last_model_name = model_name
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"{SYSTEM_PROMPT}\n\nUser: {user_text}\nAssistant:",
                config={"max_output_tokens": 128},
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini request failed for %s: %s", model_name, exc)
            response_headers = getattr(exc, "headers", None)
            if response_headers:
                try:
                    logger.info("Gemini response headers: %s", dict(response_headers))
                except Exception:
                    logger.info("Gemini response headers: %s", response_headers)
            if _is_rate_limited(exc):
                return "Rate limit reached. Please try again in one day."
            if "not found" in str(exc).lower() or "not supported" in str(exc).lower():
                continue
            break

    if last_error is not None:
        env_model = os.environ.get("GEMINI_MODEL")
        if env_model:
            return (
                "Gemini request failed for "
                f"GEMINI_MODEL={env_model} (last tried {last_model_name}): {last_error}"
            )
        return (
            "Gemini request failed for "
            f"{last_model_name}: {last_error}"
        )

    response_text = _extract_text_from_response(response)
    if not response_text:
        return "I did not get a response from Gemini."

    is_geo, content = _parse_geo_response(response_text)
    if not is_geo:
        if globals.number_conversants > 1:
            _RESPONSE_CACHE[normalized_query] = ""
            return ""
        response = "That question is not about geography."
        _RESPONSE_CACHE[normalized_query] = response
        return response

    final_response = content.strip()
    _RESPONSE_CACHE[normalized_query] = final_response
    return final_response


