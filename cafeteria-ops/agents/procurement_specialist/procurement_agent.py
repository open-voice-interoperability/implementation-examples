#!/usr/bin/env python3
"""
Procurement Specialist Agent — Cafeteria Ops Floor

Grounds sourcing/procurement recommendations in real USDA AMS wholesale
commodity price data. Also remembers the Recipe & Portion Specialist's
one-serving recipe writeup (broadcast to it via Pass-Through, see
on_observed_utterance below) so a broad planning question (no single
commodity named) can still be grounded in real market data for every
commodity the actual menu uses, instead of falling back to ungrounded
general advice just because the question itself didn't name an
ingredient -- confirmed live this was the gap: a five-day-menu planning
question always fell through to "No matching USDA market data found",
even in a conversation where Recipe & Portion had already produced a
real, specific ingredient list.

Falls back to a real web search (Tavily, see mcp/web_search_mcp.py) for
any commodity/ingredient USDA AMS has no wholesale report for -- USDA
AMS only tracks bulk commodities (livestock, dairy, produce, grain), so
specialty or manufactured items (quinoa, shrimp, soy sauce) never match
there no matter what search term is tried, even though they genuinely do
have real, findable retail prices online. The web search results are
handed to the LLM as retrieved context, same as USDA data -- the model
itself has no live internet access via a plain chat completion, so it
was never actually able to act on the whole-menu prompt's earlier
"search for current grocery-store product information" instruction; that
was quietly asking for a capability that didn't exist until this.

Port: 8306
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

# Hardcoded to match agents/recipe_portion_specialist/recipe_portion_agent.py's
# own AGENT_PORT -- cafeteria-ops agents use serviceUrl == speakerUri ==
# "http://127.0.0.1:<port>/" throughout, and each agent file is
# self-contained (no cross-agent imports), so this is kept in sync by hand
# like every other agent's port number in this project.
_RECIPE_PORTION_SERVICE_URL = "http://127.0.0.1:8303/"

# The maxWords slider's instruction, appended by convener._question_text
# whenever the UI's maxWords != the no-instruction default -- present on
# almost every real request, so it must be stripped before judging what
# commodity (if any) the ORIGINAL question names.
_MAX_WORDS_INSTRUCTION = re.compile(r"\n\n\[Write approximately[\s\S]*$", re.IGNORECASE)
_ADDRESS_PREFIX = re.compile(r"^[^,]{0,40},\s*", re.IGNORECASE)
_REQUEST_FRAMING = re.compile(
    r"\b(what'?s the (market )?price (of|for)|"
    r"market (price|conditions|data) for|buying (guidance|advice) for|"
    r"sourcing (guidance|advice) for|assess|evaluate|analy[sz]e)\b",
    re.IGNORECASE,
)
# "how much does X cost" needs its "how much does"/"cost" halves stripped
# SEPARATELY (anchored to the start/end), not as one non-greedy regex
# spanning "does...cost" -- that single-regex version (previously part of
# _REQUEST_FRAMING above) matched the ENTIRE span between them, silently
# eating the commodity name itself along with the framing (confirmed
# live: "How much does chicken breast cost?" -> None, not "chicken
# breast" -- there's no second "cost" anywhere else in the string for
# the non-greedy .*? to stop short at).
_LEADING_HOW_MUCH_DOES = re.compile(r"^\s*how much does\s+", re.IGNORECASE)
_TRAILING_COST = re.compile(r"\s+cost[ ?.!]*$", re.IGNORECASE)
# A leading quantity ("100 kg of chicken breast", "50 lbs of beef") isn't
# part of the commodity name either -- confirmed live that leaving it in
# breaks _search_terms_for's first/last-word fallback (tries "100" and
# "breast" as search terms, never "chicken", since the number sits in
# the first-word position and pushes the real commodity word to the
# middle rather than either edge).
_LEADING_QUANTITY = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:kg|kgs|kilograms?|g|grams?|lbs?|pounds?|oz|ounces?|tons?|tonnes?)\s+(?:of\s+)?",
    re.IGNORECASE,
)
# Trailing time-framing words a real question often ends with ("...beef
# right now?") that aren't part of the commodity name -- left in place,
# these make it into the search keyword and break search_reports's
# substring match against report_title (e.g. "beef right now" matches no
# report title even though "beef" alone matches several).
_TRAILING_FILLER = re.compile(r"\s+(right now|today|currently|these days|at the moment|this week)[ ?.!]*$", re.IGNORECASE)
# Signals a broad planning question (a whole menu/week/budget), not a
# lookup for one specific commodity -- e.g. "plan a five-day lunch menu
# for 450 people ... itemized costs ... budget of $7.00 per meal" names no
# commodity at all. USDA AMS report slugs are matched by exact substring
# (see usda_ams_mcp.py), so searching with a whole garbled planning
# sentence (or its 40-char truncation) is a wasted call at best and a
# misleading half-word substring match at worst.
_BROAD_PLANNING_SIGNAL = re.compile(
    r"\b(five-day|\d+[- ]day|weekly|week'?s|itemized|budget|per meal|menu for|lunch menu|meal plan)\b",
    re.IGNORECASE,
)


def _commodity_query(user_text: str) -> str | None:
    cleaned = _MAX_WORDS_INSTRUCTION.sub("", user_text)
    cleaned = _ADDRESS_PREFIX.sub("", cleaned, count=1)
    cleaned = _REQUEST_FRAMING.sub("", cleaned)
    cleaned = _LEADING_HOW_MUCH_DOES.sub("", cleaned)
    # Trailing filler ("...beef cost right now?") must be stripped before
    # trailing "cost" is -- _TRAILING_COST anchors to the true end of the
    # string, so "right now?" sitting after "cost" would otherwise block
    # the match entirely.
    cleaned = _TRAILING_FILLER.sub("", cleaned)
    cleaned = _TRAILING_COST.sub("", cleaned)
    cleaned = _LEADING_QUANTITY.sub("", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.!")
    if not cleaned or _BROAD_PLANNING_SIGNAL.search(cleaned):
        return None
    if len(cleaned.split()) > 6:
        return None
    return cleaned


def _non_empty_results(raw: str | None) -> str | None:
    """search_reports always returns a JSON string, even for zero matches
    ({"results": []}) -- that string is truthy, so a plain `or` fallback
    never actually triggers on a real "nothing found" case. Parse and
    treat an empty results list as no data, same as a failed call."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict) and "results" in parsed and not parsed["results"]:
        return None
    return raw


