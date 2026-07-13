#!/usr/bin/env python3
"""
Technical Feasibility Agent — Startup Strategy Floor

Evaluates feasibility and implementation risks for technology-heavy startup ideas.
Port: 8208
"""

import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Technical Feasibility specialist in a startup strategy team.
Your job is to assess whether the concept is technically buildable in 12-18 months.

Produce a concise technical feasibility review with:
1. Domain fit (chemistry, artificial intelligence, mechanical engineering, or other)
2. Core technical unknowns and failure modes
3. Build complexity (low/medium/high) with rationale
4. Critical dependencies (talent, tooling, data, suppliers, regulations)
5. A 90-day validation plan with concrete prototype tests

Be practical and specific. Avoid generic business advice.
Keep response to maximum 55 words."""


class TechnicalFeasibilityAgent(BaseStrategyAgent):
    AGENT_NAME = "Technical Feasibility"
    AGENT_PORT = 8208
    AGENT_SYNOPSIS = "Assesses technical feasibility by engineering domain and implementation risk"
    AGENT_CAPABILITY_DETAIL = "Evaluates technical unknowns, build complexity, dependencies, and prototype plan for technology-heavy concepts."
    AGENT_KEYPHRASES = [
        "technical feasibility", "engineering", "prototype", "implementation", "chemistry",
        "artificial intelligence", "mechanical engineering", "hardware", "manufacturing", "architecture"
    ]

    def process_utterance(self, user_text: str) -> str:
        tech_domain = self._extract_domain_hint(user_text)
        user_message = f"""Startup concept and routing context:
{user_text}

Technology specialization hint: {tech_domain}

Please provide a technical feasibility assessment focused on this domain."""
        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)

    def _extract_domain_hint(self, text: str) -> str:
        lowered = (text or "").lower()
        explicit = re.search(r"technology\s+(?:specialization|focus|domain)\s*[:\-]\s*(.+)", lowered)
        if explicit:
            return explicit.group(1).strip()

        if any(k in lowered for k in ["ai", "artificial intelligence", "machine learning", "llm", "neural", "computer vision"]):
            return "artificial intelligence"
        if any(k in lowered for k in ["chemistry", "chemical", "polymer", "catalyst", "formulation", "electrolyte"]):
            return "chemistry"
        if any(k in lowered for k in ["mechanical", "robotics", "gear", "motor", "actuator", "thermodynamic"]):
            return "mechanical engineering"
        return "general engineering"


def main() -> None:
    agent = TechnicalFeasibilityAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(TechnicalFeasibilityAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
