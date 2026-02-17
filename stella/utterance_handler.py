#!/usr/bin/env python3
"""
Utterance Handler - Stella

Custom conversation logic for the Stella space assistant.
"""

import json
import os
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from openai import OpenAI
import generate_nasa_gallery
import nasa_api
import globals

conversation_state = {}

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "assistant_config.json")
with open(_CONFIG_PATH, "r", encoding="utf-8") as file:
    agent_config = json.load(file)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

_IMAGE_KEYWORDS = {
    "image", "images", "picture", "pictures", "photo", "photos", "gallery",
}
_SPACE_KEYWORDS = {
    "nasa", "space", "astronomy", "planet", "planets", "mars", "venus",
    "jupiter", "saturn", "mercury", "neptune", "uranus", "pluto", "moon",
    "sun", "galaxy", "nebula", "comet", "asteroid", "telescope",
}


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
    message_history = [
        {"role": "system", "content": agent_config.get("personalPrompt", "")},
        {"role": "system", "content": agent_config.get("functionPrompt", "")},
    ]

    if "messages" in conversation_state:
        message_history.extend(conversation_state["messages"])

    message_history.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=agent_config.get("model", "gpt-4o-mini"),
        messages=message_history,
        max_tokens=200,
        temperature=0.7,
    )

    if response and response.choices:
        message = response.choices[0].message
        if hasattr(message, "content"):
            assistant_reply = (message.content or "").strip()
        elif isinstance(message, dict):
            assistant_reply = str(message.get("content", "")).strip()
        else:
            assistant_reply = str(message).strip()
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
    lowered = text.lower().strip()
    for prefix in ("pictures of ", "picture of ", "images of ", "image of ", "photos of ", "photo of "):
        if lowered.startswith(prefix):
            return lowered[len(prefix):].strip() or lowered
    return lowered


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