def _search_terms_for(name: str) -> list[str]:
    """Candidate search terms for one ingredient name, tried in order: the
    full name as given, then its first word, then its last word
    (deduplicated, order preserved). USDA AMS report titles use short,
    single-word commodity terms -- confirmed live that a specific
    ingredient name almost never matches on its own ("cheddar cheese" and
    "chicken breast" both match zero report titles), but the commodity
    word it contains often does ("cheese" matches 5 real reports,
    "chicken" matches 3). Which word (first or last) is the actual
    commodity varies by ingredient ("chicken breast" -> "chicken" is
    first; "cheddar cheese" -> "cheese" is last), so both are tried."""
    words = name.split()
    terms = [name]
    if len(words) > 1:
        if words[0] not in terms:
            terms.append(words[0])
        if words[-1] not in terms:
            terms.append(words[-1])
    return terms


def _fetch_report_data(search_result_json: str | None) -> str | None:
    """search_reports only returns matching report names/slug_ids -- it
    never includes actual price data, so on its own it can't ground a
    procurement response despite the SYSTEM_PROMPT claiming "real USDA
    wholesale commodity market data" whenever it's present (confirmed live:
    the LLM was silently inventing every price figure even for commodities
    that "were found"). The real pricing rows need a second lookup, by a
    match's slug_id -- same two-stage shape as recipe_portion_agent.py's
    _fetch_recipe_details and nutrition_agent.py's food-details lookup.

    Tries every candidate from the search results in rank order, not just
    the top one -- confirmed live that the top-ranked report for a given
    keyword sometimes has zero data rows for the current day (USDA AMS
    reports are live and not every report publishes daily), which
    previously made the whole commodity look like "no data found" even
    though a real match existed a candidate or two further down."""
    if not search_result_json:
        return None
    try:
        parsed = json.loads(search_result_json)
    except (json.JSONDecodeError, TypeError):
        return None
    results = parsed.get("results") or []

    for candidate in results:
        slug_id = candidate.get("slug_id")
        if not slug_id:
            continue
        raw = mcp_client.call_tool_sync_or_none("usda_ams", "get_report", {"slug_id": slug_id, "limit": 10})
        if not raw:
            continue
        try:
            detail = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if detail.get("rows"):
            return raw
    return None


