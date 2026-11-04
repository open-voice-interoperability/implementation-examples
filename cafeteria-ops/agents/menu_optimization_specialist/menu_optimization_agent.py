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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

# This agent retrieves and formats data (USDA / TheMealDB lookups, portion
# arithmetic) rather than doing open-ended creative work, so every LLM call
# here runs on the smaller, cheaper "lookup" model tier. Only the Menu
# Designer keeps the full analysis model. See llm_utils.LOOKUP_* / .env.
_LOOKUP = {"ollama_model": llm_utils.LOOKUP_OLLAMA_MODEL, "openai_model": llm_utils.LOOKUP_LLM_MODEL}

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

IMPORTANT: this system has NO data on dish popularity, sales, uptake, diner
ratings or preferences, or historical waste volumes -- you have only the
menu itself. Never invent such figures, and never rank or compare dishes by
"popularity", "how well they sell", or "how much was actually wasted".

If a request CANNOT be answered without data you don't have (e.g. "worst
cost-to-popularity ratio", "rank the dishes by popularity", "which dish was
wasted most last week"), DECLINE it: reply with one or two sentences saying
this system has no popularity, sales, or waste-history data and so the
question can't be answered -- then STOP. Do not substitute a generic
cost/variety/waste review that was not asked for. Only if the same request
ALSO contains a part that is genuinely answerable from the menu (e.g. "...
and which dishes are most expensive per serving") do you answer that part,
after noting what you can't.

Be concrete and specific. Write in plain prose only -- no markdown, bold,
or bullet characters, no numbered-list markers -- just plain text. Keep
the response focused; overall length is guided by a separate instruction."""

# A question whose core metric depends on data this system does not have
# (dish popularity/sales/uptake, or historical waste volumes) is declined
# BEFORE any LLM call -- confirmed live that qwen2.5:7b, even instructed to
# decline and stop, still pads the decline with an unrequested generic
# review. Substring match on the raw utterance, deliberately broad: over-
# declining a borderline "make it more popular" is acceptable, silently
# fabricating popularity/sales/waste numbers is not.
_MISSING_DATA_MARKERS = (
    "popular", "cost-to-popularity", "cost to popularity",
    "best seller", "best-seller", "bestseller", "top seller", "top-seller",
    "sales figure", "sales data", "sales number", "sell", "uptake",
    "take rate", "take-rate",
    "how much was wasted", "how much is wasted", "wasted last", "waste last week",
    "actual waste", "waste history", "waste volume", "historical waste",
    "diner rating", "diner preference", "customer favorite", "customer favourite",
)
_MISSING_DATA_DECLINE = (
    "I don't have data about dish popularity, sales, uptake, diner ratings, or "
    "historical waste volumes -- only the proposed menu -- so I can't answer that."
)


def _needs_unavailable_data(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    return any(marker in lowered for marker in _MISSING_DATA_MARKERS)


class MenuOptimizationAgent(BaseStrategyAgent):
    AGENT_NAME = "Menu Optimization Specialist"
    AGENT_PORT = 8304
    AGENT_SYNOPSIS = "Optimizes the menu mix for cost, variety, and waste reduction"
    AGENT_CAPABILITY_DETAIL = "Evaluates a proposed menu across a planning period and recommends concrete cost, ingredient-reuse, and waste-reduction improvements."
    WORKING_LABEL = "reviewing the menu for cost and waste"
    AGENT_KEYPHRASES = ["optimize", "optimization", "cost", "waste", "efficiency",
                         "ingredient reuse", "variety", "menu mix", "budget"]
    # BaseStrategyAgent's default of 50 words is a single-item budget. This
    # agent reviews a whole planning period -- when a client sends no
    # maxWords feature (e.g. the test harness), 50 words hard-truncates the
    # review mid-sentence (see BaseStrategyAgent._limit_words). 300 matches
    # the other whole-menu specialists (Nutrition, Procurement); a client
    # that does send maxWords (the web UI slider) still overrides this.
    MAX_RESPONSE_WORDS = 300

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
        if _needs_unavailable_data(user_text):
            logger.info("[MenuOptimization] Declining -- question needs popularity/sales/waste data this system lacks")
            return {"text": _MISSING_DATA_DECLINE, "html": ""}

        saved_menu = self._observed_menus.get(self._current_conv_id, "")
        if saved_menu:
            # The saved menu is the subject to evaluate; the utterance
            # routed here in the same round is OFTEN just the original
            # planning request (headcount/budget/day-count), not a menu --
            # but it can also be a pointed question ("worst cost-to-
            # popularity ratio", "where is ingredient reuse weakest"), so
            # carry it through and let the model tell the two apart rather
            # than dropping it and always giving a generic review.
            user_message = f"""{self._history_block()}The menu to evaluate, as proposed by the Menu Designer:
{saved_menu}

What was asked: {user_text}

If "what was asked" is a specific question, answer only that question about
the menu above -- or, per the IMPORTANT note in your instructions, decline
it if it needs data this system does not have -- and do NOT add a broader
review that was not requested. Only if "what was asked" is a generic
planning request with no specific question in it, give a full
cost/variety/waste-reduction review of the menu."""
        else:
            user_message = f"""{self._history_block()}Proposed menu or menu mix: {user_text}

Please evaluate this and recommend concrete cost/variety/waste-reduction improvements."""

        # Hand the model an explicit length target and steer it away from a
        # dish-by-dish walk -- without this the LLM tends to start an entry
        # per dish and get hard-truncated mid-list (see
        # BaseStrategyAgent._limit_words). Same "give it the number, not
        # just 'be concise'" fix as the other whole-menu agents' per-item
        # budget hints.
        user_message += (
            f"\n\nKeep the entire response within about {self._current_max_words} words. "
            "Do not go through the menu dish by dish -- give a consolidated review of the "
            "two to four highest-impact cost, ingredient-reuse, and waste opportunities "
            "across the planning period, and finish every point you start rather than "
            "beginning a per-dish list you cannot complete in that space."
        )

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, **_LOOKUP)
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
