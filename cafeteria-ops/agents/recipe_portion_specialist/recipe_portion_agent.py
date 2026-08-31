#!/usr/bin/env python3
"""
Recipe & Portion Specialist Agent — Cafeteria Ops Floor

Finds real recipe ideas (TheMealDB) and grounds portion/serving guidance
in real ingredient nutrient data (USDA FoodData Central). Also remembers
the Menu Designer's proposed weekly menu (broadcast to it via Pass-Through,
see on_observed_utterance below) so it can be asked to work out recipes and
amounts for that WHOLE menu, not just one dish at a time.

Port: 8303
"""

import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

# Hardcoded to match agents/menu_designer/menu_designer_agent.py's own
# AGENT_PORT -- cafeteria-ops agents use serviceUrl == speakerUri ==
# "http://127.0.0.1:<port>/" throughout (confirmed via live testing), and
# each agent file is self-contained (no cross-agent imports), so this is
# kept in sync by hand like every other agent's port number in this project.
_MENU_DESIGNER_SERVICE_URL = "http://127.0.0.1:8301/"

# TheMealDB's search matches meal names, not free text -- a raw utterance
# like "Recipe Specialist, give me a recipe for chicken curry" returns zero
# results even though "chicken curry" alone would match real recipes
# (confirmed via live testing). Strip the address prefix a direct question
# arrives with, plus common request framing, to raise the odds of a real hit
# without adding another LLM round-trip just to extract a search term.
#
# The maxWords slider's instruction, appended by convener._question_text
# whenever the UI's maxWords != the no-instruction default -- present on
# almost every real request, so it must be stripped before judging what
# dish (if any) the ORIGINAL question names.
_MAX_WORDS_INSTRUCTION = re.compile(r"\n\n\[Write approximately[\s\S]*$", re.IGNORECASE)
_ADDRESS_PREFIX = re.compile(r"^[^,]{0,40},\s*", re.IGNORECASE)
_REQUEST_FRAMING = re.compile(
    r"\b(give me|show me|find|i want|i'd like|can you (make|find|get)|"
    r"how (do i|to) make|what'?s a good recipe for|recipe for|a recipe for)\b",
    re.IGNORECASE,
)
# Signals a broad planning question (a whole menu/week/budget), not a
# lookup for one specific dish -- e.g. "plan a five-day lunch menu for 450
# people ... itemized costs ... budget of $7.00 per meal" names no dish at
# all, so searching TheMealDB/FDC with that whole sentence either finds
# nothing (TheMealDB matches meal names) or, for FDC's fuzzy search,
# something unrelated but superficially keyword-matched.
_BROAD_PLANNING_SIGNAL = re.compile(
    r"\b(five-day|\d+[- ]day|weekly|week'?s|itemized|budget|per meal|menu for|lunch menu|meal plan)\b",
    re.IGNORECASE,
)

_DISH_EXTRACTION_SYSTEM_PROMPT = """Extract the distinct dish names from a cafeteria menu.

Identify every distinct DISH (a specific food item someone would cook -- e.g.
"Grilled Chicken Caesar Salad"). Ignore day labels ("Day 1:") and anything
that isn't an actual dish name.

Respond with ONLY a single JSON object and no other text:
{"dishes": ["<dish name>", ...]}
"""

SYSTEM_PROMPT = """You are the Recipe & Portion Specialist for a corporate cafeteria planning panel.
Your job is to turn a menu idea -- or a whole week's finalized menu -- into
concrete recipe(s) with portion guidance for exactly ONE SERVING: real
ingredient amounts needed to prepare a SINGLE serving of each dish, not a
batch and not scaled to any headcount. The Nutrition Specialist runs right
after you and computes per-serving nutrition from the amounts you give here,
so they must genuinely be for one serving.

You have access to real recipe data (ingredients + instructions) and, where
available, nutrient data for specific ingredients. Ground your recipe(s) in
the retrieved ingredient list and instructions rather than inventing one
from scratch when real recipe data was found -- retrieved recipe data is
often written for several servings, so scale it DOWN to one serving rather
than reporting it as retrieved.

If given ONE dish, cover: the ingredient list for a single serving (specific
weights/volumes per ingredient, e.g. "150g chicken breast", not just "1
serving"), a brief summary of preparation steps, and a recommended plate
serving size (weight or volume).

If given a WHOLE WEEK'S menu (multiple dishes), do the same for EVERY dish
-- one compact entry per dish (dish name, key one-serving ingredient
amounts, a one-line prep summary, plate serving size), covering every dish
before adding extra depth to any single one. Put each dish on its OWN LINE
(a real line break between one dish's entry and the next, not run together
in one paragraph). Do not silently drop a dish that has no retrieved data
-- name it and say so plainly instead.

If no matching recipe data was retrieved for a dish, say so plainly and give
your best LLM-derived recipe instead -- don't imply you found real data when
you didn't.

Derive specifics from the actual dish(es) named, not a generic template.
Write in plain prose only -- no markdown, bold, or bullet characters, no
numbered-list markers -- just plain text lines. Keep the response focused;
overall length is guided by a separate instruction."""


