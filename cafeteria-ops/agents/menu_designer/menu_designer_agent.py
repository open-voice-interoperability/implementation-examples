#!/usr/bin/env python3
"""
Menu Designer Agent — Cafeteria Ops Floor

Designs weekly/daily lunch menu concepts: dish selection, variety across
the week, and thematic balance. Dish selection is pure LLM (no data
source needed to imagine a menu), and each proposed meal is illustrated
with an AI-generated image of that specific dish (see
_generate_meal_images below) via llm_utils.generate_image_sync -- unlike
every other specialist's data (real USDA prices/nutrition, real
TheMealDB recipes), an illustrative image has no equivalent free
real-data source with enough catalog coverage to reliably match an
LLM-invented dish name, so this one feature is generated rather than
looked up. Generation can fail or be unconfigured (no LLM_API_KEY, or an
Ollama-only setup); a line with no image just shows text, same
honest-degradation spirit as every other agent's real-data lookups.

Port: 8301
"""

import concurrent.futures
import logging
import os
import re
import sys
from html import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import llm_utils

logger = logging.getLogger(__name__)

# A soft "cover every day, don't just detail the first" admonition wasn't
# reliable on its own -- live testing showed real run-to-run variance (the
# SAME word budget produced anywhere from 3 to 5 days out of a requested
# five) because nothing told the model the actual per-day word math. A
# concrete number is what worked for the Shopping List Specialist's own
# multi-item budgeting problem, so apply the same idea here: detect how
# many days were actually requested and hand the model a computed
# words-per-day target instead of a vague instruction.
_DAY_COUNT_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
}
_DAY_COUNT_PATTERN = re.compile(
    r"\b(one|two|three|four|five|six|seven|\d+)[\s-]days?\b", re.IGNORECASE
)


def _requested_day_count(user_text: str) -> int | None:
    match = _DAY_COUNT_PATTERN.search(user_text)
    if not match:
        return None
    token = match.group(1).lower()
    return _DAY_COUNT_WORDS.get(token) or (int(token) if token.isdigit() else None)


# Strips a leading "Day N:" label so it's not part of the image prompt --
# the label isn't a dish description.
_DAY_LABEL_PREFIX = re.compile(r"^day\s*\d+:\s*", re.IGNORECASE)


def _image_prompt(line: str) -> str:
    """Build an image-generation prompt from one line of this agent's own
    response (a "Day N: ..." entry, or the single dish/meal named in a
    single-day response), keeping every item the line lists -- a main
    dish plus separate sides ("Chicken and chorizo tacos with avocado
    salsa, grilled vegetable tacos, corn tortillas"). Simply handing the
    model that whole line with no further guidance confirmed live to
    produce visibly DUPLICATED food (e.g. two near-identical sets of
    tacos) instead of one coherent plate -- dropping everything but the
    main dish avoided the duplication but silently left the sides out of
    the picture entirely. The explicit "one cohesive plate, nothing
    repeated" instruction below fixes the actual problem (composition)
    instead, confirmed live to compose all of a multi-item line onto one
    plate with each element appearing exactly once."""
    dish = _DAY_LABEL_PREFIX.sub("", line).strip()
    return (
        f"A professional, appetizing food-photography shot of one cohesive "
        f"cafeteria lunch plate combining: {dish} Arrange all of this as ONE "
        "single plate -- do not repeat or duplicate any item, each element "
        "should appear exactly once. Realistic, natural lighting, no text or "
        "watermarks."
    )


def _generate_meal_images(lines: list[str]) -> list[str]:
    """One AI-generated illustration data URI per line ("" where generation
    is unavailable or fails), in the same order as the given lines --
    generated in parallel since llm_utils.generate_image_sync is a
    blocking call and a multi-day menu needs one image per day. Honest
    degradation: no image just means no <img> for that line, never a
    broken or placeholder one."""
    if not lines:
        return []

    prompts = [_image_prompt(line) for line in lines]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(prompts)) as pool:
        return list(pool.map(llm_utils.generate_image_sync, prompts))


def _build_menu_html(text: str, images: list[str]) -> str:
    """Plain-text response -> HTML for the browser's Analysis report
    popup: one <li> per line when there's more than one (matching
    BaseStrategyAgent._text_to_html_list's shape for consistency with
    every other specialist), with an AI-generated illustration <img>
    appended wherever _generate_meal_images produced one for that line. A
    one-line response only gets an "html" feature when an image was
    actually generated for it -- otherwise it would just be the same text
    again in a <p>, which BaseStrategyAgent's own _text_to_html_list also
    treats as not worth showing (single item, no genuine list)."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return ""

    def _entry_html(line: str, image: str | None) -> str:
        image_html = ""
        if image:
            image_html = (
                f'<br><img src="{escape(image)}" alt="{escape(line)}" '
                f'style="max-width:200px;border-radius:6px;margin-top:4px">'
            )
        return f"{escape(line)}{image_html}"

    if len(lines) == 1:
        image = images[0] if images else None
        if not image:
            return ""
        return f"<p>{_entry_html(lines[0], image)}</p>"

    items = "".join(f"<li>{_entry_html(line, image)}</li>" for line, image in zip(lines, images))
    return f"<ul>{items}</ul>"


SYSTEM_PROMPT = """You are the Menu Designer for a corporate cafeteria planning panel.
Your job is to propose concrete lunch menu(s) for the request given -- state
the dish(es) themselves, not a pitch for why they're good choices.

