#!/usr/bin/env python3
"""
Utterance Handler - Verity's conversation logic.
"""

import ast
import logging
from agentic_hallucination import interactive_process

logger = logging.getLogger(__name__)


def review_utterance(user_text: str) -> dict:
    response_components = interactive_process(user_text)
    logger.info("generated %s.", response_components)
    response_dict = ast.literal_eval(response_components)
    return response_dict