def _dish_query(user_text: str) -> str | None:
    cleaned = _MAX_WORDS_INSTRUCTION.sub("", user_text)
    cleaned = _ADDRESS_PREFIX.sub("", cleaned, count=1)
    cleaned = _REQUEST_FRAMING.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!")
    if not cleaned or _BROAD_PLANNING_SIGNAL.search(cleaned):
        return None
    if len(cleaned.split()) > 8:
        return None
    return cleaned


def _extract_dishes(menu_text: str) -> list[str]:
    """LLM-based extraction of distinct dish names from a proposed menu.
    Free text like "Day 1: X, Day 2: Y, ..." has an unknown number of
    dishes mixed with day labels and operational notes -- the same problem
    (and the same fix) as the Shopping List Specialist's own menu
    extraction, kept as a separate local copy since each cafeteria-ops
    agent is self-contained."""
    raw = llm_utils.chat_sync(_DISH_EXTRACTION_SYSTEM_PROMPT, menu_text, temperature=0, timeout=15)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [d.strip() for d in (parsed.get("dishes") or []) if isinstance(d, str) and d.strip()]


def _non_empty_results(raw: str | None) -> str | None:
    """MCP search tools always return a JSON string, even for zero matches
    (e.g. {"results": []}) -- that string is truthy, so a plain `or`
    fallback never actually triggers on a real "nothing found" case. Parse
    and treat an empty results list as no data, same as a failed call."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict) and "results" in parsed and not parsed["results"]:
        return None
    return raw


def _fetch_recipe_details(recipe_summary_json: str | None) -> str | None:
    """search_by_name only returns a summary (id/name/category/area/
    thumbnail) -- it never includes ingredients or instructions, so on its
    own it can't actually ground a recipe response despite the SYSTEM_PROMPT
    claiming "real recipe data" whenever it's present (confirmed live: the
    LLM was silently inventing every ingredient list even for dishes that
    "were found"). The real ingredients/instructions need a second lookup,
    by the top match's id."""
    if not recipe_summary_json:
        return None
    try:
        parsed = json.loads(recipe_summary_json)
    except (json.JSONDecodeError, TypeError):
        return None
    results = parsed.get("results") or []
    if not results or not results[0].get("id"):
        return None

    raw = mcp_client.call_tool_sync_or_none("themealdb", "get_recipe_details", {"meal_id": results[0]["id"]})
    if not raw:
        return None
    try:
        detail = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not detail.get("ingredients"):
        return None
    return raw


def _fetch_all_recipes(dishes: list[str]) -> dict[str, str | None]:
    """dish name -> real recipe detail JSON (ingredients+instructions), or
    None if not found. Same two-round shape as _fetch_recipe_details, but
    batched (parallel search round, then parallel detail round) across
    every dish in a whole week's menu instead of just one."""
    if not dishes:
        return {}

    search_requests = [("themealdb", "search_by_name", {"name": dish[:60]}) for dish in dishes]
    search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=10.0)

    top_match: dict[str, str] = {}  # dish -> meal_id
    for dish, raw in zip(dishes, search_results):
        raw = _non_empty_results(raw)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        results = parsed.get("results") or []
        if results and results[0].get("id"):
            top_match[dish] = results[0]["id"]

    output: dict[str, str | None] = {dish: None for dish in dishes}
    if not top_match:
        return output

    detail_requests = [("themealdb", "get_recipe_details", {"meal_id": meal_id}) for meal_id in top_match.values()]
    detail_results = mcp_client.call_tools_parallel_sync(detail_requests, timeout=10.0)
    for (dish, _meal_id), raw in zip(top_match.items(), detail_results):
        if not raw:
            continue
        try:
            detail = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if detail.get("ingredients"):
            output[dish] = raw
    return output


