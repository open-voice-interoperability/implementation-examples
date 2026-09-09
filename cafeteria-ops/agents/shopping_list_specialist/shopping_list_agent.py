#!/usr/bin/env python3
"""
Shopping List Specialist Agent — Cafeteria Ops Floor

Turns a week's finalized menu (dish names + headcount) into one
consolidated shopping list: real per-dish ingredient quantities summed
across the week and scaled to the headcount, with estimated costs.

Prefers the Recipe & Portion Specialist's already-determined one-serving
amounts (observed via Pass-Through broadcast, see on_observed_utterance)
whenever they're available in the conversation -- confirmed live that this
agent's own direct TheMealDB search frequently fails to match Menu
Designer's LLM-invented dish names (e.g. "Grilled Chicken Caesar Salad"
has no exact entry in TheMealDB's own catalog), producing "ingredients
could not be found" for dishes Recipe & Portion had already successfully
worked out (falling back to an LLM-derived recipe when its own TheMealDB
search also came up empty). Falls back to this agent's own direct
TheMealDB lookup only when Recipe & Portion hasn't been invited, or
hasn't replied yet, in this conversation.

When those saved recipes ARE available, the dish list itself is also
extracted from that writeup (see _extract_dishes_from_recipes), not from
the current utterance addressed to this agent -- confirmed live that the
utterance (often just the original planning request forwarded again by
the convener) could name the menu in a way that only yielded a partial
dish list, silently dropping every other dish (including meat) from the
resulting shopping list even though the saved recipe writeup had the
Menu Designer's real, complete week.

Port: 8310
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

# Most LLM calls here just parse or classify text, so they run on the
# smaller, cheaper "lookup" model tier. See llm_utils.LOOKUP_* / .env.
_LOOKUP = {"ollama_model": llm_utils.LOOKUP_OLLAMA_MODEL, "openai_model": llm_utils.LOOKUP_LLM_MODEL}

# The one exception: the consolidated shopping-list call multiplies every
# one-serving amount by the headcount and sums matching ingredients across
# every dish -- a dozen-plus multiply-and-add steps in a single pass. The
# lookup model gets that arithmetic wrong (confirmed live: 120g/serving x
# 100 people came back as 1.5kg instead of 12kg, and whole ingredients
# were dropped from the list), so this call keeps the full analysis model.
_SCALING = {}  # empty -> llm_utils defaults to the full OLLAMA_MODEL / LLM_MODEL

logger = logging.getLogger(__name__)

# Hardcoded to match agents/recipe_portion_specialist/recipe_portion_agent.py's
# own AGENT_PORT -- cafeteria-ops agents use serviceUrl == speakerUri ==
# "http://127.0.0.1:<port>/" throughout, and each agent file is
# self-contained (no cross-agent imports), so this is kept in sync by hand
# like every other agent's port number in this project.
_RECIPE_PORTION_SERVICE_URL = "http://127.0.0.1:8303/"

# A week's menu arrives as free text ("Day 1: Grilled Chicken Caesar Salad,
# Day 2: ..."), not a clean list -- day labels, dish names, and an optional
# headcount are all mixed into one sentence or paragraph. Regex extraction
# (the pattern used elsewhere in this project for a single dish/food/
# commodity name) doesn't generalize to "pull out an unknown number of
# distinct dish names", so this is a genuine LLM extraction step rather
# than a shortcut around one.
_EXTRACTION_SYSTEM_PROMPT = """You extract structured menu data from a cafeteria planning message.

Identify every distinct DISH mentioned (a specific food item someone would
cook -- e.g. "Grilled Chicken Caesar Salad", "Beef and Vegetable Stir-Fry").
Ignore day labels ("Day 1:"), serving/operational notes, and anything that
isn't an actual dish name.

Also identify the headcount (number of people/lunches/meals/servings) if a
number is given for that.

Respond with ONLY a single JSON object and no other text:
{"dishes": ["<dish name>", ...], "headcount": <integer or null>}
"""

# Used only when the message never states a headcount -- matches this
# project's own recurring example prompts, not a hidden assumption about
# the real cafeteria's size.
DEFAULT_HEADCOUNT = 450

SYSTEM_PROMPT = """You are the Shopping List Specialist for a corporate cafeteria planning panel.
Your job is to turn a week's finalized menu into ONE consolidated shopping
list: how much of each ingredient to buy in total, and an estimated cost.

You will be given real one-serving ingredient/quantity data for each dish
in the menu (either already worked out by the Recipe & Portion Specialist,
or looked up directly from TheMealDB), plus the target headcount.

Work this out in two passes internally, but only show the reader the
result of pass 2 -- never print the words "pass 1"/"pass 2", any
intermediate per-dish math, or scratch work; the visible response is the
final list ONLY.

