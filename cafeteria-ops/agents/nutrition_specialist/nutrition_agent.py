#!/usr/bin/env python3
"""
Nutrition Specialist Agent — Cafeteria Ops Floor

Assesses nutritional content of menu items using real USDA FoodData
Central data: calories, macros, sodium, and other tracked nutrients. Also
remembers the Recipe & Portion Specialist's one-serving recipe amounts
(broadcast to it via Pass-Through, see on_observed_utterance below) so it
can be asked to work out per-serving nutrition for a WHOLE menu, not just
one food at a time -- the Recipe & Portion Specialist runs immediately
before this agent (see convener_service/convener.py's MENU_PLANNING_AGENTS)
specifically so those one-serving amounts are always ready by the time
this agent is asked.

Port: 8302
"""

import json
import logging
import os
import re
import sys
from html import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app, render_bar_chart_png
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

# Hardcoded to match agents/recipe_portion_specialist/recipe_portion_agent.py's
# own AGENT_PORT -- cafeteria-ops agents use serviceUrl == speakerUri ==
# "http://127.0.0.1:<port>/" throughout, and each agent file is
# self-contained (no cross-agent imports), so this is kept in sync by hand
# like every other agent's port number in this project.
_RECIPE_PORTION_SERVICE_URL = "http://127.0.0.1:8303/"

SYSTEM_PROMPT = """You are the Nutrition Specialist for a corporate cafeteria planning panel.
Your job is to assess the nutritional profile of the menu item(s) or question given.

You have access to real USDA nutrient data. Use it to ground your assessment
in actual calories, macronutrients (protein/fat/carbohydrate), and sodium --
don't estimate figures the data already gives you.

Cover: calorie range, macro balance, sodium level relative to a typical daily
lunch target (~700-800mg for one meal), and any notable nutritional strength
or concern for a cafeteria audience (e.g. high sodium, low fiber, good
protein-to-calorie ratio).

Derive your assessment from the actual food(s) named and the data retrieved
-- don't reuse generic nutrition commentary that would apply to any dish.

Return your response as a single JSON object with exactly these two fields:
{
  "text": "your prose nutritional assessment here; length guided by a separate instruction",
  "bars": [
    {"label": "Calories", "value": <number>, "display": "<e.g. 420 kcal>"},
    {"label": "Protein", "value": <number>, "display": "<e.g. 28g>"},
    {"label": "Fat", "value": <number>, "display": "<e.g. 14g>"},
    {"label": "Carbs", "value": <number>, "display": "<e.g. 45g>"}
  ]
}

The "bars" array must contain exactly these four entries, in this order,
using the real values from the retrieved data (grams for protein/fat/carbs,
kcal for calories -- "value" is the raw number used to size the bar, scaled
however makes the four bars visually comparable; "display" is the
human-readable string). If the data for a field is genuinely unavailable,
use 0 for "value" and "n/a" for "display" rather than guessing.
Output nothing outside the JSON object. Do NOT include any SVG or HTML."""

# Used for the whole-menu path (see _respond_for_whole_menu below): the
# single-food SYSTEM_PROMPT's JSON+bars shape is built for exactly one
# dish, so a multi-dish reply uses this separate plain-prose prompt
# instead -- same split as recipe_portion_agent.py's single-dish vs
# whole-week SYSTEM_PROMPT.
_WHOLE_MENU_SYSTEM_PROMPT = """You are the Nutrition Specialist for a corporate cafeteria planning panel.
You have been given a set of dishes with their real ONE-SERVING recipe/
ingredient amounts (from the Recipe & Portion Specialist, which runs right
before you) and, where available, real USDA nutrient data for those
ingredients.

For EVERY dish, provide a compact nutritional assessment for that ONE
serving: an estimated calorie count, macro balance (protein/fat/
carbohydrate), and sodium level relative to a typical daily lunch target
(~700-800mg for one meal) -- grounded in the retrieved USDA data where
available, plainly noted as an estimate where it isn't. Cover every dish
before adding extra depth to any single one. Put each dish on its OWN LINE
(a real line break between one dish's entry and the next, not run together
in one paragraph). Do not silently drop a dish that has no retrieved data
-- name it and say so plainly instead.

After covering every dish, end with a short concluding note, on its own
final line, flagging any notable nutrition problems across the WHOLE menu
(e.g. cumulative sodium risk if several dishes run high, a day with poor
macro balance, low fiber or protein across the board) -- if nothing stands
out, say briefly that no notable problems were found rather than omitting
the conclusion.

Derive specifics from the actual dish(es) and one-serving ingredient
amounts given, not a generic template. Write in plain prose only -- no
markdown, bold, bullet characters, or JSON -- just plain text lines. Keep
the response focused; overall length is guided by a separate instruction."""

