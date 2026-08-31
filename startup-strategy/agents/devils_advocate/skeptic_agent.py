#!/usr/bin/env python3
"""
Devil's Advocate Agent — Startup Strategy Floor

Reads the full conversation history and challenges the analysis produced
by other agents. Pure LLM — no MCP data sources needed.

Port: 8206
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Devil's Advocate in a startup strategy review panel.
Your role is to challenge the analysis that other agents have produced.

You have heard the full conversation so far. Your job is to:

1. Identify the 3 most dangerous objections a skeptical VC would raise
   - For each: what's the underlying concern?
   - How strong is the counter-argument, if any?

2. Challenge the biggest assumptions in the analysis
   - Which assumption, if wrong, kills the business?
   - How likely is that assumption to be wrong?

3. Point out what was NOT said
   - What risks or challenges were glossed over?
   - What data is missing that would change the analysis?

4. Steelman the bearish case
   - Make the strongest possible argument AGAINST this startup succeeding

Be sharp and direct. Do not be polite about fatal flaws.
Your job is to prevent founders from walking into avoidable failure.
End with: "The most likely way this fails is: [one sentence]"
Do not use markdown formatting, bold text, headers, or bullet symbols. Write in plain prose only.
Keep the response focused; overall length is guided by a separate instruction."""


class SkepticAgent(BaseStrategyAgent):
    AGENT_NAME = "Devil's Advocate"
    AGENT_PORT = 8206
    AGENT_SYNOPSIS = "Challenges startup analysis and surfaces fatal flaws"
    AGENT_CAPABILITY_DETAIL = "Pressure-tests assumptions, identifies the strongest bearish objections, and highlights missing risks or data gaps."
    AGENT_KEYPHRASES = ["challenge", "devil", "skeptic", "critique", "flaw", "weakness",
                        "pushback", "counter", "objection", "bear case", "risks ignored"]

    def process_utterance(self, user_text: str) -> str:
        user_message = f"""Here is the startup concept and analysis produced so far:

{user_text}

Please challenge this analysis as a skeptical investor would.
Identify the fatal flaws, challenge the assumptions, and make the bear case."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = SkepticAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(SkepticAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