Pass 1 (internal): build one merged ingredient list across ALL dishes.
For EVERY ingredient of EVERY dish, multiply its one-serving amount by the
headcount exactly -- total = per-serving amount x headcount (e.g. 120 g per
serving x 100 people = 12000 g). Do this for every ingredient; never skip a
dish or an ingredient, and never leave an amount near its one-serving size.
Treat two ingredient names as the SAME ingredient whenever they refer to
the same thing regardless of capitalization, singular/plural, or minor
wording ("Onions", "onion", "diced onions" are all one ingredient: onions).
THEN add matching ingredients from different dishes into one running total
each. There must be exactly one entry per distinct ingredient -- if you
notice two entries that are the same ingredient, merge them (normalize
compatible units first, e.g. grams and kg; only keep an ingredient as two
lines if the units genuinely can't be combined, e.g. "2 cloves" vs "500g").
Give each total in a sensible bulk unit: grams as kilograms once over
1000 g, millilitres as litres once over 1000 ml, and teaspoons/tablespoons
converted to cups or litres when the count is large. Keep count-based items
(eggs, scallops, cloves of garlic, whole lemons) as plain counts.

Pass 2 (internal): for each entry in that merged list, estimate a
reasonable wholesale/bulk grocery cost for the total quantity, using your
general knowledge of typical ingredient prices -- state plainly that costs
are estimates, not looked-up prices.

If a dish's ingredient data is missing (not found), name the dish and say
its ingredients could not be found -- do not silently drop it or invent a
recipe for it.

Visible output: one line per merged ingredient, nothing else --
"<ingredient>: <total quantity> (~$<cost>)", ending with a final line
"Estimated total: ~$<sum>". Plain text only -- no markdown, bold, or
bullet characters, no headers, no explanation of your method."""

# Grouping the shopping list by grocery category is handled as a SEPARATE
# structured step (see _categorize_ingredients/_group_by_category below),
# not folded into SYSTEM_PROMPT above -- confirmed live that asking the
# main call to both merge/cost AND group by category in one pass let
# ingredients silently duplicate across categories (the same ingredient
# appearing under two different headers, inflating the effective total),
# even after tightening that instruction. Classifying the ALREADY-merged
# ingredient names in a small, separate JSON call, then grouping the
# already-generated lines in Python, guarantees each line appears in
# exactly one category by construction.
CATEGORIES = [
    "Produce", "Meat & Poultry", "Seafood", "Dairy & Eggs", "Grains & Bakery",
    "Pantry & Dry Goods", "Condiments & Sauces", "Frozen", "Other",
]

# Cost-by-category chart colors (see _build_cost_chart below) -- the
# dataviz skill's validated 8-hue categorical order (blue, orange, aqua,
# yellow, magenta, green, violet, red; adjacent-pair CVD-safe on a light
# surface), assigned by CATEGORY NAME rather than by position among
# whichever categories happen to be present in a given response, so a
# category's color never shifts when other categories are absent. There
# are exactly 8 real categories above plus "Other" as a 9th -- the skill
# is explicit that a 9th series should never get a generated hue but
# should fold into "Other" instead, which is already this list's own
# catch-all, so "Other" gets the muted chart ink rather than a 9th hue.
_CATEGORY_COLORS: dict[str, str] = {
    "Produce": "#2a78d6",
    "Meat & Poultry": "#eb6834",
    "Seafood": "#1baf7a",
    "Dairy & Eggs": "#eda100",
    "Grains & Bakery": "#e87ba4",
    "Pantry & Dry Goods": "#008300",
    "Condiments & Sauces": "#4a3aa7",
    "Frozen": "#e34948",
    "Other": "#898781",
}

_CATEGORIZE_SYSTEM_PROMPT = f"""Classify each grocery ingredient name into exactly ONE of these categories:
{', '.join(CATEGORIES)}.

Fresh vegetables, fruits, and fresh herbs belong in Produce. Raw meat and
poultry belong in Meat & Poultry. Raw/fresh fish and shellfish belong in
Seafood. Milk, cheese, butter, yogurt, and eggs belong in Dairy & Eggs.
Bread, pasta, rice, flour, and baked goods belong in Grains & Bakery.
Canned goods, dried spices, oils, sugar, and other shelf-stable staples
belong in Pantry & Dry Goods. Dressings, sauces, and condiments belong in
Condiments & Sauces. Anything frozen belongs in Frozen. Use Other only
when nothing else genuinely fits.

Respond with ONLY a single JSON object mapping each given ingredient name
(exactly as given, as the key) to one category name (as the value), and
no other text: {{"<ingredient name>": "<category>", ...}}
"""

# The final total line. "Estimated total: ~$X" is what SYSTEM_PROMPT asks
# for, but the model also writes "Total: $X", "Grand total ~$X",
# "Total cost: $X" -- all mean the same final figure and must be captured
# as the total, not dropped as noise or parsed as an ingredient.
_TOTAL_LINE_PATTERN = re.compile(
    r"^\s*(?:estimated|grand|approx\.?|approximate|overall|final)?\s*total(?:\s+(?:estimated\s+)?cost)?\s*:?\s*~?\$?",
    re.IGNORECASE,
)
# Matched by content ("could not be found" appearing anywhere in the
# line), not just the exact "Dishes with no ingredient data found: ..."
# phrasing the SYSTEM_PROMPT asks for -- confirmed live that the model
# sometimes phrases this as one line per dish instead ("<Dish>: Ingredients
# could not be found."), which still contains a colon and would otherwise
# be treated as a real ingredient line and dumped into "Other".
_NOT_FOUND_LINE_PATTERN = re.compile(r"^Dishes with no\b|could not be found", re.IGNORECASE)
# Summary lines the model sometimes adds on its own -- a per-plate/per-
# serving average, a running subtotal, a restated grand total. This agent
# computes the total and the per-plate average deterministically (see
# _recompute_total_line / _average_cost_per_plate_line), so any such line
# from the model is dropped: kept, they were parsed as fake "ingredients"
# ("Average cost per plate: ~$2.31" landing under a category) AND left the
# response with two disagreeing per-plate figures next to the real total.
_SUMMARY_NOISE_PATTERN = re.compile(
    r"^\s*(?:the\s+)?(?:average|avg\.?|mean|approximate|approx\.?|overall|estimated)?\s*"
    r"(?:cost|price|spend|amount)\s+per\s+"
    r"(?:plate|serving|portion|meal|person|head|cover|dish|day|week)\b"
    r"|^\s*(?:cost|price)\s+per\s+(?:plate|serving|portion|meal|person|head)\b"
    r"|^\s*per[-\s](?:plate|serving|portion|person)\s+(?:cost|price)\b"
    r"|^\s*(?:sub-?total|running\s+total)\b",
    re.IGNORECASE,
)


def _parse_ingredient_lines(text: str) -> tuple[list[tuple[str, str]], list[str], str]:
    """Split the flat merge/cost pass's output into (name, full_line)
    ingredient pairs, any other non-ingredient lines (e.g. a "Dishes with
    no ingredient data found" note), and the final total line -- so the
    ingredient lines alone can be grouped by category afterward without
    disturbing anything else in the response."""
    ingredient_lines: list[tuple[str, str]] = []
    other_lines: list[str] = []
    total_line = ""
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if _TOTAL_LINE_PATTERN.match(line):
            total_line = line
            continue
        if _NOT_FOUND_LINE_PATTERN.search(line):
            other_lines.append(line)
            continue
        if _SUMMARY_NOISE_PATTERN.match(line):
            # the model's own per-plate/subtotal line -- we recompute these
            continue
        if ":" in line:
            name = line.split(":", 1)[0].strip()
            ingredient_lines.append((name, line))
        else:
            other_lines.append(line)
    return ingredient_lines, other_lines, total_line


def _dedupe_ingredient_lines(ingredient_lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop exact-duplicate ingredient lines -- same name AND same
    quantity/cost, differing at most in whitespace or case -- confirmed
    live that the main merge pass sometimes emits the identical line
    twice in a row for the same ingredient (e.g. "garlic: 150 g (~$15)"
    appearing twice) despite the SYSTEM_PROMPT's "exactly one entry per
    distinct ingredient" instruction. Genuinely different quantities for
    the same ingredient name are left alone -- reconciling those would
    mean summing across possibly-incompatible units, a harder problem
    this does not attempt to solve, and silently dropping one such line
    could undercount the true total."""
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for name, line in ingredient_lines:
        key = re.sub(r"\s+", " ", line.strip()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, line))
    return deduped


_LINE_COST_PATTERN = re.compile(r"\(~\$([\d,]+(?:\.\d+)?)\)\s*$")

# Deterministic unit roll-up for a per-ingredient line's quantity. The
# scaling model now multiplies reliably (see _SCALING) but still prints the
# raw scaled figure -- "5000g", "100 tbsp" -- rather than a bulk unit. This
# converts the leading "<number> <unit>" of a line's quantity into a
# sensible bulk unit; anything it doesn't recognise (count-based items like
# "100 cloves", or non-numeric amounts like "Pinch" / "Juice of 50 limes")
# is left exactly as written.
_QTY_SEGMENT_RE = re.compile(r"^(.*?:\s*)(.*?)(\s*\(~\$[\d,]+(?:\.\d+)?\)\s*)$")
_LEADING_QTY_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([A-Za-z]+)\b(.*)$")
_ML_PER_UNIT = {
    "tsp": 4.92892, "teaspoon": 4.92892, "teaspoons": 4.92892,
    "tbsp": 14.7868, "tablespoon": 14.7868, "tablespoons": 14.7868,
    "cup": 236.588, "cups": 236.588,
}


def _fmt_qty_number(value: float) -> str:
    """Trim a rolled-up quantity to at most 2 decimals, no trailing zeros."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _roll_up_amount(number: float, unit: str) -> tuple[float, str] | None:
    """(new_number, new_unit) for a quantity worth expressing in a larger
    unit, or None to leave it as written."""
    u = unit.lower()
    if u in ("g", "gram", "grams", "gm", "gms") and number >= 1000:
        return number / 1000, "kg"
    if u == "mg" and number >= 1000:
        return number / 1000, "g"
    if u in ("ml", "milliliter", "milliliters", "millilitre", "millilitres") and number >= 1000:
        return number / 1000, "L"
    if u in _ML_PER_UNIT:
        millilitres = number * _ML_PER_UNIT[u]
        if millilitres >= 1000:
            return millilitres / 1000, "L"
        if millilitres >= 240:
            return millilitres / 236.588, "cups"
        return None  # a small volume -- leave the spoons as written
    if u in ("oz", "ounce", "ounces") and number >= 16:
        return number / 16, "lb"
    return None


def _roll_up_line(line: str) -> str:
    """Rewrite one "<ingredient>: <qty> (~$<cost>)" line's quantity into a
    bulk unit where that helps; return it unchanged otherwise (no cost
    suffix, non-numeric quantity, or a unit not worth converting)."""
    segments = _QTY_SEGMENT_RE.match(line)
    if not segments:
        return line
    prefix, quantity, cost = segments.groups()
    leading = _LEADING_QTY_RE.match(quantity.strip())
    if not leading:
        return line
    number_text, unit, rest = leading.groups()
    try:
        number = float(number_text.replace(",", ""))
    except ValueError:
        return line
    rolled = _roll_up_amount(number, unit)
    if rolled is None:
        return line
    new_number, new_unit = rolled
    return f"{prefix}{_fmt_qty_number(new_number)} {new_unit}{rest}{cost}"


def _format_dollars(amount: float) -> str:
    """"$23" for a whole number, "$23.50" for a fractional one -- never a
    trailing ".00"."""
    formatted = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"${formatted}"


# The Recipe & Portion Specialist now hands back a whole-menu writeup that
# is ALREADY scaled to a headcount when it was asked for one directly ("for
# 4 people"), prefixed "Full service -- quantities to prepare N servings ...".
# This agent's prompt then treats those amounts as one-serving and
# multiplies by the headcount AGAIN -- a 4x-too-big shopping list. Detect
# that marker and divide the amounts back to one serving first, so the
# scaling pass multiplies exactly once from clean per-serving data.
_BATCH_MARKER_RE = re.compile(r"\b(?:quantities to prepare|prepare)\s+(\d{1,6})\s+servings?\b", re.IGNORECASE)
_BATCH_PREAMBLE_RE = re.compile(r"\A\s*full[\s-]?service\b[^\n]*(?:\n\s*)+", re.IGNORECASE)
_RESCALE_MASS_G = {"g": 1, "gram": 1, "grams": 1, "gm": 1, "gms": 1,
                   "kg": 1000, "kilo": 1000, "kilos": 1000, "kilogram": 1000, "kilograms": 1000, "mg": 0.001}
_RESCALE_VOL_ML = {"ml": 1, "milliliter": 1, "milliliters": 1, "millilitre": 1, "millilitres": 1,
                   "l": 1000, "liter": 1000, "liters": 1000, "litre": 1000, "litres": 1000}
_RESCALE_COUNT = {"tsp", "tbsp", "teaspoon", "teaspoons", "tablespoon", "tablespoons", "cup", "cups",
                  "clove", "cloves", "slice", "slices", "sprig", "sprigs", "can", "cans", "stick", "sticks",
                  "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds"}
_RESCALE_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)(\s*)([A-Za-z]+)\b")


def _rescale_amounts(text: str, factor: float) -> str:
    """Multiply every "<number> <food-unit>" in a recipe writeup by factor
    (used here with factor < 1 to divide a batch writeup back to one
    serving), rolling mass/volume down to g/ml when the result drops below
    1 kg / 1 L. Times ("3 min"), temperatures ("400 F"), dimensions ("1
    inch") and a per-plate figure carry no food unit / are left alone."""
    def repl(match: re.Match) -> str:
        after = text[match.end():match.end() + 18].lower()
        if any(w in after for w in ("plate", "bowl", "per serving", "serving size", "portion size", "per plate", "per bowl")):
            return match.group(0)
        num, spacer, unit_raw = match.group(1), match.group(2), match.group(3)
        unit = unit_raw.lower()
        value = float(num) * factor
        if unit in _RESCALE_MASS_G:
            grams = value * _RESCALE_MASS_G[unit]
            return f"{_fmt_qty_number(grams / 1000)} kg" if grams >= 1000 else f"{_fmt_qty_number(grams)} g"
        if unit in _RESCALE_VOL_ML:
            millilitres = value * _RESCALE_VOL_ML[unit]
            return f"{_fmt_qty_number(millilitres / 1000)} L" if millilitres >= 1000 else f"{_fmt_qty_number(millilitres)} ml"
        if unit in _RESCALE_COUNT:
            return f"{_fmt_qty_number(value)}{spacer}{unit_raw}"
        return match.group(0)

    return _RESCALE_QTY_RE.sub(repl, text)


def _to_one_serving(recipe_text: str) -> tuple[str, int]:
    """(one-serving writeup, N) -- if `recipe_text` was already scaled to N
    servings (Recipe & Portion's "Full service -- quantities to prepare N
    servings ..." preamble), divide it back and drop the preamble; N is 1
    when it was not a batch writeup."""
    m = _BATCH_MARKER_RE.search(recipe_text or "")
    if not m:
        return recipe_text, 1
    n = int(m.group(1))
    if n <= 1:
        return recipe_text, 1
    body = _BATCH_PREAMBLE_RE.sub("", recipe_text, count=1)
    return _rescale_amounts(body, 1.0 / n), n


def _recompute_total_line(ingredient_lines: list[tuple[str, str]]) -> str | None:
    """Sum each line's own "(~$X)" cost -- used to correct the model's
    separately-stated total after a duplicate line is removed, so the
    displayed total stays consistent with what's actually shown rather
    than silently including a line that's no longer there. Returns None
    (caller should fall back to the model's own total line) if any
    line's cost can't be parsed, rather than showing a partial sum as if
    it were the true total."""
    total = 0.0
    for _name, line in ingredient_lines:
        match = _LINE_COST_PATTERN.search(line)
        if not match:
            return None
        total += float(match.group(1).replace(",", ""))
    return f"Estimated total: ~{_format_dollars(total)}"


_TOTAL_DOLLARS_PATTERN = re.compile(r"~\$([\d,]+(?:\.\d+)?)")


def _parse_total_dollars(total_line: str) -> float | None:
    """The numeric amount out of a total line ("Estimated total: ~$1234"
    -> 1234.0), or None if it can't be parsed -- distinct from
    _LINE_COST_PATTERN, which matches a per-ingredient line's
    "(~$X)" (parenthesized, mid-line), not the total line's own
    "~$X" (no parens, at the end)."""
    match = _TOTAL_DOLLARS_PATTERN.search(total_line)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _average_cost_per_plate_line(total_line: str, headcount: int) -> str:
    """"Average cost per plate: ~$X.XX", computed deterministically from
    the (possibly post-dedup-recomputed) total line and the target
    headcount -- never left for the model to compute itself, matching
    this project's established pattern of doing arithmetic in code
    rather than trusting the LLM with it (see e.g. the per-item word
    budget hints elsewhere in this project). Returns "" if the total
    can't be parsed or headcount isn't positive, rather than showing a
    bogus figure."""
    if not total_line or headcount <= 0:
        return ""
    total = _parse_total_dollars(total_line)
    if total is None:
        return ""
    return f"Average cost per plate: ~{_format_dollars(total / headcount)}"


def _category_cost_totals(sections: list[tuple[str, list[str]]]) -> list[tuple[str, float]]:
    """(category, total $ cost) for each category, summing whatever
    per-line costs are parseable. Deliberately more lenient than
    _recompute_total_line: a chart bar is an approximate visual aid, so
    one line with an unparseable cost just contributes 0 to its
    category's bar rather than voiding the whole chart."""
    totals = []
    for category, lines in sections:
        total = 0.0
        for line in lines:
            match = _LINE_COST_PATTERN.search(line)
            if match:
                total += float(match.group(1).replace(",", ""))
        totals.append((category, total))
    return totals


def _build_cost_chart(sections: list[tuple[str, list[str]]]) -> str:
    """Horizontal bar chart of total cost per grocery category, as a
    base64 PNG <img> tag -- reuses the same render_bar_chart_png helper
    nutrition_agent.py's own chart already uses. Colors come from
    _CATEGORY_COLORS, keyed by category NAME rather than by position
    among whichever categories happen to be present, so a category's
    color never shifts depending on what else is in a given week's
    menu. Categories in canonical CATEGORIES order (same order as the
    list below it), not sorted by cost, so the chart and the list read
    as one coherent view rather than two independently-ordered ones."""
    totals = [(category, cost) for category, cost in _category_cost_totals(sections) if cost > 0]
    if not totals:
        return ""

    max_cost = max(cost for _, cost in totals)
    max_bar_w = 200
    rows = [
        (
            category,
            round(cost / max_cost * max_bar_w),
            f"~{_format_dollars(cost)}",
            _CATEGORY_COLORS.get(category, _CATEGORY_COLORS["Other"]),
        )
        for category, cost in totals
    ]
    return render_bar_chart_png(
        "Cost by Category", rows,
        row_h=36, top=32, bar_h=20,
        alt="Shopping list cost by category chart",
    )


def _categorize_ingredients(names: list[str]) -> dict[str, str]:
    """name -> one of CATEGORIES, via a small structured classification
    call. Only entries with a name AND a category from the fixed CATEGORIES
    list are kept -- anything else (missing key, invalid category, parse
    failure) is left for the caller to default to "Other"."""
    if not names:
        return {}
    raw = llm_utils.chat_sync(_CATEGORIZE_SYSTEM_PROMPT, json.dumps(names), temperature=0, timeout=20, **_LOOKUP)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        name: category for name, category in parsed.items()
        if isinstance(name, str) and isinstance(category, str) and category in CATEGORIES
    }


def _build_category_sections(text: str) -> tuple[list[tuple[str, list[str]]], list[str], str]:
    """Parse + categorize a flat merge/cost response into (category, lines)
    pairs -- only non-empty categories, in canonical CATEGORIES order --
    plus any other non-ingredient lines and the final total line. This is
    the single shared step both the plain-text and HTML renderers build
    from (see _render_text_from_sections/_render_html_from_sections
    below), so the actual grouping call happens exactly once per response
    and both renderings stay consistent with each other, instead of each
    re-running its own categorization pass."""
    ingredient_lines, other_lines, total_line = _parse_ingredient_lines(text)
    deduped_lines = _dedupe_ingredient_lines(ingredient_lines)
    if len(deduped_lines) != len(ingredient_lines):
        total_line = _recompute_total_line(deduped_lines) or total_line
    # Roll each quantity up to a bulk unit AFTER dedup/total (costs are
    # untouched, so the total stays correct) and BEFORE categorization
    # (the ingredient name is unchanged, so grouping is unaffected).
    ingredient_lines = [(name, _roll_up_line(line)) for name, line in deduped_lines]
    if not ingredient_lines:
        return [], other_lines, total_line

    category_of = _categorize_ingredients([name for name, _ in ingredient_lines])

    grouped: dict[str, list[str]] = {category: [] for category in CATEGORIES}
    for name, line in ingredient_lines:
        grouped[category_of.get(name, "Other")].append(line)

    sections = [(category, grouped[category]) for category in CATEGORIES if grouped[category]]
    return sections, other_lines, total_line


def _render_text_from_sections(
    sections: list[tuple[str, list[str]]], other_lines: list[str], total_line: str, fallback_text: str, headcount: int
) -> str:
    """Plain-text rendering: one section per category, in canonical order,
    each ingredient on its own line -- built entirely in code from the
    already-generated lines plus a name->category mapping, so no
    ingredient can end up duplicated across two categories the way
    letting the model regroup its own list did. The average-cost-per-
    plate figure (see _average_cost_per_plate_line) follows the total
    line when both are available."""
    if not sections:
        return fallback_text

    parts = [f"{category}:\n" + "\n".join(lines) for category, lines in sections]
    output = "\n".join(parts)
    if other_lines:
        output += ("\n" if output else "") + "\n".join(other_lines)
    if total_line:
        output += ("\n" if output else "") + total_line
        per_plate_line = _average_cost_per_plate_line(total_line, headcount)
        if per_plate_line:
            output += "\n" + per_plate_line
    return output


def _render_html_from_sections(
    sections: list[tuple[str, list[str]]], other_lines: list[str], total_line: str, headcount: int
) -> str:
    """HTML rendering of the same structured sections: bold category
    names, one ingredient per line as a real list item (<li>), for the
    "html" feature -- shown in the browser's Analysis report popup
    alongside the plain-text "text" feature, same as the chart other
    agents (e.g. Nutrition) already attach there. The average-cost-per-
    plate figure follows the total line when both are available."""
    if not sections:
        return ""

    parts = []
    for category, lines in sections:
        items = "".join(f"<li>{escape(line)}</li>" for line in lines)
        parts.append(f"<p><strong>{escape(category)}</strong></p><ul>{items}</ul>")
    if other_lines:
        parts.append("<p>" + "<br>".join(escape(line) for line in other_lines) + "</p>")
    if total_line:
        parts.append(f"<p><strong>{escape(total_line)}</strong></p>")
        per_plate_line = _average_cost_per_plate_line(total_line, headcount)
        if per_plate_line:
            parts.append(f"<p><strong>{escape(per_plate_line)}</strong></p>")
    return "".join(parts)


def _categorized_response(raw: str, headcount: int) -> dict:
    """{"text": ..., "html": ...} for a flat merge/cost response, built
    from ONE categorization pass shared by both renderings (see
    _build_category_sections) so the text, the HTML list, and the cost
    chart all agree on which category each ingredient landed in. The
    chart is prepended above the list in "html" -- a quick visual first,
    the full per-ingredient detail right below it. headcount drives the
    average-cost-per-plate line appended after the total in both
    renderings."""
    sections, other_lines, total_line = _build_category_sections(raw)
    chart_html = _build_cost_chart(sections)
    list_html = _render_html_from_sections(sections, other_lines, total_line, headcount)
    return {
        "text": _render_text_from_sections(sections, other_lines, total_line, raw, headcount),
        "html": chart_html + list_html,
    }


def _extract_menu(user_text: str) -> dict:
    raw = llm_utils.chat_sync(_EXTRACTION_SYSTEM_PROMPT, user_text, temperature=0, timeout=15, **_LOOKUP)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {"dishes": [], "headcount": None}
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return {"dishes": [], "headcount": None}
    dishes = [d.strip() for d in (parsed.get("dishes") or []) if isinstance(d, str) and d.strip()]
    headcount = parsed.get("headcount")
    headcount = headcount if isinstance(headcount, int) and headcount > 0 else None
    return {"dishes": dishes, "headcount": headcount}


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


def _extract_dishes_from_recipes(recipe_text: str) -> list[str]:
    """LLM-based extraction of the distinct dish names from the Recipe &
    Portion Specialist's saved whole-menu writeup -- same shape as
    recipe_portion_agent.py's own _extract_dishes and nutrition_agent.py's/
    procurement_agent.py's copies, kept as a separate local copy since
    each cafeteria-ops agent is self-contained.

    Used instead of _extract_menu's dish list whenever saved_recipes is
    available: _extract_menu works off the CURRENT utterance addressed to
    this agent, which the convener often forwards as the ORIGINAL planning
    request text -- confirmed live that when that request phrased the
    menu as one compound line, only the salad portion of it was extracted
    as "the dish," silently dropping every other dish (including any
    meat) even though saved_recipes had the Menu Designer's real, complete
    week. saved_recipes is the authoritative source of what dishes exist,
    same reasoning as every other specialist's own on_observed_utterance
    hook in this project."""
    raw = llm_utils.chat_sync(_DISH_EXTRACTION_SYSTEM_PROMPT, recipe_text, temperature=0, timeout=15, **_LOOKUP)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [d.strip() for d in (parsed.get("dishes") or []) if isinstance(d, str) and d.strip()]


def _fetch_dish_ingredients(dishes: list[str]) -> dict[str, dict | None]:
    """dish name -> {"meal_name": str, "ingredients": [str, ...]}, or None
    when no match was found. Two rounds are needed because TheMealDB's name
    search only returns a summary (id/name/category) -- the real
    ingredients list comes from a second, per-meal-id lookup."""
    if not dishes:
        return {}

    search_requests = [("themealdb", "search_by_name", {"name": dish[:60]}) for dish in dishes]
    search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=10.0)

    top_match: dict[str, tuple[str, str]] = {}  # dish -> (meal_id, meal_name)
    for dish, raw in zip(dishes, search_results):
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        results = parsed.get("results") or []
        if results and results[0].get("id"):
            top_match[dish] = (results[0]["id"], results[0].get("name") or dish)

    # Dedupe by meal_id: two dish names can match the same TheMealDB
    # recipe. Keep the first dish (menu order); the rest stay None so the
    # same ingredient list isn't summed into the shopping list twice.
    claimed: set[str] = set()
    for dish in dishes:
        pair = top_match.get(dish)
        if pair is None:
            continue
        if pair[0] in claimed:
            del top_match[dish]
        else:
            claimed.add(pair[0])

    output: dict[str, dict | None] = {dish: None for dish in dishes}
    if not top_match:
        return output

    detail_requests = [("themealdb", "get_recipe_details", {"meal_id": meal_id}) for meal_id, _ in top_match.values()]
    detail_results = mcp_client.call_tools_parallel_sync(detail_requests, timeout=10.0)

    for (dish, (_meal_id, meal_name)), raw in zip(top_match.items(), detail_results):
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ingredients = parsed.get("ingredients") or []
        if ingredients:
            output[dish] = {"meal_name": meal_name, "ingredients": ingredients}
    return output