_DISH_EXTRACTION_SYSTEM_PROMPT = """Extract the distinct dish names from a cafeteria recipe/portion writeup.

Identify every distinct DISH (a specific food item someone would cook -- e.g.
"Grilled Chicken Caesar Salad"). Ignore day labels ("Day 1:") and anything
that isn't an actual dish name.

Respond with ONLY a single JSON object and no other text:
{"dishes": ["<dish name>", ...]}
"""


def _extract_dishes(recipe_text: str) -> list[str]:
    """LLM-based extraction of distinct dish names from the Recipe & Portion
    Specialist's saved whole-menu response. Free text like "Grilled Chicken
    Caesar Salad: 150g chicken breast, ... Beef stir-fry: ..." has an
    unknown number of dishes mixed with ingredient amounts and prep notes
    -- the same problem (and the same fix) as recipe_portion_agent.py's own
    menu extraction, kept as a separate local copy since each cafeteria-ops
    agent is self-contained."""
    raw = llm_utils.chat_sync(_DISH_EXTRACTION_SYSTEM_PROMPT, recipe_text, temperature=0, timeout=15)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [d.strip() for d in (parsed.get("dishes") or []) if isinstance(d, str) and d.strip()]


def _fetch_all_nutrients(dishes: list[str]) -> dict[str, str | None]:
    """dish name -> real USDA FoodData Central detail JSON, or None if not
    found. Same batched two-round shape (parallel search round, then
    parallel detail round) as recipe_portion_agent.py's _fetch_all_recipes."""
    if not dishes:
        return {}

    search_requests = [("usda_fdc", "search_food", {"query": dish[:80], "limit": 2}) for dish in dishes]
    search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=10.0)

    top_match: dict[str, str] = {}  # dish -> fdcId
    for dish, raw in zip(dishes, search_results):
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        results = parsed.get("results") or []
        if results and results[0].get("fdcId"):
            top_match[dish] = results[0]["fdcId"]

    output: dict[str, str | None] = {dish: None for dish in dishes}
    if not top_match:
        return output

    detail_requests = [("usda_fdc", "get_food_details", {"fdc_id": fdc_id}) for fdc_id in top_match.values()]
    detail_results = mcp_client.call_tools_parallel_sync(detail_requests, timeout=10.0)
    for (dish, _fdc_id), raw in zip(top_match.items(), detail_results):
        if raw:
            output[dish] = raw
    return output


def _build_nutrition_chart(bars: list[dict]) -> str:
    """Render a calories/protein/fat/carbs bar chart as a PNG image."""
    colors = ["#8E24AA", "#1E88E5", "#FB8C00", "#43A047"]
    rows = []
    for item in bars[:4]:
        label = str(item.get("label", ""))[:9]
        display = str(item.get("display", ""))[:12]
        try:
            value = max(0.0, float(item.get("value", 0)))
        except (TypeError, ValueError):
            value = 0.0
        rows.append((label, value, display))

    if not rows:
        return ""

    max_val = max((v for _, v, _ in rows), default=0) or 1
    max_bar_w = 200
    chart_rows = [
        (label, round(value / max_val * max_bar_w), display, colors[i % len(colors)])
        for i, (label, value, display) in enumerate(rows)
    ]
    return render_bar_chart_png(
        "Nutrition Profile", chart_rows,
        row_h=40, top=32, bar_h=22,
        alt="Nutrition profile chart",
    )


