#!/usr/bin/env python3
"""
Utterance Handler - Stella

Custom conversation logic for the Stella space assistant.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from openai import OpenAI
import generate_nasa_gallery
import nasa_api
import globals

conversation_state = {}
logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "assistant_config.json")
with open(_CONFIG_PATH, "r", encoding="utf-8") as file:
    agent_config = json.load(file)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", agent_config.get("model", "gpt-4o-mini"))
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
SHOW_LLM_PROVIDER = os.environ.get("SHOW_LLM_PROVIDER", "false").strip().lower() in {"1", "true", "yes", "on"}

_IMAGE_KEYWORDS = {
    "image", "images", "picture", "pictures", "photo", "photos", "gallery",
}
_SPACE_KEYWORDS = {
    "nasa", "space", "astronomy", "planet", "planets", "mars", "venus",
    "jupiter", "saturn", "mercury", "neptune", "uranus", "pluto", "moon",
    "sun", "galaxy", "nebula", "comet", "asteroid", "telescope",
}
_last_llm_provider = ""
_last_llm_model = ""


def _ollama_base_url() -> str:
    base_url = OLLAMA_HOST.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _llm_targets() -> List[tuple[str, OpenAI, str]]:
    targets: List[tuple[str, OpenAI, str]] = []
    openai_api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    if LLM_PROVIDER in {"auto", "ollama"}:
        targets.append(
            (
                "ollama",
                OpenAI(
                    base_url=_ollama_base_url(),
                    api_key=(os.environ.get("OLLAMA_API_KEY") or "ollama"),
                ),
                OLLAMA_MODEL,
            )
        )

    if openai_api_key and LLM_PROVIDER in {"auto", "openai", "ollama"}:
        targets.append(("openai", OpenAI(api_key=openai_api_key), OPENAI_MODEL))

    return targets


def _build_client() -> OpenAI | None:
    targets = _llm_targets()
    return targets[0][1] if targets else None


def _provider_label() -> str:
    if SHOW_LLM_PROVIDER and _last_llm_provider:
        return f"[{_last_llm_provider}:{_last_llm_model}] "
    return ""


def _create_chat_completion(messages: List[Dict[str, str]], **kwargs):
    global _last_llm_provider, _last_llm_model
    last_error = None
    query_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            query_text = (message.get("content") or "").replace("\n", " ").strip()
            break

    for provider, llm_client, model in _llm_targets():
        try:
            response = llm_client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs,
            )
            _last_llm_provider = provider
            _last_llm_model = model
            logger.info(
                "LLM provider=%s model=%s query=%s",
                provider,
                model,
                query_text[:120],
            )
            return response
        except Exception as exc:
            last_error = exc
            logger.warning("%s request failed: %s", provider, exc)

    if last_error is not None:
        logger.warning("No LLM provider succeeded: %s", last_error)
    return None


def _search_intent(input_text: str) -> Optional[List[Dict[str, object]]]:
    json_file_path = os.path.join(os.path.dirname(__file__), "intentConcepts.json")
    with open(json_file_path, "r", encoding="utf-8") as f:
        concepts_data = json.load(f)

    matched_intents = []
    input_text_lower = input_text.lower()

    if "astronomy" in input_text_lower or "space" in input_text_lower:
        matched_intents.append({"intent": "nasa"})

    for concept in concepts_data.get("concepts", []):
        matched_words = [word for word in concept.get("examples", []) if word in input_text_lower]
        if matched_words:
            matched_intents.append({"intent": concept.get("name", ""), "matched_words": matched_words})

    return matched_intents if matched_intents else None


def _generate_openai_response(prompt: str) -> str:
    if _build_client() is None:
        return (
            "I can answer NASA and space-image requests right now, but neither Ollama nor "
            "OPENAI_API_KEY is available for general LLM responses."
        )

    message_history = [
        {"role": "system", "content": agent_config.get("personalPrompt", "")},
        {"role": "system", "content": agent_config.get("functionPrompt", "")},
    ]

    if "messages" in conversation_state:
        message_history.extend(conversation_state["messages"])

    message_history.append({"role": "user", "content": prompt})

    response = _create_chat_completion(
        messages=message_history,
        max_tokens=200,
        temperature=0.0,
    )

    if response is None:
        return (
            "I can answer NASA and space-image requests right now, but no configured LLM provider "
            "is currently responding."
        )

    if response and response.choices:
        message = response.choices[0].message
        if hasattr(message, "content"):
            assistant_reply = (message.content or "").strip()
        elif isinstance(message, dict):
            assistant_reply = str(message.get("content", "")).strip()
        else:
            assistant_reply = str(message).strip()
        assistant_reply = f"{_provider_label()}{assistant_reply}" if assistant_reply else assistant_reply
        conversation_state.setdefault("messages", []).append({"role": "user", "content": prompt})
        conversation_state["messages"].append({"role": "assistant", "content": assistant_reply})
        return assistant_reply

    return "Error: No valid response received."


def _is_nasa_image_request(text: str) -> bool:
    lowered = text.lower()
    if any(keyword in lowered for keyword in _IMAGE_KEYWORDS):
        return True
    if "nasa" in lowered and ("image" in lowered or "photo" in lowered or "picture" in lowered):
        return True
    if any(keyword in lowered for keyword in _SPACE_KEYWORDS) and any(
        kw in lowered for kw in _IMAGE_KEYWORDS
    ):
        return True
    return False


def _is_space_question(text: str) -> bool:
    lowered = text.lower()
    if "astronomy" in lowered or "space" in lowered:
        return True
    return any(keyword in lowered for keyword in _SPACE_KEYWORDS)


def _extract_nasa_search_query(text: str) -> str:
    query = re.sub(r"\s+", " ", text.lower().strip())
    query = re.sub(r"[.!?]+$", "", query).strip()

    # Remove common conversational lead-ins repeatedly until stable.
    lead_ins = [
        r"^(please\s+)?(?:can|could|would|will)\s+you\s+",
        r"^(please\s+)?(?:show|find|get|give)\s+me\s+",
        r"^i\s+(?:want|need|would\s+like)\s+(?:to\s+see\s+)?",
        r"^do\s+you\s+have\s+",
        r"^let\s+me\s+see\s+",
    ]
    previous = None
    while previous != query:
        previous = query
        for pattern in lead_ins:
            query = re.sub(pattern, "", query).strip()

    # Remove image-request scaffolding and articles to keep the core topic.
    query = re.sub(r"^(?:nasa\s+)?(?:pictures?|images?|photos?)\s+of\s+", "", query).strip()
    query = re.sub(r"^(?:a|an|the|some)\s+", "", query).strip()
    query = re.sub(r"^(?:pictures?|images?|photos?)\s+", "", query).strip()

    return query or text.lower().strip()


def _format_nasa_search_results(nasa_data: dict) -> str:
    try:
        collection = nasa_data.get("collection", {})
        items = collection.get("items", [])
        if not items:
            return "I couldn't find any NASA images for that query."

        html_gallery = generate_nasa_gallery.generate_gallery_html_from_json_obj(
            nasa_data,
            title="NASA Image Results",
            max_items=10,
            compact=False,
        )
        return html_gallery
    except Exception:
        return "I couldn't format the NASA image results."


def _handle_nasa_image_search(user_text: str) -> str:
    query = _extract_nasa_search_query(user_text)
    if not query:
        return "What NASA images are you looking for?"
    api_url = f"https://images-api.nasa.gov/search?q={quote_plus(query)}&media_type=image"
    try:
        nasa_data = nasa_api.get_nasa(api_url)
    except Exception:
        return "I couldn't reach the NASA image service right now."
    return _format_nasa_search_results(nasa_data)


def process_utterance(user_text: str, agent_name: str = "Stella") -> str:
    if globals.number_conversants > 1 and not _is_space_question(user_text):
        return ""

    if _is_nasa_image_request(user_text):
        return _handle_nasa_image_search(user_text)

    detected_intents = _search_intent(user_text) or []

    if detected_intents:
        for intent in detected_intents:
            if intent.get("intent") == "nasa":
                nasa_data = nasa_api.get_nasa()
                explanation, picture_url = nasa_api.parse_nasa_data(nasa_data)
                return (
                    f"Today's astronomy picture can be found at: {picture_url}. "
                    f"Here's an explanation {explanation}"
                )

    return _generate_openai_response(user_text)
