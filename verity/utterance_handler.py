#!/usr/bin/env python3
"""
Utterance Handler - Verity's conversation logic.
"""

import ast
import logging
from agentic_hallucination import interactive_process
import globals

logger = logging.getLogger(__name__)


def review_utterance(user_text: str) -> dict:
    response_components = interactive_process(user_text)
    logger.info("generated %s.", response_components)
    response_dict = ast.literal_eval(response_components)
    response_dict["suppress"] = _should_suppress_response(response_dict)
    return response_dict


def _should_suppress_response(response_dict: dict) -> bool:
    if globals.number_conversants <= 1:
        return False

    applicable = str(response_dict.get("applicable", "")).strip().lower()
    decision = str(response_dict.get("decision", "")).strip().lower()

    # Always respond to non-factual determinations.
    if "not factual" in decision or "non-factual" in decision or decision == "false":
        return False

    # Suppress if factuality does not apply or the statement is factual.
    if applicable == "no":
        return True
    if decision == "factual":
        return True

    return False
