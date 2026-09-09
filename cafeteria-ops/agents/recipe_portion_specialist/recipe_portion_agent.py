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

# This agent retrieves and formats data (USDA / TheMealDB lookups, portion
# arithmetic) rather than doing open-ended creative work, so every LLM call
# here runs on the smaller, cheaper "lookup" model tier. Only the Menu
# Designer keeps the full analysis model. See llm_utils.LOOKUP_* / .env.
_LOOKUP = {"ollama_model": llm_utils.LOOKUP_OLLAMA_MODEL, "openai_model": llm_utils.LOOKUP_LLM_MODEL}

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

_DISH_EXTRACTION_SYSTEM_PROMPT = """Extract the main dishes from a cafeteria menu.

Return ONE entry per dish (per day / per menu line) -- the whole meal as a
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

This system keeps NO record of recipes previously used or dishes previously
made in this cafeteria. If asked "what recipe did we use last time" or
similar, say plainly you don't have that history -- you can still give a
standard one-serving recipe for the dish, but don't imply it is the one
previously used here.

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


# Preparation / plating / seasoning words that describe HOW a dish is cooked
# or served, not WHAT it is. TheMealDB's title search (search.php?s=) matches
# a query only as a substring of a recipe title, so the Menu Designer's
# "Grilled salmon with a lemon-pepper crust" finds nothing while a bare
# "salmon" finds several (confirmed live: 0 vs 7). Stripping these leaves the
# identity noun to retry with.
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
    """The single identity word to retry a lookup with when the dish name
    as given found nothing -- the first word left after prep/plating and
    generic request words are dropped ("Herb-crusted pork tenderloin" ->
    "pork"). "" if nothing identifiable remains (e.g. a vague "one-serving
    recipes for the whole menu"), which suppresses the retry rather than
    matching junk."""
    for word in re.findall(r"[A-Za-z]+", dish_name):
        if len(word) > 2 and word.lower() not in _PREP_PLATING_WORDS:
            return word.lower()
    return ""


def _extract_dishes(menu_text: str) -> list[str]:
    """LLM-based extraction of distinct dish names from a proposed menu.
    Free text like "Day 1: X, Day 2: Y, ..." has an unknown number of
    dishes mixed with day labels and operational notes -- the same problem
    (and the same fix) as the Shopping List Specialist's own menu
    extraction, kept as a separate local copy since each cafeteria-ops
    agent is self-contained."""
    raw = llm_utils.chat_sync(_DISH_EXTRACTION_SYSTEM_PROMPT, menu_text, temperature=0, timeout=15, **_LOOKUP)
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

    top_match: dict[str, str] = {}  # dish -> meal_id

    def _search_round(queries: dict[str, str]) -> None:
        """queries: dish -> search term. Records a top_match for any hit."""
        if not queries:
            return
        requests = [("themealdb", "search_by_name", {"name": term[:60]}) for term in queries.values()]
        results = mcp_client.call_tools_parallel_sync(requests, timeout=10.0)
        for dish, raw in zip(queries.keys(), results):
            raw = _non_empty_results(raw)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            hits = parsed.get("results") or []
            if hits and hits[0].get("id"):
                top_match[dish] = hits[0]["id"]

    # Round 1: the dish name as given.
    _search_round({dish: dish for dish in dishes})
    # Round 2: for anything still unmatched, retry with just the core
    # identity word -- TheMealDB's title search can't match the Menu
    # Designer's full "Grilled salmon with a lemon-pepper crust" phrasing.
    retry = {}
    for dish in dishes:
        if dish in top_match:
            continue
        term = _core_term(dish)
        if term and term != dish.strip().lower():
            retry[dish] = term
    _search_round(retry)

    # Dedupe by meal_id: several dishes can resolve to the SAME TheMealDB
    # recipe -- especially after the core-term retry, where e.g. "Grilled
    # chicken breast" and "Chicken tikka masala" both reduce to "chicken"
    # and grab the same match. Keep the first dish (menu order) for each
    # meal_id; the rest fall through to not_found so the model derives a
    # dish-specific recipe rather than printing the identical one twice.
    claimed: dict[str, str] = {}  # meal_id -> first dish that claimed it
    for dish in dishes:
        meal_id = top_match.get(dish)
        if meal_id is None:
            continue
        if meal_id in claimed:
            del top_match[dish]
        else:
            claimed[meal_id] = dish

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


# A question that asks what recipe was previously used / how a dish was
# made here before is declined BEFORE any LLM call -- confirmed live that
# qwen2.5:7b just answers with a standard recipe and never mentions it has
# no such history. Substring match on the raw utterance. (A plain "give me
# a recipe for chicken curry" has none of these and is answered normally.)
_MISSING_DATA_MARKERS = (
    "recipe did we use", "recipe we used", "recipe we've used",
    "last time we made", "last time we cooked", "last time we served",
    "last time we prepared", "how did we make", "how we made it",
    "how we've made", "the version we used", "the one we used",
    "what we did last time", "our recipe for", "recipe from last",
    "recipe we had", "did we make it last",
)
_MISSING_DATA_DECLINE = (
    "I don't have any record of recipes previously used or dishes previously "
    "made in this cafeteria, so I can't tell you what was used last time."
)


def _needs_unavailable_data(user_text: str) -> bool:
    lowered = (user_text or "").lower()
    return any(marker in lowered for marker in _MISSING_DATA_MARKERS)


# --- serving scale -----------------------------------------------------------
#
# The recipe/portion round-robin (the forwarded planning request) always
# produces ONE-serving amounts -- the Nutrition Specialist runs right after
# and needs one serving, and the Shopping List Specialist scales the
# one-serving amounts itself. But a person can ALSO ask this agent directly
# to "show the recipes", which they want scaled to the whole cafeteria, with
# an explicit way to ask for a single serving instead. So:
#   * "single serving" / "per serving" phrasing anywhere -> one serving.
#   * an explicit request to SEE the recipes (whole menu) -> scale to the
#     headcount.
#   * an explicit "full service" / "batch" / "for everyone" -> scale, even
#     for a single named dish.
#   * anything else (including the round-robin planning request, which does
#     say "for 450 people" but is not a request to view recipes) -> one
#     serving, unchanged.
DEFAULT_SERVINGS = 450
_SINGLE_SERVING_RE = re.compile(
    r"\b(?:single|one|1|per)[\s-]+serving\b|\bper[- ]serving\b|\bone portion\b|\bjust one\b", re.I)
_RECIPE_VIEW_RE = re.compile(
    r"\b(?:show|see|view|display|list|pull up|bring up|give me|what(?:'s| is| are))\b[^.?!]*\brecipe", re.I)
_FULL_SERVICE_RE = re.compile(
    r"\bfull[\s-]?service\b|\bfull batch\b|\bfull number of servings\b|\bscale(?:d)?\s*(?:it|them|up)\b"
    r"|\bfor (?:all|everyone|the whole)\b|\bbatch (?:size|quantit)", re.I)
# The leftover of _dish_query when the request names no real dish (just
# "the recipes", "the menu", "a single serving", optionally trailing "for
# 300 people" etc.) -- these route to the whole-menu path, not a TheMealDB
# search.
_VAGUE_DISH_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?:(?:show|see|view|display|list|give|get|pull up|bring up|what(?:'s| is| are))\s+)?(?:me\s+)?"
    r"(?:the|a|an|all|all of the|every|our|those|these|it|them)?\s*"
    r"(?:recipes?|menu|dishes|meals?)\b"
    r"(?:\s+(?:for|to|of|please|now|scaled|full service|single serving|per serving)\b.*)?\s*[.?!]*$",
    re.I)
_VAGUE_SERVING_RE = re.compile(
    r"^\s*(?:(?:the|a|an)\s+){0,3}"
    r"(?:single serving|one serving|per serving|full service|full batch|batch|everything)"
    r"(?:\s+\S.*)?\s*[.?!]*$", re.I)
_SERVINGS_UNIT = (
    r"people|persons?|servings?|diners?|guests?|lunches|meals?|covers|portions?|plates?"
    r"|kids|children|students|staff|employees|attendees|adults|folks|heads?"
)
_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}
_SERVE_VERB = r"serves?|serving|feeds?|feed|to feed|to serve|cook(?:ing)? for|make(?:s)? for|meals? for|feeding"
_SERVINGS_UNIT_RE = re.compile(rf"\b(\d{{1,6}})\s*(?:{_SERVINGS_UNIT})\b", re.I)
_SERVINGS_VERB_RE = re.compile(rf"\b(?:{_SERVE_VERB})\s+(\d{{1,6}})\b", re.I)
# A bare "for N" needs 2+ digits and must not sit before a day/dish word --
# "for 5 days" and "for 3 dishes" are not headcounts.
_SERVINGS_FOR_RE = re.compile(
    r"\bfor\s+(\d{2,6})\b(?!\s*(?:day|week|hour|minute|min|dish|course|item|option|serving|of\b))", re.I)
_SERVINGS_UNIT_WORD_RE = re.compile(rf"\b({'|'.join(_WORD_NUMS)})\s*(?:{_SERVINGS_UNIT})\b", re.I)
_SERVINGS_VERB_WORD_RE = re.compile(rf"\b(?:{_SERVE_VERB}|for)\s+({'|'.join(_WORD_NUMS)})\b", re.I)
# Trailing "for 4 people" / "for four" clause on a dish query, so
# "chicken curry for 4 people" searches for "chicken curry".
_STRIP_HEADCOUNT_RE = re.compile(
    rf"[\s,]*\b(?:for|to\s+(?:feed|serve)|{_SERVE_VERB})\s+"
    rf"(?:\d{{1,6}}|{'|'.join(_WORD_NUMS)})\s*(?:{_SERVINGS_UNIT})?\s*[.?!]*\s*$", re.I)
# A dish query that is really just "food/a meal for N", not a dish.
_GENERIC_FOOD_RE = re.compile(
    r"^\s*(?:some\s+|a\s+)?(?:food|meals?|dinner|lunch|supper|brunch|something(?:\s+to\s+eat)?|a\s+meal|eats?)\b", re.I)

_MASS_G = {"g": 1, "gram": 1, "grams": 1, "gm": 1, "gms": 1,
           "kg": 1000, "kilo": 1000, "kilos": 1000, "kilogram": 1000, "kilograms": 1000, "mg": 0.001}
_VOL_ML = {"ml": 1, "milliliter": 1, "milliliters": 1, "millilitre": 1, "millilitres": 1,
           "l": 1000, "liter": 1000, "liters": 1000, "litre": 1000, "litres": 1000}
_COUNT_UNITS = {"tsp", "tbsp", "teaspoon", "teaspoons", "tablespoon", "tablespoons", "cup", "cups",
                "clove", "cloves", "slice", "slices", "sprig", "sprigs", "can", "cans", "stick", "sticks",
                "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds"}
_SCALE_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)(\s*)([A-Za-z]+)\b")


def _fmt_amount(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _scale_recipe_text(text: str, n: int) -> str:
    """Multiply every ingredient quantity in a one-serving writeup by ``n``,
    rolling grams up to kg and millilitres up to litres. Times ("3 min"),
    temperatures ("400 F"), and dimensions ("1 inch") carry no food unit and
    pass through untouched; a per-plate / per-serving figure is left as
    written."""
    if n <= 1:
        return text

    def repl(match: re.Match) -> str:
        after = text[match.end():match.end() + 18].lower()
        if any(word in after for word in ("plate", "bowl", "per serving", "serving size", "portion size", "per plate", "per bowl")):
            return match.group(0)
        num, spacer, unit_raw = match.group(1), match.group(2), match.group(3)
        unit = unit_raw.lower()
        value = float(num) * n
        if unit in _MASS_G:
            grams = value * _MASS_G[unit]
            return f"{_fmt_amount(grams / 1000)} kg" if grams >= 1000 else f"{_fmt_amount(grams)} g"
        if unit in _VOL_ML:
            millilitres = value * _VOL_ML[unit]
            return f"{_fmt_amount(millilitres / 1000)} L" if millilitres >= 1000 else f"{_fmt_amount(millilitres)} ml"
        if unit in _COUNT_UNITS:
            return f"{_fmt_amount(value)}{spacer}{unit_raw}"
        return match.group(0)

    return _SCALE_UNIT_RE.sub(repl, text)


def _explicit_servings(text: str) -> "int | None":
    """A headcount the user actually stated ("for 4 people", "food for four",
    "serves 12", "cook for six"), or None. Digits or number words."""
    s = text or ""
    for rx in (_SERVINGS_UNIT_RE, _SERVINGS_VERB_RE, _SERVINGS_FOR_RE):
        m = rx.search(s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 100000:
                return n
    for rx in (_SERVINGS_UNIT_WORD_RE, _SERVINGS_VERB_WORD_RE):
        m = rx.search(s)
        if m:
            n = _WORD_NUMS.get(m.group(1).lower())
            if n:
                return n
    return None


def _servings_from(*sources: str) -> int:
    for src in sources:
        n = _explicit_servings(src or "")
        if n is not None:
            return n
    return DEFAULT_SERVINGS


# The browser board (public/cafeteria-ops.html) shows only the dish NAME for
# each entry and opens the recipe in a popup -- it keys on each dish being a
# single line "<dish name>: <amounts...>". The model mostly does that, but
# sometimes wraps a long dish name or its amounts across two or three lines,
# which the board would then read as extra (bogus) dishes. This folds every
# non-dish-start line back onto the preceding dish line.
_MENU_FIELD_LABEL_RE = re.compile(
    r"^(prep(aration)?|ingredients?|method|directions?|instructions?|steps?|serving(\s*size)?|serves|"
    r"portions?|plate|yield|amounts?|notes?|nutrition|calories?|makes)\b", re.I)
_MENU_NOTE_RE = re.compile(r"^\s*(full[\s-]?service\b|dishes with no\b|no recipe data\b|here (is|are)\b|below\b)", re.I)
_MENU_DISH_START_RE = re.compile(
    r"^\s*(?:day\s*\d+\s*[:\-–—.)]*\s*|\d+[.)]\s*)?([^:\n]{1,64}):\s+\S")


_MENU_PREP_VERB_RE = re.compile(
    r"^(season|sear|cook|mix|combine|heat|add|serve|toss|whisk|simmer|bake|roast|grill|saute|"
    r"sauté|fry|boil|steam|drain|stir|blend|marinate|chop|slice|dice|preheat|plate|garnish|"
    r"top|drizzle|fold|reduce|deglaze|rest|set|arrange|spread|brush|coat|dress|assemble|use|scale|"
    r"place|pour|cover|remove|transfer|cut|form|shape)\b", re.I)


def _dish_name_from_line(line: str) -> str | None:
    """The dish name if ``line`` starts a dish entry ("<name>: <amounts>"),
    else None -- a leading "Day 3 - " / "1. " ordinal is ignored, and a
    field label or a note line is not a dish."""
    if _MENU_NOTE_RE.match(line):
        return None
    m = _MENU_DISH_START_RE.match(line)
    if not m:
        return None
    name = m.group(1).strip(" .-–—")
    if not name or _MENU_FIELD_LABEL_RE.match(name) or len(name.split()) > 9:
        return None
    return name


def _looks_like_bare_dish_name(line: str) -> bool:
    """A colon-less line that reads as a dish TITLE rather than amounts or a
    prep sentence -- short, capitalised, no digits, not an imperative
    cooking instruction. Used to recover a dish boundary when the model
    ignored the "<name>: ..." format entirely."""
    if not line or not line[0].isupper():
        return False
    if _MENU_FIELD_LABEL_RE.match(line) or _MENU_PREP_VERB_RE.match(line):
        return False
    if any(ch.isdigit() for ch in line):
        return False
    words = line.rstrip(".").split()
    return 1 <= len(words) <= 7


def _normalize_menu_recipe_lines(text: str) -> str:
    """Collapse a whole-menu writeup to one line per dish. An explicit
    "<name>: <amounts>" line starts a dish; a bare title line also starts
    one (a synthetic colon is added); every other line is folded onto the
    current dish. Note / marker lines stay on their own line."""
    out: list[str] = []
    have_dish = False
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _MENU_NOTE_RE.match(line):
            out.append(line)
            have_dish = False
            continue
        if _dish_name_from_line(line):
            out.append(line)
            have_dish = True
        elif not have_dish and _looks_like_bare_dish_name(line):
            out.append(line.rstrip(".") + ":")
            have_dish = True
        elif have_dish and out:
            out[-1] = out[-1].rstrip() + " " + line
        elif _looks_like_bare_dish_name(line):
            out.append(line.rstrip(".") + ":")
            have_dish = True
        else:
            out.append(line)
            have_dish = True
    return "\n".join(out)


class RecipePortionAgent(BaseStrategyAgent):
    AGENT_NAME = "Recipe & Portion Specialist"
    AGENT_PORT = 8303
    AGENT_SYNOPSIS = "Finds real recipe ideas and grounds cafeteria portion sizing"
    AGENT_CAPABILITY_DETAIL = "Retrieves real recipes and ingredient data to propose cafeteria-scale portion guidance for a specific dish or a whole week's menu."
    WORKING_LABEL = "working out the recipes and portions"
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
        if _needs_unavailable_data(user_text):
            logger.info("[RecipePortion] Declining -- question needs recipe/prep history this system lacks")
            return {"text": _MISSING_DATA_DECLINE, "html": ""}

        single_serving = bool(_SINGLE_SERVING_RE.search(user_text))
        wants_full = bool(_FULL_SERVICE_RE.search(user_text))
        wants_recipe_view = bool(_RECIPE_VIEW_RE.search(user_text))
        # An explicit headcount the user stated ("for 4 people", "food for
        # four", "serves 12") is itself a request to scale to that number --
        # UNLESS this is the round-robin planning request, which also says
        # "for 450" but must stay one serving for Nutrition / Shopping List.
        is_planning = bool(_BROAD_PLANNING_SIGNAL.search(user_text))
        explicit_servings = None if is_planning else _explicit_servings(user_text)
        headcount_request = explicit_servings is not None

        single_dish_query = _dish_query(user_text)
        if single_dish_query and headcount_request:
            # "chicken curry for 4 people" -> search "chicken curry".
            single_dish_query = _STRIP_HEADCOUNT_RE.sub("", single_dish_query).strip()
        if single_dish_query and (
            _VAGUE_DISH_RE.match(single_dish_query.strip())
            or _VAGUE_SERVING_RE.match(single_dish_query.strip())
            or (headcount_request and _GENERIC_FOOD_RE.match(single_dish_query.strip()))
        ):
            single_dish_query = None  # "show me the recipes" / "food for four" -> whole menu

        if single_dish_query:
            scale = not single_serving and (wants_full or headcount_request)
            servings = (explicit_servings or _servings_from(user_text)) if scale else 1
            if servings > 1:
                return self._respond_for_one_dish(user_text, single_dish_query, servings=servings)
            return self._respond_for_one_dish(user_text, single_dish_query)

        saved_menu = self._observed_menus.get(self._current_conv_id, "")
        if saved_menu:
            dishes = _extract_dishes(saved_menu)
            if dishes:
                scale = not single_serving and (wants_full or wants_recipe_view or headcount_request)
                if not scale:
                    servings = 1
                elif explicit_servings is not None:
                    servings = explicit_servings
                else:
                    servings = _servings_from(user_text, saved_menu)
                if servings > 1:
                    return self._respond_for_whole_menu(saved_menu, dishes, servings=servings)
                return self._respond_for_whole_menu(saved_menu, dishes)

        # No specific dish named and no usable saved menu -- fall back to
        # general reasoning rather than doing nothing.
        user_message = f"""{self._history_block()}Menu idea: {user_text}

Data retrieved:
No recipe or nutrient data found -- use general culinary knowledge.

Please provide a concrete recipe with portion guidance for ONE serving of this dish."""
        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, **_LOOKUP)
        return {"text": text, "html": self._text_to_html_list(text)}

    @staticmethod
    def _apply_servings(text: str, servings: int) -> str:
        """One-serving writeup -> batch writeup for ``servings`` servings, with
        a leading marker the browser board keys on ("full service ...")."""
        if servings <= 1:
            return text
        return (
            f"Full service -- quantities to prepare {servings} servings of each dish, "
            f"scaled from the one-serving amounts:\n\n"
        ) + _scale_recipe_text(text, servings)

    def _respond_for_one_dish(self, user_text: str, query: str, servings: int = 1) -> dict:
        recipe_summary, nutrient_data = mcp_client.call_tools_parallel_sync([
            ("themealdb", "search_by_name", {"name": query[:60]}),
            ("usda_fdc", "search_food", {"query": query[:80], "limit": 2}),
        ], timeout=10.0)
        nutrient_data = _non_empty_results(nutrient_data)
        # search_by_name only found a candidate dish -- fetch that
        # match's real ingredients/instructions in a second lookup.
        recipe_data = _fetch_recipe_details(_non_empty_results(recipe_summary))
        if not recipe_data:
            # Retry with just the core identity word -- a full "Grilled
            # salmon with a lemon-pepper crust" won't match a TheMealDB
            # title, but "salmon" will.
            term = _core_term(query)
            if term and term != query.strip().lower():
                retry_summary = mcp_client.call_tool_sync_or_none("themealdb", "search_by_name", {"name": term})
                recipe_data = _fetch_recipe_details(_non_empty_results(retry_summary))

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

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, **_LOOKUP)
        text = self._apply_servings(text, servings)
        return {"text": text, "html": self._text_to_html_list(text)}

    def _respond_for_whole_menu(self, saved_menu: str, dishes: list[str], servings: int = 1) -> dict:
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

Please provide a concrete recipe with portion guidance (ingredient amounts needed) for ONE serving of EVERY dish in this week's menu.

Format: ONE line per dish -- the dish name, then a colon, then the
one-serving ingredient amounts, a short prep note, and the plate size, all
on that same line. The dish name before the colon must be 2 to 6 words with
no colon, comma, or line break inside it. Do not put a dish's amounts, prep,
or plate size on their own separate lines."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, timeout=45, **_LOOKUP)
        text = _normalize_menu_recipe_lines(text)
        text = self._apply_servings(text, servings)
        return {"text": text, "html": self._text_to_html_list(text)}


def main() -> None:
    agent = RecipePortionAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(RecipePortionAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
