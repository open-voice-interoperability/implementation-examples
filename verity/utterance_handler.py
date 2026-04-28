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
    """Review user text for factuality and always return a valid dict."""
    default_response = {
        "applicable": "no",
        "decision": "unknown",
        "factual_likelihood": 0.5,
        "explanation": "Unable to evaluate this statement.",
        "suppress": False,
    }

    try:
        response_components = interactive_process(user_text)
        logger.info("interactive_process returned: %s", response_components)

        if response_components is None or not isinstance(response_components, str) or not response_components.strip():
            logger.error("interactive_process returned invalid response")
            return default_response

        response_dict = ast.literal_eval(response_components)
        if not isinstance(response_dict, dict):
            logger.error("Parsed response is not a dict: %s", type(response_dict))
            return default_response

        response_dict.setdefault("applicable", "no")
        response_dict.setdefault("decision", "unknown")
        response_dict.setdefault("factual_likelihood", 0.5)
        response_dict.setdefault("explanation", "")
        response_dict["suppress"] = _should_suppress_response(response_dict)
        return response_dict

    except (ValueError, SyntaxError) as e:
        logger.error("Failed to parse response as dict: %s", e)
        return default_response
    except Exception as e:
        logger.exception("Unexpected error in review_utterance: %s", e)
        return default_response


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
