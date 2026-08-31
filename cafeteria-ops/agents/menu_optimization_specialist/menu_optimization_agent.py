#!/usr/bin/env python3
"""
Menu Optimization Specialist Agent — Cafeteria Ops Floor

Optimizes the menu mix across a planning period for cost, variety, and
waste reduction. Pure LLM -- no MCP data sources needed. Remembers the
Menu Designer's proposed menu (broadcast to it via Pass-Through, see
on_observed_utterance below) so it evaluates the ACTUAL proposed menu
rather than the raw planning request text it happens to be asked with
(e.g. "Plan a five-day lunch menu for 300 people..." is the REQUEST, not
a menu -- confirmed live this was being evaluated as if it were one).

Port: 8304
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

# Hardcoded to match agents/menu_designer/menu_designer_agent.py's own
# AGENT_PORT -- cafeteria-ops agents use serviceUrl == speakerUri ==
# "http://127.0.0.1:<port>/" throughout, and each agent file is
# self-contained (no cross-agent imports), so this is kept in sync by hand
# like every other agent's port number in this project.
_MENU_DESIGNER_SERVICE_URL = "http://127.0.0.1:8301/"

SYSTEM_PROMPT = """You are the Menu Optimization Specialist for a corporate cafeteria planning panel.
Your job is to evaluate a proposed menu or menu mix and recommend concrete
improvements for cost efficiency, ingredient reuse, and waste reduction
across the planning period (not just one day in isolation).

Cover: where ingredients can be shared across multiple menu items to reduce
waste and simplify prep, where a lower-cost substitution wouldn't meaningfully
hurt the diner experience, and where the current mix over- or under-serves
variety (too much repetition of a protein/cuisine, or so much variety that
prep complexity spikes).

Ground your recommendations in the specific menu described -- don't give
generic cost-cutting advice that would apply to any cafeteria. Two different
menus should get different, specific optimization recommendations.

Be concrete and specific. Write in plain prose only -- no markdown, bold,
or bullet characters, no numbered-list markers -- just plain text. Keep
the response focused; overall length is guided by a separate instruction."""


class MenuOptimizationAgent(BaseStrategyAgent):
    AGENT_NAME = "Menu Optimization Specialist"
    AGENT_PORT = 8304
    AGENT_SYNOPSIS = "Optimizes the menu mix for cost, variety, and waste reduction"
    AGENT_CAPABILITY_DETAIL = "Evaluates a proposed menu across a planning period and recommends concrete cost, ingredient-reuse, and waste-reduction improvements."
    AGENT_KEYPHRASES = ["optimize", "optimization", "cost", "waste", "efficiency",
                         "ingredient reuse", "variety", "menu mix", "budget"]

    def __init__(self):
        super().__init__()
        # conv_id -> the Menu Designer's last proposed-menu text observed in
        # that conversation (see on_observed_utterance). Scoped per
        # conversation so an older, unrelated conversation's menu can never
        # leak into a new one against the same running agent process.
        self._observed_menus: dict[str, str] = {}

    def on_observed_utterance(self, conv_id: str, speaker_uri: str, text: str) -> None:
        if self._normalize_endpoint_id(speaker_uri) == self._normalize_endpoint_id(_MENU_DESIGNER_SERVICE_URL):
            self._observed_menus[conv_id] = text
            logger.info("[MenuOptimization] Saved Menu Designer's proposed menu for conv %s", conv_id)

    def process_utterance(self, user_text: str) -> dict:
        saved_menu = self._observed_menus.get(self._current_conv_id, "")
        if saved_menu:
            # The saved menu IS the thing to evaluate -- the current
            # question routed here in the same round is typically just the
            # same original planning request (headcount/budget/day-count),
            # not a menu itself, so it's dropped in favor of the real one.
            user_message = f"""{self._history_block()}The menu as proposed by the Menu Designer:
{saved_menu}

Please evaluate this and recommend concrete cost/variety/waste-reduction improvements."""
        else:
            user_message = f"""{self._history_block()}Proposed menu or menu mix: {user_text}

Please evaluate this and recommend concrete cost/variety/waste-reduction improvements."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        # This agent's response is normally one holistic paragraph, not a
        # per-item list -- _text_to_html_intro_and_list correctly returns
        # "" for that (< 2 lines). On the rarer occasion the model breaks
        # its recommendations into an opening framing sentence followed by
        # itemized specifics, that opening sentence is kept as plain intro
        # text rather than bulleted alongside the specifics below it
        # (confirmed live it was landing as just one more <li>).
        return {"text": text, "html": self._text_to_html_intro_and_list(text)}


def main() -> None:
    agent = MenuOptimizationAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(MenuOptimizationAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