class ShoppingListAgent(BaseStrategyAgent):
    AGENT_NAME = "Shopping List Specialist"
    AGENT_PORT = 8310
    AGENT_SYNOPSIS = "Aggregates a week's menu into ingredient quantities and estimated costs"
    AGENT_CAPABILITY_DETAIL = "Sums real per-dish ingredient quantities across a week's menu into one shopping list with estimated costs."
    WORKING_LABEL = "totalling up the shopping list"
    AGENT_KEYPHRASES = ["shopping list", "grocery list", "how much", "ingredients needed",
                         "quantities", "buy", "order", "purchase list"]
    # BaseStrategyAgent's default of 50 words is a single-item budget --
    # this is the value that actually governs the final hard truncation
    # whenever convener delegates a question, since convener only embeds
    # the UI slider's value as advisory text, never as the maxWords
    # feature this reads. A full week's consolidated list can have many
    # more distinct ingredient lines than there are dishes -- 400 gives
    # it room for a genuinely complete list instead of getting cut off
    # partway through.
    MAX_RESPONSE_WORDS = 400

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
            logger.info("[ShoppingList] Saved Recipe & Portion's one-serving recipes for conv %s", conv_id)

    def process_utterance(self, user_text: str) -> dict | str:
        menu = _extract_menu(user_text)
        headcount = menu["headcount"] or DEFAULT_HEADCOUNT
        headcount_note = "" if menu["headcount"] else f" (no headcount given in the message -- assuming {DEFAULT_HEADCOUNT})"

        # Prefer the dish list from Recipe & Portion's own saved writeup
        # (the Menu Designer's real, complete week) over re-extracting
        # dishes from the current utterance -- that utterance is often
        # just the original planning request forwarded again, which can
        # name the menu in a way that only yields a partial dish list
        # (see _extract_dishes_from_recipes's docstring).
        saved_recipes = self._observed_recipes.get(self._current_conv_id, "")
        if saved_recipes:
            dishes = _extract_dishes_from_recipes(_BATCH_PREAMBLE_RE.sub("", saved_recipes, count=1))
            if dishes:
                return self._respond_from_recipe_portion(dishes, headcount, headcount_note, saved_recipes)

        dishes = menu["dishes"]
        if not dishes:
            return ("I couldn't identify any specific dishes in that message -- please list the "
                    "week's dishes (e.g. \"Day 1: Grilled Chicken Caesar Salad, Day 2: ...\") so I "
                    "can total up ingredient quantities and estimate costs.")

        return self._respond_from_themealdb(dishes, headcount, headcount_note)

    def _respond_from_recipe_portion(self, dishes: list[str], headcount: int, headcount_note: str, saved_recipes: str) -> dict:
        # If Recipe & Portion already scaled its writeup to a headcount,
        # divide it back to one serving so the scaling pass below multiplies
        # exactly once (not twice).
        saved_recipes, already_scaled_to = _to_one_serving(saved_recipes)
        if already_scaled_to > 1:
            logger.info(
                "[ShoppingList] Recipe & Portion writeup was pre-scaled to %d servings; "
                "divided back to one serving before scaling to %d",
                already_scaled_to, headcount,
            )

        user_message = f"""{self._history_block()}Week's menu ({len(dishes)} dishes) for {headcount} people{headcount_note}:
{', '.join(dishes)}

Real one-serving ingredient amounts already determined by the Recipe & Portion Specialist:
{saved_recipes}

Please produce one consolidated shopping list (total quantity + estimated cost per ingredient) scaled to {headcount} people."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, timeout=45, **_SCALING)
        return _categorized_response(raw, headcount)

    def _respond_from_themealdb(self, dishes: list[str], headcount: int, headcount_note: str) -> dict:
        ingredient_data = _fetch_dish_ingredients(dishes)
        found = {dish: data for dish, data in ingredient_data.items() if data}
        not_found = [dish for dish, data in ingredient_data.items() if not data]

        context = "\n".join(
            f'{data["meal_name"]}: {json.dumps(data["ingredients"])}' for data in found.values()
        ) or "No ingredient data found for any dish."
        not_found_note = f"\nDishes with no ingredient data found: {', '.join(not_found)}" if not_found else ""

        user_message = f"""{self._history_block()}Week's menu ({len(dishes)} dishes) for {headcount} people{headcount_note}:
{', '.join(dishes)}

Real per-serving ingredient data retrieved from TheMealDB:
{context}
{not_found_note}

Please produce one consolidated shopping list (total quantity + estimated cost per ingredient) scaled to {headcount} people."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message, timeout=45, **_SCALING)
        return _categorized_response(raw, headcount)


def main() -> None:
    agent = ShoppingListAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(ShoppingListAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
