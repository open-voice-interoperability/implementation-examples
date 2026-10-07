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

# This agent retrieves and formats data (USDA / TheMealDB lookups, portion
# arithmetic) rather than doing open-ended creative work, so every LLM call
# here runs on the smaller, cheaper "lookup" model tier. Only the Menu
# Designer keeps the full analysis model. See llm_utils.LOOKUP_* / .env.
_LOOKUP = {"ollama_model": llm_utils.LOOKUP_OLLAMA_MODEL, "openai_model": llm_utils.LOOKUP_LLM_MODEL}

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

IMPORTANT: this system has NO data on what diners actually ate, chose, or
were served in the past -- no consumption history, no historical menu
records, no diner surveys. If the request depends on that (e.g. "average
sodium of the lunches diners chose last month", "how does this compare to
what people usually eat here"), say plainly in "text" that you don't have
that data and cannot answer it, and set every "bars" value to 0 / "n/a".
Never state a specific figure for data you don't have.

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
amounts given, not a generic template.

IMPORTANT: this system has NO data on what diners actually ate, chose, or
were served in the past -- no consumption history, no diner surveys. If the
request depends on that, say plainly you don't have that data and cannot
answer it rather than stating a figure.

Write in plain prose only -- no markdown, bold, bullet characters, or JSON
-- just plain text lines. Keep the response focused; overall length is
guided by a separate instruction."""

_DISH_EXTRACTION_SYSTEM_PROMPT = """Extract the main dishes from a cafeteria recipe/portion writeup.

Return ONE entry per dish (per day / per meal) -- the whole meal as a
single dish, named by its main or centerpiece component in 2-4 plain words
("Grilled salmon", "Herb-crusted pork tenderloin", "Stuffed portobello").

Do NOT:
- break a meal into parts -- sides, starches, vegetables, salads, sauces,
  glazes, dressings, marinades and garnishes belong to their dish, they
  are not separate dishes ("... with wild rice pilaf and a lemon-pepper
  crust" is still just "Grilled salmon")
- include day labels ("Day 1:"), headcounts, serving or operational
  notes, or anything that isn't a dish
- keep plating flourishes ("pan-seared", "served over", "with a drizzle
  of ...") -- name the dish, not how it is presented

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
    raw = llm_utils.chat_sync(_DISH_EXTRACTION_SYSTEM_PROMPT, recipe_text, temperature=0, timeout=15, **_LOOKUP)
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

    # Search FDC by each dish's core ingredient word, not its full composite
    # name: FDC is an ingredient database, so "Herb-crusted pork tenderloin
    # with garlic mashed potatoes" matches nothing while "pork" does -- and
    # firing one doomed call per dish also burns through FDC's DEMO_KEY rate
    # limit fast. Dedupe so a term several dishes share ("chicken") costs one
    # lookup, not five.
    dish_term: dict[str, str] = {dish: (_core_term(dish) or dish[:80]) for dish in dishes}
    unique_terms = list(dict.fromkeys(dish_term.values()))

    search_requests = [("usda_fdc", "search_food", {"query": term[:80], "limit": 2}) for term in unique_terms]
    search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=10.0)

    term_fdc: dict[str, str] = {}  # search term -> fdcId
    for term, raw in zip(unique_terms, search_results):
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        results = parsed.get("results") or []
        if results and results[0].get("fdcId"):
            term_fdc[term] = results[0]["fdcId"]

    output: dict[str, str | None] = {dish: None for dish in dishes}
    if not term_fdc:
        return output

    unique_ids = list(dict.fromkeys(term_fdc.values()))
    detail_requests = [("usda_fdc", "get_food_details", {"fdc_id": fdc_id}) for fdc_id in unique_ids]
    detail_results = mcp_client.call_tools_parallel_sync(detail_requests, timeout=10.0)
    id_detail = {fdc_id: raw for fdc_id, raw in zip(unique_ids, detail_results) if raw}

    # Dedupe: dishes sharing a core term ("chicken") resolve to the same
    # fdcId. The first dish (menu order) carries that nutrient data; the
    # rest stay None -> not_found, so the model estimates from the recipe
    # amounts rather than repeating an identical block.
    claimed_ids: set[str] = set()
    for dish in dishes:
        fdc_id = term_fdc.get(dish_term[dish])
        if not fdc_id or fdc_id in claimed_ids:
            continue
        detail = id_detail.get(fdc_id)
        if detail:
            output[dish] = detail
            claimed_ids.add(fdc_id)
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
# A compound ask ("how many calories AND how much sodium is in X") joins two
# framing clauses with "and" before the shared trailing "in" -- confirmed
# live that only the second clause ("how much sodium is in") matched below,
# leaving "how many calories and" attached to the food name. That pushed the
# cleaned text over the 8-word cap, so _food_query returned None entirely
# and the question silently fell through to a whole-menu nutrition dump
# instead of answering about the food actually named. The first two
# alternatives match the compound form (either nutrient first) as one
# clause so it's fully stripped; the third/fourth remain for the plain
# single-clause form.
_REQUEST_FRAMING = re.compile(
    r"\b(how many calories(?:,? and how much (?:protein|fat|sodium|carb\w*))? (are |is )?in|"
    r"how much (?:protein|fat|sodium|carb\w*)(?:,? and how many calories)? (is |are )?in|"
    r"how many calories (are |is )?in|how much (protein|fat|sodium|carb\w*) (is |are )?in|"
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
# Left over once _REQUEST_FRAMING strips "...is in" / "...are in" -- the
# article right after "in" ("in A grilled chicken caesar wrap") isn't part
# of the dish name.
_LEADING_ARTICLE = re.compile(r"^(a|an|the)\s+", re.IGNORECASE)


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
    cleaned = _LEADING_ARTICLE.sub("", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!")
    if not cleaned or _VAGUE_REFERENT.match(cleaned):
        return None
    if _BROAD_PLANNING_SIGNAL.search(cleaned):
        return None
    if len(cleaned.split()) > 8:
        return None
    return cleaned


# Preparation / plating / seasoning words that describe HOW a dish is cooked
# or served, not WHAT it is. USDA FoodData Central is an ingredient database
# -- the Menu Designer's composite "Herb-crusted pork tenderloin with garlic
# mashed potatoes" matches no food entry, while the core "pork" does.
# Stripping these leaves the identity noun to retry with. Kept as a local
# copy (like _extract_dishes) since each cafeteria-ops agent is
# self-contained; recipe_portion_agent.py has the same list.
_PREP_PLATING_WORDS = frozenset("""
grilled roasted seared sauteed sauteed baked braised fried pan stir steamed
poached smoked charred blackened caramelized whipped mashed pureed crusted
herb herbed spiced spice glazed marinated fresh creamy crispy crisp crunchy
tender juicy homemade classic style rustic hearty light warm cold chilled
served side sides topped drizzled dressed accompanied stuffed rolled wrapped
with without and the a an of on in over under alongside plus atop
lemon pepper peppered garlic butter buttered honey dijon mustard balsamic
citrus soy teriyaki sesame ginger chili chilli paprika cumin rosemary thyme
basil parsley cilantro oregano cinnamon
sauce reduction glaze gravy vinaigrette dressing crust rub marinade jus
caps cap fillet fillets breast breasts thigh thighs loin tenderloin cutlet
strips bites medallions skewers
one two three four five six seven eight nine ten
serving servings portion portions recipe recipes amount amounts ingredient
ingredients dish dishes meal meals menu menus day days week weeks whole full
entire for from into please work give show find make
""".split())


def _core_term(dish_name: str) -> str:
    """The single identity word to search/retry with -- the first word left
    after prep/plating and generic request words are dropped ("Herb-crusted
    pork tenderloin" -> "pork"). "" if nothing identifiable remains (e.g. a
    vague "one-serving recipes for the whole menu"), which suppresses the
    retry rather than matching junk."""
    for word in re.findall(r"[A-Za-z]+", dish_name):
        if len(word) > 2 and word.lower() not in _PREP_PLATING_WORDS:
            return word.lower()
    return ""


# A question whose core answer depends on data this system does not have
# (what diners actually ate/chose/were served, or historical menu records)
# is declined BEFORE any LLM call -- confirmed live that qwen2.5:7b, even
# told plainly it has no such data, still pads the reply with a made-up
# "typical" sodium/calorie range. Substring match on the raw utterance.
_MISSING_DATA_MARKERS = (
    "diners chose", "diners ate", "diners selected", "diners picked",
    "people chose", "people ate", "our diners", "what was eaten",
    "what was chosen", "actually chose", "actually ate",
    "served last week", "served last month", "serve last week",
    "serve last month", "we served last", "we serve last",
    "last week's menu", "last month's menu", "last week's lunch",
    "consumption history", "consumption data", "what people usually eat",
    "what people typically eat", "usually eat here", "typically eat here",
    "how does this compare to what", "uptake",
)
_MISSING_DATA_DECLINE = (
    "I don't have data on what diners actually ate, chose, or were served in "
    "the past -- no consumption history or diner surveys -- so I can't answer "
    "that."
)


def _needs_unavailable_data(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    return any(marker in lowered for marker in _MISSING_DATA_MARKERS)


class NutritionAgent(BaseStrategyAgent):
    AGENT_NAME = "Nutrition Specialist"
    AGENT_PORT = 8302
    AGENT_SYNOPSIS = "Assesses menu item nutrition using real USDA FoodData Central data"
    AGENT_CAPABILITY_DETAIL = "Analyzes calories, macronutrients, and sodium for menu items using real USDA nutrient data."
    WORKING_LABEL = "checking the nutrition levels"
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
        if _needs_unavailable_data(user_text):
            logger.info("[Nutrition] Declining -- question needs consumption/history data this system lacks")
            return {"text": _MISSING_DATA_DECLINE, "html": ""}

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
        def _lookup(query: str) -> tuple[str | None, str | None]:
            """(details JSON, raw search JSON) for one FDC query."""
            search_raw = mcp_client.call_tool_sync_or_none("usda_fdc", "search_food", {"query": query, "limit": 3})
            if not search_raw:
                return None, None
            try:
                results = (json.loads(search_raw).get("results") or [])
            except (json.JSONDecodeError, TypeError):
                return None, search_raw
            if results and results[0].get("fdcId"):
                return mcp_client.call_tool_sync_or_none(
                    "usda_fdc", "get_food_details", {"fdc_id": results[0]["fdcId"]}
                ), search_raw
            return None, search_raw

        details, search_result = _lookup(food_query)
        if not details:
            # Retry with just the core identity word -- FDC won't match a
            # composite "Grilled chicken breast with honey glaze", but
            # "chicken" pulls a real nutrient entry.
            term = _core_term(food_query)
            if term and term != food_query.strip().lower():
                retry_details, retry_search = _lookup(term)
                details = details or retry_details
                search_result = search_result or retry_search

        context = details or search_result or "No USDA nutrient data found -- use general nutrition knowledge."
        return self._respond_json_with_bars(user_text, context)

    def _respond_json_with_bars(self, user_text: str, context: str) -> dict | str:
        user_message = f"""{self._history_block()}Menu item or nutrition question: {user_text}

USDA nutrient data retrieved:
{context}

Please provide a nutritional assessment as a JSON object."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, **_LOOKUP)
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

        text = llm_utils.chat_sync(_WHOLE_MENU_SYSTEM_PROMPT, user_message, timeout=45, **_LOOKUP)
        return {"text": text, "html": _build_whole_menu_html(text)}


def main() -> None:
    agent = NutritionAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(NutritionAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