_INGREDIENT_EXTRACTION_SYSTEM_PROMPT = """Extract the distinct named ingredients from this list of cafeteria recipe ingredients.

Use the ACTUAL ingredient names as given -- e.g. "cheddar cheese",
"chicken breast", "romaine lettuce" -- do NOT generalize to a broad
category like "dairy", "poultry", or "produce". Drop only quantities/units
(e.g. "150g chicken breast" -> "chicken breast"), keep the ingredient name
itself intact. List each distinct ingredient only once.

Respond with ONLY a single JSON object and no other text:
{"ingredients": ["<ingredient name>", ...]}
"""


def _extract_ingredients(recipe_text: str) -> list[str]:
    """LLM-based extraction of the actual named ingredients from the
    Recipe & Portion Specialist's saved writeup -- kept as real ingredient
    names (e.g. "cheddar cheese"), not generalized into a broad category
    bucket (e.g. "dairy"), since a vague bucket name in the visible
    response tells the reader nothing about what's actually being priced.
    Matching that name against real USDA AMS report titles is handled
    separately (see _search_terms_for) since the full ingredient name
    rarely matches on its own. Same extraction shape as
    recipe_portion_agent.py's own _extract_dishes, kept as a separate
    local copy since each cafeteria-ops agent is self-contained."""
    raw = llm_utils.chat_sync(_INGREDIENT_EXTRACTION_SYSTEM_PROMPT, recipe_text, temperature=0, timeout=15)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return []
    return [i.strip() for i in (parsed.get("ingredients") or []) if isinstance(i, str) and i.strip()]


def _search_candidates_with_fallback(ingredients: list[str]) -> dict[str, list[str]]:
    """ingredient -> [slug_id, ...] in rank order -- searches with each
    ingredient's full name first, then falls back to its first/last word
    (see _search_terms_for) for any ingredient that found nothing on a
    more specific term. Each round is a single parallel batch across
    whichever ingredients still need one, bounded to at most 3 rounds
    (the max length of _search_terms_for's output)."""
    pending: dict[str, list[str]] = {ingredient: _search_terms_for(ingredient) for ingredient in ingredients}
    found: dict[str, list[str]] = {}
    while pending:
        attempt = {ingredient: terms[0] for ingredient, terms in pending.items()}
        search_requests = [("usda_ams", "search_reports", {"keyword": term, "limit": 3}) for term in attempt.values()]
        search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=10.0)

        next_pending: dict[str, list[str]] = {}
        for (ingredient, _term), raw in zip(attempt.items(), search_results):
            raw = _non_empty_results(raw)
            slug_ids: list[str] = []
            if raw:
                try:
                    parsed = json.loads(raw)
                    slug_ids = [r["slug_id"] for r in (parsed.get("results") or []) if r.get("slug_id")]
                except (json.JSONDecodeError, TypeError):
                    pass
            if slug_ids:
                found[ingredient] = slug_ids
            else:
                rest = pending[ingredient][1:]
                if rest:
                    next_pending[ingredient] = rest
        pending = next_pending
    return found


