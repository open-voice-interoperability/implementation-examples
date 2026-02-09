#!/usr/bin/env python3
"""
Gemini utterance handler.

Accepts plain text and returns plain text. All OpenFloor event handling is in
template_agent.py.
"""

import os
from typing import Optional

import google.generativeai as genai

DEFAULT_MODEL = "gemini-1.5-flash"
SYSTEM_PROMPT = (
    "You are a helpful geography assistant. "
    "Answer clearly and concisely. "
    "If a question is not about geography, give a brief reply and offer to help with geography questions."
)


def _get_api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY")


def _get_model_name() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
    api_key = _get_api_key()
    if not api_key:
        return (
            "GEMINI_API_KEY is not set. "
            "Set it in your environment and try again."
        )

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(_get_model_name())

    prompt = f"{SYSTEM_PROMPT}\n\nUser: {user_text}\nAssistant:"

    try:
        response = model.generate_content(prompt)
    except Exception as exc:
        return f"Gemini request failed: {exc}"

    if not response or not getattr(response, "text", None):
        return "I did not get a response from Gemini."

    return response.text.strip()
