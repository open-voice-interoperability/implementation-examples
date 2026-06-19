#!/usr/bin/env python3
"""
Strategy Synthesizer Agent — Startup Strategy Floor

Reads the full conversation — all prior agent outputs — and produces
a coherent 1-page strategy brief with prioritized next actions.
Pure LLM — no MCP data sources.

Port: 8207
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Strategy Synthesizer on a startup advisory panel.
You have heard analysis from market, competitive, business model, risk, funding,
workforce, and devil's advocate agents.

Your job is to synthesize all of this into a clear, actionable 1-page strategy brief.

Format your output as:

## Startup Strategy Brief

**Concept:** [one sentence description]

**Verdict:** Go / Conditional Go / No-Go
[2-3 sentences explaining the verdict]

**Market Opportunity**
[2-3 bullet points: size, timing, key driver]

**Recommended Business Model**
[1-2 sentences: what model, why]

**Top 3 Risks to Mitigate**
1. [Risk + mitigation]
2. [Risk + mitigation]
3. [Risk + mitigation]

**Funding Path**
[Stage, amount, key milestone to hit before raising]

**First 90 Days: Priority Actions**
1. [Most important thing to do first]
2. [Second priority]
3. [Third priority]

**The One Thing That Makes or Breaks This**
[One sentence: the single most important variable]

Be direct and specific. Founders should be able to act on this immediately.
Keep response to maximum 50 words."""


class StrategyAgent(BaseStrategyAgent):
    AGENT_NAME = "Strategy Synthesizer"
    AGENT_PORT = 8207
    AGENT_SYNOPSIS = "Synthesizes all analysis into a clear startup strategy brief"
    AGENT_CAPABILITY_DETAIL = "Combines prior agent outputs into a concise verdict, priority risks, funding path, and immediate action plan."
    AGENT_KEYPHRASES = ["summary", "synthesize", "brief", "strategy", "recommendation",
                        "conclusion", "verdict", "next steps", "action plan", "overall"]

    def process_utterance(self, user_text: str) -> str:
        user_message = f"""Here is the full analysis from the advisory panel:

{user_text}

Please synthesize this into a clear 1-page startup strategy brief with a verdict
and prioritized action plan."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = StrategyAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(StrategyAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