def _fetch_all_market_data(ingredients: list[str]) -> dict[str, str | None]:
    """ingredient -> real USDA AMS market-data JSON (pricing rows), or
    None if not found. Same batched two-round shape (parallel search
    round, then parallel detail round) as recipe_portion_agent.py's
    _fetch_all_recipes and nutrition_agent.py's _fetch_all_nutrients --
    except the search round itself falls back across search terms (see
    _search_candidates_with_fallback), and the detail round retries with
    the NEXT candidate slug_id for any ingredient whose current candidate
    had no rows, up to as many rounds as search_reports returned
    candidates (limit=3). Confirmed live that the top-ranked report for a
    keyword sometimes has zero rows for the current day, which previously
    made the whole ingredient look like "no data found" even though a
    real match existed further down the same search results -- each
    retry round is still fully parallel across whichever ingredients
    still need one."""
    if not ingredients:
        return {}

    candidates = _search_candidates_with_fallback(ingredients)

    output: dict[str, str | None] = {ingredient: None for ingredient in ingredients}
    remaining = candidates
    while remaining:
        attempt = {ingredient: slug_ids[0] for ingredient, slug_ids in remaining.items()}
        detail_requests = [("usda_ams", "get_report", {"slug_id": slug_id, "limit": 10}) for slug_id in attempt.values()]
        detail_results = mcp_client.call_tools_parallel_sync(detail_requests, timeout=10.0)

        next_remaining: dict[str, list[str]] = {}
        for (ingredient, _slug_id), raw in zip(attempt.items(), detail_results):
            found_rows = False
            if raw:
                try:
                    detail = json.loads(raw)
                    if detail.get("rows"):
                        output[ingredient] = raw
                        found_rows = True
                except (json.JSONDecodeError, TypeError):
                    pass
            if not found_rows:
                rest = remaining[ingredient][1:]
                if rest:
                    next_remaining[ingredient] = rest
        remaining = next_remaining

    return output


def _usable_web_search_result(raw: str | None) -> str | None:
    """raw web_search.search() JSON, or None if unconfigured (no
    TAVILY_API_KEY -- the tool returns a JSON {"error": ...} payload
    rather than failing the call outright, so this has to inspect the
    body, not just truthiness) or genuinely turned up nothing usable."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if parsed.get("error"):
        return None
    if not parsed.get("results") and not parsed.get("answer"):
        return None
    return raw


def _fetch_web_price_context(commodity_query: str) -> str | None:
    """One web search for current retail/grocery pricing for a single
    commodity (see mcp/web_search_mcp.py) -- tried as a fallback when
    USDA AMS has no matching wholesale report, since specialty or
    manufactured items (quinoa, shrimp, soy sauce) have no USDA wholesale
    commodity market at all but genuinely do have real retail prices
    findable online."""
    raw = mcp_client.call_tool_sync_or_none(
        "web_search", "search", {"query": f"{commodity_query} price per pound grocery store", "max_results": 5}
    )
    return _usable_web_search_result(raw)


def _fetch_all_web_prices(ingredients: list[str]) -> dict[str, str | None]:
    """ingredient -> real web search result JSON, or None if not found/
    unconfigured. Only meant to be called for ingredients USDA AMS had no
    data for (see _respond_for_whole_menu) -- one parallel batch, unlike
    _fetch_all_market_data's two-stage search-then-detail shape, since a
    web search result is already the "detail" (no separate ID lookup)."""
    if not ingredients:
        return {}

    search_requests = [
        ("web_search", "search", {"query": f"{ingredient} price per pound grocery store", "max_results": 5})
        for ingredient in ingredients
    ]
    search_results = mcp_client.call_tools_parallel_sync(search_requests, timeout=15.0)

    return {
        ingredient: _usable_web_search_result(raw)
        for ingredient, raw in zip(ingredients, search_results)
    }


SYSTEM_PROMPT = """You are the Procurement Specialist for a corporate cafeteria operations panel.
Your job is to advise on sourcing decisions for the commodity or situation
described.