For each day/meal, name the specific dish(es) being served, with enough
detail to actually plan around: the protein or main ingredient, the main
starch/vegetable/preparation, and how it's served -- not just a food
category (e.g. not just "a salad" or "a sandwich" with nothing else
said). Do NOT explain your reasoning in the response -- no commentary on
variety versus recent menus, who the dish appeals to, or operational fit
(batch-cookable, holds on a steam table, etc.). Just the menu itself,
nothing else.

You should still privately avoid repeating the same protein/starch/cuisine
two days running when choosing dishes -- that's a constraint on WHAT you
pick, not something to mention in the response.

If the request asks for MULTIPLE days (e.g. a five-day menu), do NOT give
a long writeup of only the first day and stop -- that leaves the rest of
the request unanswered. Instead give one line per day (just the dish
name(s), nothing more), covering every day requested. Put each day on its
OWN LINE (a real line break between "Day 1: ..." and "Day 2: ...", not run
together in one paragraph).

Derive your menu ideas from the specific request -- the season, cuisine,
occasion, or constraint actually mentioned, not a generic rotation. Two
different requests should essentially never produce the same menu; if
you notice yourself reaching for the same familiar go-to dish regardless
of what was asked, stop and re-derive something more specific to what
was actually asked. (Naming that go-to dish here as an example would
just teach you to reach for it, the same mistake this instruction exists
to prevent -- notice the PATTERN of over-relying on one default, not a
specific dish to avoid.)

Be concrete and specific. Write in plain prose only -- no markdown, bold,
or bullet characters, no numbered-list markers -- just plain text lines.
Keep the response focused; overall length is guided by a separate
instruction.

If a prior conversation is included below, use it: a follow-up request
(e.g. "make day 3 vegetarian instead") refers to the menu already proposed
there, not a fresh one -- revise/extend that specific menu rather than
inventing an unrelated one.

If the request also asks about something outside menu design -- inventory/
stock/par levels, nutrition, procurement/sourcing/cost, or a shopping
list -- IGNORE that part entirely and answer ONLY the menu-design portion.
A specialist dedicated to that other topic is also on this panel and will
answer it separately; you covering it too would just be a redundant,
less-informed duplicate of their answer. Never mention stock levels,
spoilage risk, sourcing, or ingredient cost in your response -- that is
never your job, regardless of how the request is phrased.

Ignoring that other part means leaving it out SILENTLY -- do not add a
sentence pointing the reader to another specialist ("for the shopping
list, ask the Procurement Specialist," "the Inventory Specialist can
assess stock risk," etc.). The floor manager already routes the rest of
the request to the right specialist on its own; a redirect sentence from
you is not needed and is not part of the menu. Your entire response
should be the menu itself and nothing else -- no meta-commentary about
what you are or aren't covering."""


class MenuDesignerAgent(BaseStrategyAgent):
    AGENT_NAME = "Menu Designer"
    AGENT_PORT = 8301
    AGENT_SYNOPSIS = "Designs lunch menu concepts balancing variety and theme"
    AGENT_CAPABILITY_DETAIL = "Proposes concrete lunch menu concepts with dish selection, weekly variety, and operational fit for a cafeteria setting."
    AGENT_KEYPHRASES = ["menu", "menu design", "dish", "dishes", "lunch", "theme", "variety",
                         "rotation", "offering", "weekly menu"]
    # BaseStrategyAgent's default of 50 words is a single-item budget --
    # divided across a five-day request via the per-day hint above, that's
    # only 10 words/day (floor-clamped up to 15), too tight for a real
    # dish name plus a variety/fit note. 250 gives 50 words/day for a
    # five-day menu, matching what live testing showed a genuinely useful
    # per-day entry needs. Only takes effect when the UI's maxWords slider
    # value isn't otherwise supplied (e.g. a direct, non-UI request).
    MAX_RESPONSE_WORDS = 250

    def process_utterance(self, user_text: str) -> dict:
        day_count = _requested_day_count(user_text)
        budget_hint = ""
        if day_count and day_count > 1:
            per_day_words = max(15, self._current_max_words // day_count)
            budget_hint = (
                f"\n\nThis request covers {day_count} days. Budget roughly {per_day_words} words "
                f"per day so all {day_count} fit in the response -- do not spend more than "
                f"about that on any single day until every one of the {day_count} days has its "
                f"own entry."
            )

        user_message = f"""{self._history_block()}Cafeteria menu planning request: {user_text}{budget_hint}

Please propose concrete lunch menu concept(s) for this request."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        # Stripped once here (rather than left to bot_on_utterance's own
        # later pass) so the "text" returned and the lines used to look
        # up images for "html" are guaranteed to match line-for-line --
        # _strip_markdown is idempotent, so running it again downstream
        # is harmless.
        text = self._strip_markdown(raw)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        images = _generate_meal_images(lines)
        return {"text": text, "html": _build_menu_html(text, images)}


def main() -> None:
    agent = MenuDesignerAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(MenuDesignerAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