class RecipePortionAgent(BaseStrategyAgent):
    AGENT_NAME = "Recipe & Portion Specialist"
    AGENT_PORT = 8303
    AGENT_SYNOPSIS = "Finds real recipe ideas and grounds cafeteria portion sizing"
    AGENT_CAPABILITY_DETAIL = "Retrieves real recipes and ingredient data to propose cafeteria-scale portion guidance for a specific dish or a whole week's menu."
    AGENT_KEYPHRASES = ["recipe", "recipes", "portion", "portions", "serving", "serving size",
                         "ingredients", "preparation", "cook", "batch", "amounts needed"]
    # BaseStrategyAgent's default of 50 words is a single-item budget --
    # this is the value that actually governs (both the per-dish budget
    # hint's arithmetic and the final hard truncation) whenever convener
    # delegates a question, since convener only embeds the UI slider's
    # value as advisory text, never as the maxWords feature this reads.
    # A whole-week response needs to fit a full ingredient list, a prep
    # summary, and a serving size for potentially 5+ dishes -- 350 gives
    # each dish real room instead of a couple of words apiece.
    MAX_RESPONSE_WORDS = 350

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
            logger.info("[RecipePortion] Saved Menu Designer's proposed menu for conv %s", conv_id)

    def process_utterance(self, user_text: str) -> dict:
        single_dish_query = _dish_query(user_text)
        if single_dish_query:
            return self._respond_for_one_dish(user_text, single_dish_query)

        saved_menu = self._observed_menus.get(self._current_conv_id, "")
        if saved_menu:
            dishes = _extract_dishes(saved_menu)
            if dishes:
                return self._respond_for_whole_menu(saved_menu, dishes)

        # No specific dish named and no usable saved menu -- fall back to
        # general reasoning rather than doing nothing.
        user_message = f"""{self._history_block()}Menu idea: {user_text}

Data retrieved:
No recipe or nutrient data found -- use general culinary knowledge.

Please provide a concrete recipe with portion guidance for ONE serving of this dish."""
        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        return {"text": text, "html": self._text_to_html_list(text)}

    def _respond_for_one_dish(self, user_text: str, query: str) -> dict:
        recipe_summary, nutrient_data = mcp_client.call_tools_parallel_sync([
            ("themealdb", "search_by_name", {"name": query[:60]}),
            ("usda_fdc", "search_food", {"query": query[:80], "limit": 2}),
        ], timeout=10.0)
        nutrient_data = _non_empty_results(nutrient_data)
        # search_by_name only found a candidate dish -- fetch that
        # match's real ingredients/instructions in a second lookup.
        recipe_data = _fetch_recipe_details(_non_empty_results(recipe_summary))

        gathered = []
        if recipe_data:
            gathered.append(f"Recipe data (ingredients/instructions):\n{recipe_data}")
        if nutrient_data:
            gathered.append(f"Ingredient nutrient/serving-size reference data:\n{nutrient_data}")
        context = "\n\n".join(gathered) if gathered else "No recipe or nutrient data found -- use general culinary knowledge."

        user_message = f"""{self._history_block()}Menu idea: {user_text}

Data retrieved:
{context}

Please provide a concrete recipe with portion guidance for ONE serving of this dish."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        return {"text": text, "html": self._text_to_html_list(text)}

    def _respond_for_whole_menu(self, saved_menu: str, dishes: list[str]) -> dict:
        recipe_data = _fetch_all_recipes(dishes)

        gathered = []
        not_found = []
        for dish, raw in recipe_data.items():
            if raw:
                gathered.append(f"{dish}:\n{raw}")
            else:
                not_found.append(dish)
        context = "\n\n".join(gathered) if gathered else "No recipe data found for any dish."
        not_found_note = f"\nDishes with no recipe data found: {', '.join(not_found)}" if not_found else ""

        # Same fix as Menu Designer's per-day word budget: without an
        # explicit per-dish word count, the model writes an exhaustive
        # entry for the first dish or two and the reply gets hard-truncated
        # (see _limit_words) before every dish gets covered -- confirmed
        # live (a 3-dish menu at a 300-word budget only ever covered dish
        # 1). Giving it the arithmetic up front, not just the instruction
        # to "cover everything," is what actually makes it reliable.
        per_dish_words = max(20, self._current_max_words // max(1, len(dishes)))
        budget_hint = (
            f"\n\nThis menu has {len(dishes)} dishes. Budget roughly {per_dish_words} words "
            f"per dish so all {len(dishes)} fit in the response -- do not spend more than "
            f"about that on any single dish until every one of the {len(dishes)} dishes has its "
            f"own entry."
        )

        user_message = f"""{self._history_block()}The week's menu as proposed by the Menu Designer:
{saved_menu}

Dishes identified: {', '.join(dishes)}

Real recipe data retrieved from TheMealDB (may be written for several servings -- scale down to one serving):
{context}
{not_found_note}
{budget_hint}

Please provide a concrete recipe with portion guidance (ingredient amounts needed) for ONE serving of EVERY dish in this week's menu."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, timeout=45)
        return {"text": text, "html": self._text_to_html_list(text)}


def main() -> None:
    agent = RecipePortionAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(RecipePortionAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