def _build_whole_menu_html(text: str) -> str:
    """Per-dish entries as a real <ul> list, with the final cross-menu
    concluding note (see _WHOLE_MENU_SYSTEM_PROMPT's "end with a short
    concluding note, on its own final line" instruction) rendered as its
    own plain paragraph below the list, NOT swept into a bullet alongside
    the per-dish entries -- unlike BaseStrategyAgent._text_to_html_list
    (which has no way to know one particular line is a synthesis of every
    line above it, not one more item of the same kind), this treats the
    text's own documented last-line-is-the-conclusion shape explicitly."""
    text = BaseStrategyAgent._strip_markdown(text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return ""
    *dish_lines, conclusion = lines
    if not dish_lines:
        return ""
    items = "".join(f"<li>{escape(line)}</li>" for line in dish_lines)
    conclusion_html = f'<p style="margin-top:8px">{escape(conclusion)}</p>'
    return f"<ul>{items}</ul>{conclusion_html}"


# The maxWords slider's instruction, appended by convener._question_text
# whenever the UI's maxWords != the no-instruction default -- present on
# almost every real request, so it must be stripped before judging whether
# the ORIGINAL question names a specific food, not treated as part of it.
_MAX_WORDS_INSTRUCTION = re.compile(r"\n\n\[Write approximately[\s\S]*$", re.IGNORECASE)
_ADDRESS_PREFIX = re.compile(r"^[^,]{0,40},\s*", re.IGNORECASE)
_REQUEST_FRAMING = re.compile(
    r"\b(how many calories (are |is )?in|how much (protein|fat|sodium|carb\w*) (is |are )?in|"
    r"what'?s the nutrition(al)? (value|profile|content)?\s*(of)?|nutrition(al)? (value|profile|content) of|"
    r"assess|evaluate|analy[sz]e|tell me about)\b",
    re.IGNORECASE,
)
# Signals a broad planning question (a whole menu/week/budget), not a
# lookup for one specific food -- e.g. "plan a five-day lunch menu for 450
# people ... itemized costs ... budget of $7.00 per meal" has no food name
# in it at all.
_BROAD_PLANNING_SIGNAL = re.compile(
    r"\b(five-day|\d+[- ]day|weekly|week'?s|itemized|budget|per meal|menu for|lunch menu|meal plan)\b",
    re.IGNORECASE,
)
_VAGUE_REFERENT = re.compile(r"^(this|the|that)?\s*(menu item|dish|food|meal|item)s?\.?$", re.IGNORECASE)


def _food_query(user_text: str) -> str | None:
    """A specific food/dish name to search USDA FDC for, or None when the
    request names no specific food -- a blind full-text search on a whole
    planning sentence returns some loosely keyword-matched, irrelevant food
    (confirmed live: a five-day menu planning request returned a branded
    cheeseburger), which is worse than falling back to general nutrition
    knowledge."""
    cleaned = _MAX_WORDS_INSTRUCTION.sub("", user_text)
    cleaned = _ADDRESS_PREFIX.sub("", cleaned, count=1)
    cleaned = _REQUEST_FRAMING.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!")
    if not cleaned or _VAGUE_REFERENT.match(cleaned):
        return None
    if _BROAD_PLANNING_SIGNAL.search(cleaned):
        return None
    if len(cleaned.split()) > 8:
        return None
    return cleaned


class NutritionAgent(BaseStrategyAgent):
    AGENT_NAME = "Nutrition Specialist"
    AGENT_PORT = 8302
    AGENT_SYNOPSIS = "Assesses menu item nutrition using real USDA FoodData Central data"
    AGENT_CAPABILITY_DETAIL = "Analyzes calories, macronutrients, and sodium for menu items using real USDA nutrient data."
    AGENT_KEYPHRASES = ["nutrition", "calories", "protein", "fat", "carbs", "sodium",
                         "healthy", "macros", "nutrient", "nutritional"]
    # BaseStrategyAgent's default of 50 words is a single-item budget --
    # this is the value that actually governs (both the per-dish budget
    # hint's arithmetic and the final hard truncation) whenever convener
    # delegates a question, since convener only embeds the UI slider's
    # value as advisory text, never as the maxWords feature this reads.
    # A whole-menu response needs calories/macros/sodium for potentially
    # 5+ dishes plus the closing cross-menu note -- 300 gives each dish
    # real room instead of a couple of words apiece.
    MAX_RESPONSE_WORDS = 300

    def __init__(self):
        super().__init__()
        # conv_id -> the Recipe & Portion Specialist's last saved
        # one-serving recipe writeup observed in that conversation (see
        # on_observed_utterance). Scoped per conversation so an older,
        # unrelated conversation's recipes can never leak into a new one
        # against the same running agent process.
        self._observed_recipes: dict[str, str] = {}

    def on_observed_utterance(self, conv_id: str, speaker_uri: str, text: str) -> None:
        if self._normalize_endpoint_id(speaker_uri) == self._normalize_endpoint_id(_RECIPE_PORTION_SERVICE_URL):
            self._observed_recipes[conv_id] = text
            logger.info("[Nutrition] Saved Recipe & Portion's one-serving recipes for conv %s", conv_id)

    def process_utterance(self, user_text: str) -> dict | str:
        food_query = _food_query(user_text)
        if food_query:
            return self._respond_for_one_food(user_text, food_query)

        saved_recipes = self._observed_recipes.get(self._current_conv_id, "")
        if saved_recipes:
            dishes = _extract_dishes(saved_recipes)
            if dishes:
                return self._respond_for_whole_menu(saved_recipes, dishes)

        # No specific food named and no usable saved recipe writeup --
        # fall back to general reasoning rather than doing nothing.
        return self._respond_json_with_bars(
            user_text, "No USDA nutrient data found -- use general nutrition knowledge."
        )

    def _respond_for_one_food(self, user_text: str, food_query: str) -> dict | str:
        search_result = mcp_client.call_tool_sync_or_none(
            "usda_fdc", "search_food", {"query": food_query, "limit": 3}
        )

        details = None
        if search_result:
            try:
                parsed = json.loads(search_result)
                results = parsed.get("results") or []
                if results and results[0].get("fdcId"):
                    details = mcp_client.call_tool_sync_or_none(
                        "usda_fdc", "get_food_details", {"fdc_id": results[0]["fdcId"]}
                    )
            except (json.JSONDecodeError, KeyError, IndexError):
                pass

        context = details or search_result or "No USDA nutrient data found -- use general nutrition knowledge."
        return self._respond_json_with_bars(user_text, context)

    def _respond_json_with_bars(self, user_text: str, context: str) -> dict | str:
        user_message = f"""{self._history_block()}Menu item or nutrition question: {user_text}

USDA nutrient data retrieved:
{context}

Please provide a nutritional assessment as a JSON object."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                text = (parsed.get("text") or "").strip()
                bars = parsed.get("bars") or []
                chart_html = _build_nutrition_chart(bars) if isinstance(bars, list) else ""
                # The browser's Analysis report popup shows "html" in place
                # of "text" whenever html is non-empty (avoiding a duplicate
                # summary) -- so a chart-only html would silently drop the
                # actual nutritional assessment prose from the report. Embed
                # the same text above the chart here, matching how Shopping
                # List's cost chart already sits above its own text-equivalent
                # list rather than replacing it.
                html = f'<p style="font-family:sans-serif;margin:0 0 12px;font-size:0.9rem;color:#333;line-height:1.5">{escape(text)}</p>{chart_html}' if chart_html else ""
                if text:
                    return {"text": text, "html": html}
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
        return raw

    def _respond_for_whole_menu(self, saved_recipes: str, dishes: list[str]) -> dict:
        nutrient_data = _fetch_all_nutrients(dishes)

        gathered = []
        not_found = []
        for dish, raw in nutrient_data.items():
            if raw:
                gathered.append(f"{dish}:\n{raw}")
            else:
                not_found.append(dish)
        context = "\n\n".join(gathered) if gathered else "No USDA nutrient data found for any dish."
        not_found_note = f"\nDishes with no USDA nutrient data found: {', '.join(not_found)}" if not_found else ""

        # Same fix as Menu Designer's per-day and Recipe & Portion's
        # per-dish word budgets: without explicit arithmetic, the model
        # exhausts the word budget on the first dish and the reply gets
        # hard-truncated (see BaseStrategyAgent._limit_words) before every
        # dish -- or the closing cross-menu note -- gets covered. Reserve a
        # fixed slice for the conclusion up front so it doesn't get pushed
        # out by however many dishes there happen to be.
        conclusion_words = 30
        per_dish_budget = max(1, self._current_max_words - conclusion_words)
        per_dish_words = max(20, per_dish_budget // max(1, len(dishes)))
        budget_hint = (
            f"\n\nThis menu has {len(dishes)} dishes. Budget roughly {per_dish_words} words "
            f"per dish so all {len(dishes)} fit in the response -- do not spend more than "
            f"about that on any single dish until every one of the {len(dishes)} dishes has its "
            f"own entry. Reserve roughly the last {conclusion_words} words for the closing "
            f"cross-menu nutrition-problems note."
        )

        user_message = f"""{self._history_block()}One-serving recipe amounts from the Recipe & Portion Specialist:
{saved_recipes}

Dishes identified: {', '.join(dishes)}

Real USDA nutrient data retrieved (per ingredient):
{context}
{not_found_note}
{budget_hint}

Please provide a one-serving nutritional assessment for EVERY dish in this week's menu, ending with a concluding note on any nutrition problems across the whole menu."""

        text = llm_utils.chat_sync(_WHOLE_MENU_SYSTEM_PROMPT, user_message, timeout=45)
        return {"text": text, "html": _build_whole_menu_html(text)}


def main() -> None:
    agent = NutritionAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(NutritionAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
