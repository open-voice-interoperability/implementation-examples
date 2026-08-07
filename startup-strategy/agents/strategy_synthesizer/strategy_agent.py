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

Cover: concept in one sentence, verdict (Go / Conditional Go / No-Go) with brief reasoning, market opportunity, recommended business model, top 3 risks with mitigations, funding path, first 90 days priority actions, and the single most important variable.

Be direct and specific. Founders should be able to act on this immediately.
Do not use markdown formatting, bold text, headers, or bullet symbols. Write in plain prose only.
Keep the response focused; overall length is guided by a separate instruction."""


class StrategyAgent(BaseStrategyAgent):
    AGENT_NAME = "Strategy Synthesizer"
    AGENT_PORT = 8207
    AGENT_SYNOPSIS = "Synthesizes all analysis into a clear startup strategy brief"
    AGENT_CAPABILITY_DETAIL = "Combines prior agent outputs into a concise verdict, priority risks, funding path, and immediate action plan."
    AGENT_KEYPHRASES = ["summary", "synthesize", "brief", "strategy", "recommendation",
                        "conclusion", "verdict", "next steps", "action plan", "overall"]

    def process_utterance(self, user_text: str) -> dict | str:
        user_message = f"""Here is the full analysis from the advisory panel:

{user_text}

Please synthesize this into a clear 1-page startup strategy brief with a verdict
and prioritized action plan."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)

        # Extract the concept description for image generation (first ~150 chars of user_text
        # before any agent analysis headers start).
        concept_line = user_text.split("\n")[0].replace("Startup concept:", "").strip()
        image_prompt = (
            f"A professional, vibrant business concept illustration for: {concept_line[:200]}. "
            "Clean modern vector art style, no text overlays, warm colors, isometric or flat design."
        )
        image_uri = llm_utils.generate_image_sync(image_prompt, size="1024x1024")

        if image_uri:
            html = (
                f"<div style='text-align:center;padding:8px 0'>"
                f"<img src='{image_uri}' alt='Concept illustration' "
                f"style='max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.15)'/>"
                f"</div>"
            )
            return {"text": text, "html": html}

        return text


def main() -> None:
    agent = StrategyAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(StrategyAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