You will be given real retrieved market data where available -- either
USDA wholesale commodity data, or (for specialty/manufactured items USDA
doesn't track, e.g. quinoa, shrimp, soy sauce) real current retail
pricing found via web search. Use whichever was retrieved to ground
price-sensitivity commentary in actual market conditions rather than
guessing; if it's web-sourced retail pricing rather than USDA wholesale
data, say so plainly (the two aren't the same thing) rather than
implying it's a wholesale/bulk price.

Cover: current price/market conditions if data was found, buying-timing
guidance (buy now vs. wait, given typical volatility for that commodity),
and a sourcing recommendation grounded in what the retrieved data
actually shows about THIS commodity -- not a default hedge ("watch the
market and consider your options") that would apply equally well to any
commodity regardless of what the data says. If you notice yourself
reaching for the same recommendation you'd give for any other commodity,
stop and re-derive one specific to what was actually retrieved.

If no matching market data was retrieved (from either source), say so
plainly and give your best general procurement guidance instead -- don't
imply you found real data when you didn't.

Ground your recommendation in the specific commodity/situation described.
This is a single, focused answer about ONE commodity, not a full report
-- two or three sentences covering the points above is usually enough;
don't pad it with restated caveats or generic market-watching advice.
Write in plain prose only -- no markdown, bold, or bullet characters, no
numbered-list markers -- just plain text. Keep the response focused;
overall length is guided by a separate instruction."""

# Used only for the whole-menu path (see _respond_for_whole_menu below).
# A plain-prose instruction to "keep each ingredient's name and guidance
# on one line" was NOT reliable -- confirmed live it still split entries
# across two, then three, lines even after tightening the wording twice.
# Asking for one JSON object per ingredient instead sidesteps the problem
# entirely: a JSON string value can hold multiple sentences without ever
# containing a raw newline that _text_to_html_list could mistake for a
# new list item, and Python code (see _render_ingredient_guidance) joins
# each ingredient's name and guidance into one line deterministically,
# rather than trusting the model to keep it there.
_WHOLE_MENU_SYSTEM_PROMPT = """You are the Procurement Specialist for a corporate cafeteria operations panel.

You have been given a set of ingredients used in a week's menu, each with
whatever real market data was actually retrieved for it: USDA wholesale
commodity data, real current retail prices found via web search (for
specialty/manufactured items USDA doesn't track, e.g. quinoa, shrimp, soy
sauce), or neither if nothing was found. Your job is to determine
practical grocery-store or food-service procurement options for EVERY
ingredient, using ONLY the data actually given to you below -- you have
no ability to look anything up yourself.

For EVERY ingredient:

* Use the retrieved grocery-store/food-service web search data where given -- it reflects actual current retail products and prices, more directly useful for a cafeteria buyer than a USDA wholesale/bulk commodity figure.
* If only USDA wholesale data was retrieved for an ingredient (no web search result), you may still use it for market-condition/timing context, but say plainly that it's a wholesale figure, not a retail price.
* Identify a suitable product and package size when possible.
* Report the current price when a reliable current price is available.
* Calculate or estimate the number of packages needed when the required quantity is provided.
* Calculate the resulting estimated purchase cost when possible.
* Identify the retailer or store when known.
* Provide a concise sourcing recommendation based on the information retrieved.
* If multiple suitable products or prices are found, select the most practical option and briefly indicate why.
* If no data (web search or USDA) was retrieved for an ingredient, say so plainly and provide useful general sourcing guidance without implying that a current price was found.
* Never invent a product, price, package size, retailer, or other procurement information.
* Never silently omit an ingredient.

Your sourcing guidance should be specific to the individual ingredient and the information retrieved, not generic advice that could apply to any ingredient.

Respond with ONLY a single JSON object and no other text.

Use this format:

{
"ingredients": [
{
"name": "<actual ingredient name>",
"product": "<specific product, if found>",
"package_size": "<package size, if found>",
"retailer": "<retailer/store, if known>",
"unit_price": "<current price, if found>",
"quantity_needed": "<quantity needed, if provided>",
"packages_needed": "<number of packages, if calculable>",
"estimated_cost": "<estimated purchase cost, if calculable>",
"guidance": "<concise sourcing guidance for this ingredient>"
}
]
}

Use the ingredient's actual name in "name" (for example, "cheddar cheese", not "dairy").

If information is unavailable for a field, use null rather than inventing a value."""


# A single-commodity or general answer is about ONE thing, not a whole
# menu -- the shared MAX_RESPONSE_WORDS class default (300) is sized for
# _respond_for_whole_menu's very different job (covering potentially 5+
# ingredients). Without its own smaller target, live testing showed this
# path reliably ran long and repetitive (padding out with the same
# generic "watch the market and weigh your options" hedge regardless of
# the commodity). Same "hand the model a concrete number, not just 'be
# concise'" fix as every other per-item budget hint in this project --
# capped at whatever the caller's own budget already is, in case that's
# smaller (e.g. a tight UI slider value).
_SINGLE_COMMODITY_WORD_TARGET = 60


def _single_commodity_budget_hint(max_words: int) -> str:
    target = min(max_words, _SINGLE_COMMODITY_WORD_TARGET)
    return f"\n\nThis is about ONE commodity, not a whole menu -- aim for roughly {target} words, not a full report."


def _render_ingredient_guidance(raw: str) -> str:
    """Parse the whole-menu JSON response into one guaranteed single line
    per ingredient ("<name>: <guidance>"), regardless of how many
    sentences the model's own guidance text contains -- the deterministic
    assembly step _WHOLE_MENU_SYSTEM_PROMPT's docstring explains. Falls
    back to the raw text unchanged if the JSON can't be parsed or yields
    no usable entries, rather than losing the response outright."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return raw
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return raw
    entries = parsed.get("ingredients") or []
    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        guidance = " ".join(str(entry.get("guidance") or "").split())
        if name and guidance:
            lines.append(f"{name}: {guidance}")
    return "\n".join(lines) if lines else raw


class ProcurementAgent(BaseStrategyAgent):
    AGENT_NAME = "Procurement Specialist"
    AGENT_PORT = 8306
    AGENT_SYNOPSIS = "Grounds sourcing decisions in real USDA wholesale commodity price data"
    AGENT_CAPABILITY_DETAIL = "Advises on procurement timing and sourcing strategy using real USDA AMS commodity market data."
    AGENT_KEYPHRASES = ["procurement", "sourcing", "purchase", "purchasing", "commodity",
                         "price", "pricing", "buy", "contract", "market"]
    # BaseStrategyAgent's default of 50 words is a single-item budget --
    # this is the value that actually governs (both the per-commodity
    # budget hint's arithmetic and the final hard truncation) whenever
    # convener delegates a question, since convener only embeds the UI
    # slider's value as advisory text, never as the maxWords feature this
    # reads. A whole-menu response needs real room for potentially 5+
    # commodities, not a couple of words apiece.
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
            logger.info("[Procurement] Saved Recipe & Portion's one-serving recipes for conv %s", conv_id)

    def process_utterance(self, user_text: str) -> dict:
        commodity_query = _commodity_query(user_text)
        if commodity_query:
            return self._respond_for_one_commodity(user_text, commodity_query)

        saved_recipes = self._observed_recipes.get(self._current_conv_id, "")
        if saved_recipes:
            ingredients = _extract_ingredients(saved_recipes)
            if ingredients:
                return self._respond_for_whole_menu(saved_recipes, ingredients)

        # No specific commodity named and no usable saved recipe writeup
        # -- fall back to general reasoning rather than doing nothing.
        return self._respond_general(user_text)

    def _respond_for_one_commodity(self, user_text: str, commodity_query: str) -> dict:
        # Try the full query first, then fall back across its
        # first/last-word variants -- same reasoning as
        # _search_terms_for: a specific, multi-word name the user typed
        # (e.g. "cheddar cheese") rarely matches a USDA AMS report title
        # on its own.
        report_data = None
        for term in _search_terms_for(commodity_query):
            search_result = mcp_client.call_tool_sync_or_none(
                "usda_ams", "search_reports", {"keyword": term, "limit": 3}
            )
            # search_reports only found a candidate report -- fetch that
            # report's real pricing rows in a second lookup.
            report_data = _fetch_report_data(_non_empty_results(search_result))
            if report_data:
                break

        if report_data:
            context = f"USDA wholesale market data:\n{report_data}"
        else:
            # USDA AMS only tracks bulk commodities -- a specialty/
            # manufactured item (quinoa, shrimp, soy sauce) never matches
            # there, but genuinely does have real retail prices findable
            # via web search.
            web_data = _fetch_web_price_context(commodity_query)
            context = (
                f"Web search results for current retail pricing:\n{web_data}" if web_data
                else "No matching USDA market data or web search results found -- use general procurement knowledge."
            )

        user_message = f"""{self._history_block()}Procurement situation: {user_text}

Retrieved market data:
{context}
{_single_commodity_budget_hint(self._current_max_words)}

Please provide sourcing/procurement guidance for this situation."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        return {"text": text, "html": self._text_to_html_list(text)}

    def _respond_general(self, user_text: str) -> dict:
        user_message = f"""{self._history_block()}Procurement situation: {user_text}

Retrieved market data:
No matching USDA market data or web search results found -- use general procurement knowledge.
{_single_commodity_budget_hint(self._current_max_words)}

Please provide sourcing/procurement guidance for this situation."""

        text = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        return {"text": text, "html": self._text_to_html_list(text)}

    def _respond_for_whole_menu(self, saved_recipes: str, ingredients: list[str]) -> dict:
        market_data = _fetch_all_market_data(ingredients)

        # USDA AMS only tracks bulk commodities -- fall back to a real web
        # search for retail pricing, but only for the ingredients USDA had
        # nothing for, not the whole list (no point re-searching what's
        # already grounded in real wholesale data).
        missing = [ingredient for ingredient in ingredients if not market_data.get(ingredient)]
        web_data = _fetch_all_web_prices(missing) if missing else {}

        gathered = []
        not_found = []
        for ingredient in ingredients:
            usda_raw = market_data.get(ingredient)
            web_raw = web_data.get(ingredient)
            if usda_raw:
                gathered.append(f"{ingredient} (USDA wholesale data):\n{usda_raw}")
            elif web_raw:
                gathered.append(f"{ingredient} (web search retail pricing):\n{web_raw}")
            else:
                not_found.append(ingredient)
        context = "\n\n".join(gathered) if gathered else "No USDA market data or web search results found for any ingredient."
        not_found_note = f"\nIngredients with no data found (USDA or web search): {', '.join(not_found)}" if not_found else ""

        # Same fix as Recipe & Portion's/Nutrition's per-item word budget:
        # without explicit arithmetic, the model exhausts the word budget
        # on the first ingredient and the reply gets hard-truncated (see
        # BaseStrategyAgent._limit_words) before every ingredient gets
        # covered.
        per_ingredient_words = max(20, self._current_max_words // max(1, len(ingredients)))
        budget_hint = (
            f"\n\nThis menu uses {len(ingredients)} ingredients. Budget roughly {per_ingredient_words} words "
            f"per ingredient so all {len(ingredients)} fit in the response -- do not spend more than "
            f"about that on any single ingredient until every one of the {len(ingredients)} ingredients has its "
            f"own entry."
        )

        user_message = f"""{self._history_block()}One-serving recipe amounts from the Recipe & Portion Specialist:
{saved_recipes}

Ingredients identified: {', '.join(ingredients)}

Real market data retrieved (USDA wholesale where matched, web-searched retail pricing otherwise):
{context}
{not_found_note}
{budget_hint}

Please provide sourcing/procurement guidance covering EVERY ingredient used in this week's menu."""

        raw = llm_utils.chat_sync(_WHOLE_MENU_SYSTEM_PROMPT, user_message, timeout=45)
        text = _render_ingredient_guidance(raw)
        return {"text": text, "html": self._text_to_html_list(text)}


def main() -> None:
    agent = ProcurementAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(ProcurementAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
