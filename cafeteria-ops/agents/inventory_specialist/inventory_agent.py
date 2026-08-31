#!/usr/bin/env python3
"""
Inventory Specialist Agent — Cafeteria Ops Floor

Reasons about stock levels, par levels, and stockout/overstock risk for
cafeteria ingredients. Pure LLM -- no MCP data sources needed (live
inventory is inherently internal/private data this prototype doesn't
assume access to). Grounded in the real menu/ingredients already
discussed via self._history_block() (BaseStrategyAgent's automatic
full-conversation transcript, see base_strategy_agent.py) rather than
just the raw request -- without it, this agent has no ingredient/shelf-
life specifics to reason about beyond generic examples, which live
testing showed produces vague, one-size-fits-all advice ("plan for 5-7
days' worth of fresh produce...") regardless of what was actually asked.

Port: 8305
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Inventory Specialist for a corporate cafeteria operations panel.
Your job is to reason about stock levels for the ingredients or situation
described and flag stockout or overstock risk.

Cover: a reasonable par level (minimum stock to reorder at) for the
ingredient(s) given typical cafeteria usage and shelf life, lead-time risk
if reordering is delayed, and whether the described situation points toward
under-stocking (risk of running out mid-service) or over-stocking (risk of
spoilage/waste).

Ground your reasoning in the specific ingredient(s), shelf life, and usage
pattern described -- perishables (fresh produce, dairy) need tighter par
levels and more frequent counts than shelf-stable goods (dry grains, canned
goods). Don't give the same generic inventory advice regardless of what was
asked. If a prior conversation is included below, ground your assessment in
the ACTUAL dishes/ingredients other specialists already named there (e.g.
Menu Designer's proposed dishes, Recipe & Portion's ingredient amounts) --
naming those specific ingredients beats generic categories like "fresh
produce" whenever real ones are available.

Be concrete and specific. Write in plain prose only -- no markdown, bold,
or bullet characters, no numbered-list markers -- just plain text. Keep
the response focused; overall length is guided by a separate instruction."""


class InventoryAgent(BaseStrategyAgent):
    AGENT_NAME = "Inventory Specialist"
    AGENT_PORT = 8305
    AGENT_SYNOPSIS = "Reasons about stock levels, par levels, and stockout/overstock risk"
    AGENT_CAPABILITY_DETAIL = "Evaluates par levels, reorder timing, and stockout/overstock risk for cafeteria ingredients."
    AGENT_KEYPHRASES = ["inventory", "stock", "stockout", "par level", "overstock",
                         "reorder", "shelf life", "spoilage", "count"]

    def process_utterance(self, user_text: str) -> dict:
        user_message = f"""{self._history_block()}Inventory situation: {user_text}

Please assess stock/par-level risk for this situation."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        # This agent's response is normally one holistic paragraph, not a
        # per-item list -- _text_to_html_intro_and_list correctly returns
        # "" for that (< 2 lines). On the rarer occasion the model breaks
        # its assessment into an opening framing sentence followed by
        # itemized per-ingredient specifics, that opening sentence is kept
        # as plain intro text rather than bulleted alongside the specifics
        # below it (confirmed live it was landing as just one more <li>).
        return {"text": text, "html": self._text_to_html_intro_and_list(text)}


def main() -> None:
    agent = InventoryAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(InventoryAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
