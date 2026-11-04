import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.shopping_list_specialist import shopping_list_agent as sla
from agents.shopping_list_specialist.shopping_list_agent import (
    _average_cost_per_plate_line,
    _build_category_sections,
    _build_cost_chart,
    _categorize_ingredients,
    _categorized_response,
    _category_cost_totals,
    _dedupe_ingredient_lines,
    _extract_dishes_from_recipes,
    _format_dollars,
    _llm_candidate_terms,
    _parse_ingredient_lines,
    _parse_total_dollars,
    _recompute_total_line,
    _render_html_from_sections,
    _render_text_from_sections,
    _roll_up_line,
    _to_one_serving,
    ShoppingListAgent,
)


def _group_by_category(text: str, headcount: int) -> str:
    """Test-local equivalent of the deterministic category-grouping step
    (formerly its own production function, folded into _categorized_response
    since it had no other caller) -- kept here so GroupByCategoryTests below
    still exercises _build_category_sections/_render_text_from_sections
    together as a unit."""
    sections, other_lines, total_line = _build_category_sections(text)
    return _render_text_from_sections(sections, other_lines, total_line, text, headcount)


class ExtractMenuTests(unittest.TestCase):
    def test_valid_response_parses_dishes_and_headcount(self):
        raw = '{"dishes": ["Chicken Caesar Salad", "Beef Stir-Fry"], "headcount": 450}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = sla._extract_menu("Day 1: Chicken Caesar Salad. Day 2: Beef Stir-Fry. 450 people.")

        chat_sync.assert_called_once()
        self.assertEqual(result, {"dishes": ["Chicken Caesar Salad", "Beef Stir-Fry"], "headcount": 450})

    def test_missing_headcount_is_none(self):
        raw = '{"dishes": ["Lentil Soup"], "headcount": null}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = sla._extract_menu("We're serving lentil soup this week.")

        self.assertEqual(result["dishes"], ["Lentil Soup"])
        self.assertIsNone(result["headcount"])

    def test_malformed_json_returns_empty(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="not json at all"):
            result = sla._extract_menu("some message")

        self.assertEqual(result, {"dishes": [], "headcount": None})

    def test_non_positive_headcount_is_discarded(self):
        raw = '{"dishes": ["Lentil Soup"], "headcount": -5}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = sla._extract_menu("some message")

        self.assertIsNone(result["headcount"])

    def test_non_string_dish_entries_are_dropped(self):
        raw = '{"dishes": ["Lentil Soup", 123, null], "headcount": 100}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = sla._extract_menu("some message")

        self.assertEqual(result["dishes"], ["Lentil Soup"])


class ExtractDishesFromRecipesTests(unittest.TestCase):
    def test_parses_dishes_from_llm_json_response(self):
        raw = '{"dishes": ["Chicken Curry", "Shirazi Salad"]}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = _extract_dishes_from_recipes("Chicken Curry: 150g chicken. Shirazi Salad: 50g cucumber.")

        chat_sync.assert_called_once()
        self.assertEqual(result, ["Chicken Curry", "Shirazi Salad"])

    def test_response_with_no_json_object_is_empty(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="no json here"):
            result = _extract_dishes_from_recipes("some recipe writeup")

        self.assertEqual(result, [])

    def test_malformed_json_is_empty(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="{not valid json"):
            result = _extract_dishes_from_recipes("some recipe writeup")

        self.assertEqual(result, [])

    def test_blank_or_non_string_entries_are_dropped(self):
        raw = '{"dishes": ["Chicken Curry", "", 123, null]}'
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = _extract_dishes_from_recipes("some recipe writeup")

        self.assertEqual(result, ["Chicken Curry"])


class TermsFromSlotsTests(unittest.TestCase):
    """Deterministic priority order built from one dish's extracted slots
    -- same fix as recipe_portion_agent.py's own copy, needed here because
    this agent's own direct TheMealDB fallback (used when Recipe & Portion
    hasn't replied yet in the conversation) had no retry logic at all
    before the earlier fix, let alone one that reliably distinguishes
    "chorizo" from "chicken"/"cheese"/"salad"."""

    def test_dish_type_alone_is_not_a_candidate(self):
        # Confirmed live: a bare dish-type word ("tacos", "pizza") matched
        # an unrelated dish sharing only that category ("tacos" -> the
        # unrelated "Breadfruit Tacos"; "pizza" -> the unrelated "Cassava
        # pizza") -- same risk as a bare main_ingredient or cuisine word.
        self.assertEqual(sla._terms_from_slots({"dish_type": "tacos"}), [])

    def test_secondary_ingredient_ranks_above_main_plus_sauce(self):
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "chorizo", "sauce_or_style": "spicy"}
        terms = sla._terms_from_slots(slots)
        self.assertLess(terms.index("chorizo"), terms.index("chicken spicy"))

    def test_sauce_or_style_alone_is_not_a_candidate(self):
        # Confirmed live: a bare sauce/style word ("barbecue") matched an
        # unrelated dish sharing only that word ("barbecue" -> the
        # unrelated "Barbecue pork buns", even fed downstream for a dish
        # explicitly labeled Vegetarian) -- same risk as a bare
        # main_ingredient, cuisine, or dish_type word.
        self.assertEqual(sla._terms_from_slots({"sauce_or_style": "barbecue"}), [])

    def test_cuisine_ranks_below_the_dish_own_identity(self):
        # Bare cuisine alone is not a candidate at all (see
        # test_cuisine_alone_is_not_a_candidate); cuisine+main is the
        # weakest tier still allowed, since it requires both pieces of
        # information to align in one title.
        slots = {"main_ingredient": "lamb", "dish_type": "stew", "cuisine": "Moroccan"}
        terms = sla._terms_from_slots(slots)
        self.assertLess(terms.index("stew lamb"), terms.index("Moroccan lamb"))

    def test_cuisine_alone_is_not_a_candidate(self):
        # Confirmed live: a bare cuisine word matched an unrelated dish
        # from that same cuisine -- a wrong "real" recipe presented as
        # grounded data is worse than admitting no match was found.
        self.assertEqual(sla._terms_from_slots({"cuisine": "Moroccan"}), [])

    def test_main_ingredient_alone_is_not_a_candidate(self):
        self.assertEqual(sla._terms_from_slots({"main_ingredient": "chicken"}), [])

    def test_generic_category_secondary_ingredient_is_dropped(self):
        # Same fix as recipe_portion_agent.py's own copy -- confirmed live
        # the model dodged the "not vegetable/meat/..." instruction just by
        # pluralizing ("vegetables"), so this is enforced in code instead.
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "vegetables", "dish_type": "biryani"}
        terms = sla._terms_from_slots(slots)
        self.assertNotIn("vegetables", terms)

    def test_generic_category_secondary_ingredient_singular_is_also_dropped(self):
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "meat"}
        self.assertEqual(sla._terms_from_slots(slots), [])

    def test_specific_secondary_ingredient_is_not_dropped(self):
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "berries"}
        self.assertIn("berries", sla._terms_from_slots(slots))

    def test_cooking_method_plus_main_ranks_below_sauce(self):
        slots = {"main_ingredient": "chicken", "sauce_or_style": "teriyaki", "cooking_method": "grilled"}
        terms = sla._terms_from_slots(slots)
        self.assertLess(terms.index("chicken teriyaki"), terms.index("grilled chicken"))

    def test_cut_ranks_above_cooking_method(self):
        slots = {"main_ingredient": "lamb", "cooking_method": "grilled", "cut": "chop"}
        terms = sla._terms_from_slots(slots)
        self.assertLess(terms.index("lamb chop"), terms.index("chop"))
        self.assertLess(terms.index("chop"), terms.index("grilled lamb"))

    def test_steak_fallback_is_tried_only_after_the_cut_itself(self):
        slots = {"main_ingredient": "beef", "cut": "sirloin"}
        terms = sla._terms_from_slots(slots)
        self.assertLess(terms.index("beef sirloin"), terms.index("beef steak"))
        self.assertLess(terms.index("sirloin"), terms.index("steak"))

    def test_steak_fallback_is_absent_for_a_non_steak_cut(self):
        slots = {"main_ingredient": "lamb", "cut": "chop"}
        terms = sla._terms_from_slots(slots)
        self.assertNotIn("steak", terms)
        self.assertNotIn("lamb steak", terms)

    def test_empty_slots_return_no_terms(self):
        self.assertEqual(sla._terms_from_slots({}), [])


class LlmCandidateTermsTests(unittest.TestCase):
    """The exact dish name is always prepended as the first, free
    attempt, followed by the deterministic term order built from that
    dish's LLM-extracted slots (see TermsFromSlotsTests)."""

    def test_dish_name_is_prepended_before_the_slot_derived_terms(self):
        raw = json.dumps({"Grilled Teriyaki Chicken": {"main_ingredient": "chicken", "sauce_or_style": "teriyaki"}})
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = _llm_candidate_terms(["Grilled Teriyaki Chicken"])

        # No trailing bare "chicken" or bare "teriyaki" -- main_ingredient
        # alone and sauce_or_style alone are deliberately not candidates
        # (see TermsFromSlotsTests).
        self.assertEqual(
            result["Grilled Teriyaki Chicken"],
            ["Grilled Teriyaki Chicken", "chicken teriyaki"],
        )

    def test_dish_missing_from_the_llm_response_falls_back_to_itself_alone(self):
        raw = json.dumps({"Chicken Curry": {"main_ingredient": "chicken"}})
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = _llm_candidate_terms(["Chicken Curry", "Lentil Soup"])

        self.assertEqual(result["Lentil Soup"], ["Lentil Soup"])

    def test_malformed_json_response_falls_back_to_the_dish_name_alone(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="not json at all"):
            result = _llm_candidate_terms(["Chicken Curry"])

        self.assertEqual(result["Chicken Curry"], ["Chicken Curry"])

    def test_empty_dish_list_makes_no_llm_call(self):
        with patch.object(sla.llm_utils, "chat_sync") as chat_sync:
            result = _llm_candidate_terms([])

        chat_sync.assert_not_called()
        self.assertEqual(result, {})


class FetchDishIngredientsTests(unittest.TestCase):
    def test_empty_dish_list_makes_no_calls(self):
        with patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            result = sla._fetch_dish_ingredients([])

        parallel.assert_not_called()
        self.assertEqual(result, {})

    def test_found_dish_returns_real_ingredients_via_two_stage_lookup(self):
        search_result = json.dumps({
            "query": "chicken curry",
            "results": [{"id": "52", "name": "Nutty Chicken Curry", "category": "Chicken"}],
        })
        detail_result = json.dumps({
            "id": "52",
            "name": "Nutty Chicken Curry",
            "ingredients": ["200g chicken breast", "1 tbsp curry powder"],
        })

        with patch.object(sla, "_llm_candidate_terms", return_value={"chicken curry": ["chicken curry"]}), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [[search_result], [detail_result]]
            result = sla._fetch_dish_ingredients(["chicken curry"])

        self.assertEqual(parallel.call_count, 2)
        # First call: search_by_name; second call: get_recipe_details using
        # the meal id from the first call's result.
        first_call_requests = parallel.call_args_list[0].args[0]
        self.assertEqual(first_call_requests[0][:2], ("themealdb", "search_by_name"))
        second_call_requests = parallel.call_args_list[1].args[0]
        self.assertEqual(second_call_requests[0], ("themealdb", "get_recipe_details", {"meal_id": "52"}))

        self.assertEqual(result["chicken curry"]["meal_name"], "Nutty Chicken Curry")
        self.assertEqual(result["chicken curry"]["ingredients"], ["200g chicken breast", "1 tbsp curry powder"])

    def test_dish_not_found_in_search_is_none_and_skips_detail_lookup(self):
        # Both of "totally made up dish"'s candidate terms miss -- no
        # detail round should ever run.
        terms = {"totally made up dish": ["totally made up dish", "made"]}
        no_match = json.dumps({"query": "xyz", "results": []})

        with patch.object(sla, "_llm_candidate_terms", return_value=terms), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync", return_value=[no_match]) as parallel:
            result = sla._fetch_dish_ingredients(["totally made up dish"])

        self.assertEqual(parallel.call_count, 2)
        self.assertIsNone(result["totally made up dish"])

    def test_mixed_found_and_not_found_dishes(self):
        # "chicken curry" hits on the first (full-name) candidate term;
        # "made up dish" misses on its full name and its only other
        # candidate ("made") before giving up.
        terms = {"chicken curry": ["chicken curry"], "made up dish": ["made up dish", "made"]}
        round1 = [
            json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]}),
            json.dumps({"query": "made up dish", "results": []}),
        ]
        round2 = [json.dumps({"query": "made", "results": []})]
        detail_results = [json.dumps({"id": "52", "name": "Nutty Chicken Curry", "ingredients": ["200g chicken"]})]

        with patch.object(sla, "_llm_candidate_terms", return_value=terms), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [round1, round2, detail_results]
            result = sla._fetch_dish_ingredients(["chicken curry", "made up dish"])

        self.assertIsNotNone(result["chicken curry"])
        self.assertIsNone(result["made up dish"])

    def test_detail_lookup_failure_leaves_dish_as_none(self):
        terms = {"chicken curry": ["chicken curry"]}
        search_result = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]})

        with patch.object(sla, "_llm_candidate_terms", return_value=terms), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [[search_result], [None]]
            result = sla._fetch_dish_ingredients(["chicken curry"])

        self.assertIsNone(result["chicken curry"])

    def test_a_dish_that_loses_the_dedupe_retries_with_its_own_next_candidate(self):
        # Same regression as recipe_portion_agent.py's own copy: a dish
        # that collides with another on a shared fallback term must still
        # get its own real match if it has a further candidate left,
        # instead of being dropped to None outright.
        terms = {
            "Dish A": ["Dish A", "shared"],
            "Dish B": ["Dish B", "shared", "unique"],
        }
        round1 = [
            json.dumps({"query": "Dish A", "results": []}),
            json.dumps({"query": "Dish B", "results": []}),
        ]
        round2 = [
            json.dumps({"query": "shared", "results": [{"id": "99", "name": "Shared Recipe"}]}),
            json.dumps({"query": "shared", "results": [{"id": "99", "name": "Shared Recipe"}]}),
        ]
        round3_retry = [json.dumps({"query": "unique", "results": [{"id": "100", "name": "Unique Recipe"}]})]
        detail = [
            json.dumps({"id": "99", "name": "Shared Recipe", "ingredients": ["1 shared thing"]}),
            json.dumps({"id": "100", "name": "Unique Recipe", "ingredients": ["1 unique thing"]}),
        ]
        with patch.object(sla, "_llm_candidate_terms", return_value=terms), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3_retry, detail]):
            result = sla._fetch_dish_ingredients(["Dish A", "Dish B"])

        self.assertEqual(result["Dish A"]["meal_name"], "Shared Recipe")
        self.assertEqual(result["Dish B"]["meal_name"], "Unique Recipe")

    def test_a_middle_ingredient_word_is_tried_when_the_full_phrase_matches_nothing(self):
        # Same real-world case as recipe_portion_agent.py's own fix:
        # TheMealDB has no title matching "chicken chorizo quesadillas" or
        # "quesadillas" alone, but "chorizo" matches a real, closely
        # related dish.
        dish = "Chicken and Chorizo Quesadillas"
        terms = {dish: [dish, "chicken chorizo quesadillas", "quesadillas", "chorizo"]}
        round1 = [json.dumps({"query": dish, "results": []})]
        round2 = [json.dumps({"query": "chicken chorizo quesadillas", "results": []})]
        round3 = [json.dumps({"query": "quesadillas", "results": []})]
        round4 = [json.dumps({"query": "chorizo", "results": [{"id": "77", "name": "Chicken & chorizo rice pot"}]})]
        detail = [json.dumps({"id": "77", "name": "Chicken & chorizo rice pot", "ingredients": ["200g chorizo"]})]
        with patch.object(sla, "_llm_candidate_terms", return_value=terms), \
             patch.object(sla.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3, round4, detail]) as parallel:
            result = sla._fetch_dish_ingredients([dish])

        terms_tried = [c.args[0][0][2]["name"] for c in parallel.call_args_list[:4]]
        self.assertEqual(terms_tried, [dish, "chicken chorizo quesadillas", "quesadillas", "chorizo"])
        self.assertEqual(result[dish]["meal_name"], "Chicken & chorizo rice pot")


class OnObservedUtteranceTests(unittest.TestCase):
    """The Shopping List Specialist watches Pass-Through broadcast traffic
    for the Recipe & Portion Specialist's one-serving recipe writeup, keyed
    per-conversation, so it can reuse those real, already-resolved amounts
    instead of re-querying TheMealDB itself (which frequently fails to
    match Menu Designer's LLM-invented dish names)."""

    def test_saves_text_from_recipe_portion(self):
        agent = ShoppingListAgent()

        agent.on_observed_utterance("conv-1", sla._RECIPE_PORTION_SERVICE_URL, "Chicken Curry: 150g chicken breast.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken Curry: 150g chicken breast."})

    def test_matches_the_recipe_portion_uri_case_and_slash_insensitively(self):
        agent = ShoppingListAgent()
        loud_uri = sla._RECIPE_PORTION_SERVICE_URL.upper().rstrip("/")

        agent.on_observed_utterance("conv-1", loud_uri, "Chicken Curry: 150g chicken breast.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken Curry: 150g chicken breast."})

    def test_ignores_utterances_from_other_speakers(self):
        agent = ShoppingListAgent()

        agent.on_observed_utterance("conv-1", "http://127.0.0.1:8301/", "some menu designer commentary")

        self.assertEqual(agent._observed_recipes, {})

    def test_different_conversations_are_kept_separate(self):
        agent = ShoppingListAgent()

        agent.on_observed_utterance("conv-1", sla._RECIPE_PORTION_SERVICE_URL, "recipes for conv 1")
        agent.on_observed_utterance("conv-2", sla._RECIPE_PORTION_SERVICE_URL, "recipes for conv 2")

        self.assertEqual(agent._observed_recipes, {"conv-1": "recipes for conv 1", "conv-2": "recipes for conv 2"})


class ProcessUtteranceBranchingTests(unittest.TestCase):
    """process_utterance prefers the Recipe & Portion Specialist's saved
    one-serving amounts when available in this conversation, and falls
    back to a direct TheMealDB lookup only when they aren't. When saved
    recipes ARE available, the dish list comes from THAT text
    (_extract_dishes_from_recipes) rather than from re-extracting dishes
    out of the current utterance -- confirmed live (see the module's own
    docstring on _extract_dishes_from_recipes) that trusting the
    utterance's own dish list could silently drop dishes -- including
    meat -- that the Menu Designer's real week actually included."""

    def _make_agent(self, conv_id="conv-1", saved_recipes=""):
        agent = ShoppingListAgent()
        agent._current_conv_id = conv_id
        if saved_recipes:
            agent._observed_recipes[conv_id] = saved_recipes
        return agent

    def test_no_dishes_identified_returns_a_clarifying_message_without_any_lookup(self):
        agent = self._make_agent()
        with patch.object(sla, "_extract_menu", return_value={"dishes": [], "headcount": None}), \
             patch.object(agent, "_respond_from_recipe_portion") as from_rp, \
             patch.object(agent, "_respond_from_themealdb") as from_mdb:
            result = agent.process_utterance("what's for lunch?")

        from_rp.assert_not_called()
        from_mdb.assert_not_called()
        self.assertIn("couldn't identify any specific dishes", result)

    def test_saved_recipes_present_uses_dishes_extracted_from_the_recipes_not_the_utterance(self):
        # The utterance only names the salad; the saved recipe writeup has
        # BOTH dishes. The full list from the recipes must win -- this is
        # the direct regression test for the "no meat in the shopping
        # list" bug (the utterance-derived dish list silently dropped the
        # chicken dish entirely).
        agent = self._make_agent(saved_recipes="Chicken Curry: 150g chicken breast. Shirazi Salad: 50g cucumber.")
        with patch.object(sla, "_extract_menu", return_value={"dishes": ["Shirazi Salad"], "headcount": 300}), \
             patch.object(sla, "_extract_dishes_from_recipes", return_value=["Chicken Curry", "Shirazi Salad"]) as extract_from_recipes, \
             patch.object(agent, "_respond_from_recipe_portion", return_value="from recipe portion") as from_rp, \
             patch.object(agent, "_respond_from_themealdb") as from_mdb:
            result = agent.process_utterance("Shirazi Salad for 300 people")

        extract_from_recipes.assert_called_once_with("Chicken Curry: 150g chicken breast. Shirazi Salad: 50g cucumber.")
        from_rp.assert_called_once_with(
            ["Chicken Curry", "Shirazi Salad"], 300, "", "Chicken Curry: 150g chicken breast. Shirazi Salad: 50g cucumber."
        )
        from_mdb.assert_not_called()
        self.assertEqual(result, "from recipe portion")

    def test_saved_recipes_present_but_unparseable_falls_back_to_themealdb(self):
        agent = self._make_agent(saved_recipes="some unparseable writeup")
        with patch.object(sla, "_extract_menu", return_value={"dishes": ["Chicken Curry"], "headcount": None}), \
             patch.object(sla, "_extract_dishes_from_recipes", return_value=[]), \
             patch.object(agent, "_respond_from_recipe_portion") as from_rp, \
             patch.object(agent, "_respond_from_themealdb", return_value="from themealdb") as from_mdb:
            result = agent.process_utterance("Chicken Curry")

        from_rp.assert_not_called()
        from_mdb.assert_called_once_with(["Chicken Curry"], sla.DEFAULT_HEADCOUNT, f" (no headcount given in the message -- assuming {sla.DEFAULT_HEADCOUNT})")
        self.assertEqual(result, "from themealdb")

    def test_no_saved_recipes_falls_back_to_themealdb(self):
        agent = self._make_agent(saved_recipes="")
        with patch.object(sla, "_extract_menu", return_value={"dishes": ["Chicken Curry"], "headcount": None}), \
             patch.object(agent, "_respond_from_recipe_portion") as from_rp, \
             patch.object(agent, "_respond_from_themealdb", return_value="from themealdb") as from_mdb:
            result = agent.process_utterance("Chicken Curry")

        from_rp.assert_not_called()
        from_mdb.assert_called_once_with(["Chicken Curry"], sla.DEFAULT_HEADCOUNT, f" (no headcount given in the message -- assuming {sla.DEFAULT_HEADCOUNT})")
        self.assertEqual(result, "from themealdb")


class RespondFromRecipePortionTests(unittest.TestCase):
    def test_passes_saved_recipes_as_context_and_scales_to_headcount(self):
        agent = ShoppingListAgent()
        with patch.object(sla.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_from_recipe_portion(
                ["Chicken Curry", "Lentil Soup"], 300, "", "Chicken Curry: 150g chicken. Lentil Soup: 100g lentils."
            )

        self.assertEqual(chat_sync.call_args[0][0], sla.SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("Chicken Curry: 150g chicken. Lentil Soup: 100g lentils.", user_message)
        self.assertIn("scaled to 300 people", user_message)
        self.assertNotIn("TheMealDB", user_message)


class ParseIngredientLinesTests(unittest.TestCase):
    def test_splits_ingredient_lines_from_the_total_line(self):
        text = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        ingredient_lines, other_lines, total_line = _parse_ingredient_lines(text)

        self.assertEqual([name for name, _ in ingredient_lines], ["chicken breast", "romaine lettuce"])
        self.assertEqual(other_lines, [])
        self.assertEqual(total_line, "Estimated total: ~$48")

    def test_not_found_note_is_kept_separate_from_ingredient_lines(self):
        text = "chicken breast: 5kg (~$40)\nDishes with no ingredient data found: Mystery Dish\nEstimated total: ~$40"
        ingredient_lines, other_lines, total_line = _parse_ingredient_lines(text)

        self.assertEqual([name for name, _ in ingredient_lines], ["chicken breast"])
        self.assertEqual(other_lines, ["Dishes with no ingredient data found: Mystery Dish"])

    def test_per_dish_not_found_lines_are_kept_out_of_ingredient_lines(self):
        # The model doesn't always use the exact "Dishes with no ingredient
        # data found: ..." phrasing -- confirmed live it sometimes writes
        # one such line per dish instead, which still contains a colon and
        # would otherwise be mistaken for a real ingredient line.
        text = (
            "chicken breast: 5kg (~$40)\n"
            "Mystery Dish: Ingredients could not be found.\n"
            "Estimated total: ~$40"
        )
        ingredient_lines, other_lines, total_line = _parse_ingredient_lines(text)

        self.assertEqual([name for name, _ in ingredient_lines], ["chicken breast"])
        self.assertEqual(other_lines, ["Mystery Dish: Ingredients could not be found."])
        self.assertEqual(total_line, "Estimated total: ~$40")

    def test_blank_lines_are_dropped(self):
        text = "chicken breast: 5kg (~$40)\n\nromaine lettuce: 2kg (~$8)\n\nEstimated total: ~$48"
        ingredient_lines, _, _ = _parse_ingredient_lines(text)

        self.assertEqual(len(ingredient_lines), 2)

    def test_no_total_line_present_is_empty_string(self):
        text = "chicken breast: 5kg (~$40)"
        _, _, total_line = _parse_ingredient_lines(text)

        self.assertEqual(total_line, "")

    def test_model_summary_lines_are_dropped_not_parsed_as_ingredients(self):
        # The model sometimes writes its own per-plate average / subtotal /
        # restated total -- kept, "Average cost per plate: ~$2.31" was parsed
        # as a fake ingredient and the response ended up with two disagreeing
        # per-plate figures. The agent recomputes these deterministically.
        text = (
            "chicken breast: 5kg (~$40)\n"
            "Average cost per plate: ~$2.31\n"
            "Subtotal: ~$40\n"
            "Cost per serving: ~$1.50\n"
            "Estimated total: ~$40"
        )
        ingredient_lines, other_lines, total_line = _parse_ingredient_lines(text)

        self.assertEqual([name for name, _ in ingredient_lines], ["chicken breast"])
        self.assertEqual(other_lines, [])
        self.assertEqual(total_line, "Estimated total: ~$40")

    def test_bare_total_variants_are_captured_as_the_total_line(self):
        for line in ["Total: ~$300", "Grand total ~$300", "Total cost: $300", "Overall total: ~$300"]:
            _, _, total_line = _parse_ingredient_lines(f"onion: 3kg (~$6)\n{line}")
            self.assertEqual(total_line, line, line)


class ToOneServingTests(unittest.TestCase):
    """A Recipe & Portion writeup that was already scaled to a headcount
    ("Full service -- quantities to prepare N servings ...") is divided
    back to one serving so this agent doesn't multiply by the headcount a
    second time."""

    def test_a_plain_writeup_is_returned_unchanged(self):
        text = "Grilled salmon: 150 g salmon, 90 g rice; 220 g plate."
        self.assertEqual(_to_one_serving(text), (text, 1))

    def test_a_batch_writeup_is_divided_back_and_the_preamble_dropped(self):
        text = (
            "Full service -- quantities to prepare 4 servings of each dish, scaled from the one-serving amounts:\n\n"
            "Grilled salmon: 600 g salmon, 1.2 L stock; sear 3-4 min, bake at 400 F; 220 g plate.\n"
            "Chickpea stew: 720 g chickpeas; simmer 20 min; 300 g bowl."
        )
        out, n = _to_one_serving(text)
        self.assertEqual(n, 4)
        self.assertNotIn("Full service", out)
        self.assertIn("150 g salmon", out)
        self.assertIn("300 ml stock", out)          # 1.2 L / 4, rolled down
        self.assertIn("180 g chickpeas", out)
        self.assertIn("3-4 min", out)               # times untouched
        self.assertIn("400 F", out)                 # temps untouched
        self.assertIn("220 g plate", out)           # per-plate size untouched
        self.assertIn("300 g bowl", out)            # per-bowl size untouched

    def test_scaled_to_one_is_treated_as_not_a_batch(self):
        text = "Full service -- quantities to prepare 1 serving:\n\nGrilled salmon: 150 g salmon."
        out, n = _to_one_serving(text)
        self.assertEqual(n, 1)
        self.assertEqual(out, text)


class CategorizeIngredientsTests(unittest.TestCase):
    def test_empty_list_makes_no_call(self):
        with patch.object(sla.llm_utils, "chat_sync") as chat_sync:
            result = _categorize_ingredients([])

        chat_sync.assert_not_called()
        self.assertEqual(result, {})

    def test_parses_a_valid_mapping(self):
        raw = json.dumps({"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"})
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = _categorize_ingredients(["chicken breast", "romaine lettuce"])

        self.assertEqual(result, {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"})

    def test_entries_with_an_invalid_category_are_dropped(self):
        raw = json.dumps({"chicken breast": "Meat & Poultry", "mystery item": "Snacks"})
        with patch.object(sla.llm_utils, "chat_sync", return_value=raw):
            result = _categorize_ingredients(["chicken breast", "mystery item"])

        self.assertEqual(result, {"chicken breast": "Meat & Poultry"})

    def test_malformed_json_returns_empty(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="not json"):
            result = _categorize_ingredients(["chicken breast"])

        self.assertEqual(result, {})

    def test_non_dict_json_returns_empty(self):
        with patch.object(sla.llm_utils, "chat_sync", return_value="[1, 2, 3]"):
            result = _categorize_ingredients(["chicken breast"])

        self.assertEqual(result, {})


class GroupByCategoryTests(unittest.TestCase):
    """The deterministic grouping step -- confirmed live that letting the
    main merge/cost LLM call also group by category let ingredients
    duplicate across sections; grouping the already-generated lines in
    code, from a separate name->category mapping, prevents that by
    construction."""

    def test_no_ingredient_lines_returns_text_unchanged(self):
        text = "I couldn't find any ingredients for this menu."
        self.assertEqual(_group_by_category(text, headcount=0), text)

    def test_groups_lines_under_their_category_in_canonical_order(self):
        text = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        mapping = {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping):
            result = _group_by_category(text, headcount=0)

        # Produce comes before Meat & Poultry in CATEGORIES, so it must be
        # rendered first regardless of the original line order.
        self.assertEqual(
            result,
            "Produce:\nromaine lettuce: 2kg (~$8)\nMeat & Poultry:\nchicken breast: 5kg (~$40)\nEstimated total: ~$48",
        )

    def test_every_ingredient_appears_exactly_once_even_with_many_items(self):
        names = [f"item{i}" for i in range(6)]
        text = "\n".join(f"{name}: 1kg (~$1)" for name in names) + "\nEstimated total: ~$6"
        # Deliberately map every item to the SAME category -- a case where
        # duplication would be most likely if grouping weren't purely a
        # by-construction partition of the original lines.
        mapping = {name: "Produce" for name in names}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping):
            result = _group_by_category(text, headcount=0)

        for name in names:
            self.assertEqual(result.count(f"{name}: 1kg"), 1)

    def test_unmapped_ingredient_defaults_to_other(self):
        text = "mystery ingredient: 1kg (~$1)\nEstimated total: ~$1"
        with patch.object(sla, "_categorize_ingredients", return_value={}):
            result = _group_by_category(text, headcount=0)

        self.assertEqual(result, "Other:\nmystery ingredient: 1kg (~$1)\nEstimated total: ~$1")

    def test_not_found_note_and_total_line_survive_grouping(self):
        text = (
            "chicken breast: 5kg (~$40)\n"
            "Dishes with no ingredient data found: Mystery Dish\n"
            "Estimated total: ~$40"
        )
        with patch.object(sla, "_categorize_ingredients", return_value={"chicken breast": "Meat & Poultry"}):
            result = _group_by_category(text, headcount=0)

        self.assertEqual(
            result,
            "Meat & Poultry:\nchicken breast: 5kg (~$40)\nDishes with no ingredient data found: Mystery Dish\nEstimated total: ~$40",
        )

    def test_empty_categories_are_skipped_entirely(self):
        text = "chicken breast: 5kg (~$40)\nEstimated total: ~$40"
        with patch.object(sla, "_categorize_ingredients", return_value={"chicken breast": "Meat & Poultry"}):
            result = _group_by_category(text, headcount=0)

        for category in sla.CATEGORIES:
            if category != "Meat & Poultry":
                self.assertNotIn(f"{category}:", result)


class RollUpLineTests(unittest.TestCase):
    """The scaling model prints the raw scaled figure ("5000g", "100 tbsp");
    _roll_up_line rewrites each line's quantity into a bulk unit, leaving
    the ingredient name and the cost untouched, and leaving anything it
    doesn't recognise exactly as written."""

    def test_grams_over_a_kilo_become_kilograms(self):
        self.assertEqual(_roll_up_line("scallops: 5000g (~$150)"), "scallops: 5 kg (~$150)")
        self.assertEqual(_roll_up_line("salmon: 12000 g (~$180)"), "salmon: 12 kg (~$180)")

    def test_millilitres_over_a_litre_become_litres(self):
        self.assertEqual(_roll_up_line("olive oil: 1500 ml (~$15)"), "olive oil: 1.5 L (~$15)")

    def test_spoons_convert_to_litres_or_cups(self):
        self.assertEqual(_roll_up_line("butter: 100 tbsp (~$10)"), "butter: 1.48 L (~$10)")
        self.assertEqual(_roll_up_line("lemon juice: 100 tsp (~$10)"), "lemon juice: 2.08 cups (~$10)")

    def test_ounces_over_a_pound_become_pounds(self):
        self.assertEqual(_roll_up_line("beef: 40 oz (~$30)"), "beef: 2.5 lb (~$30)")

    def test_thousands_separator_is_handled(self):
        self.assertEqual(_roll_up_line("flour: 12,000 g (~$9)"), "flour: 12 kg (~$9)")

    def test_count_based_items_are_left_alone(self):
        self.assertEqual(_roll_up_line("garlic: 100 cloves (~$5)"), "garlic: 100 cloves (~$5)")

    def test_amounts_below_the_threshold_are_left_alone(self):
        self.assertEqual(_roll_up_line("cream: 800 ml (~$4)"), "cream: 800 ml (~$4)")
        self.assertEqual(_roll_up_line("sugar: 8 tbsp (~$1)"), "sugar: 8 tbsp (~$1)")
        self.assertEqual(_roll_up_line("chicken breast: 5kg (~$40)"), "chicken breast: 5kg (~$40)")

    def test_non_numeric_quantities_are_left_alone(self):
        self.assertEqual(_roll_up_line("salt: Pinch (~$1)"), "salt: Pinch (~$1)")
        self.assertEqual(_roll_up_line("lime: Juice of 50 limes (~$5)"), "lime: Juice of 50 limes (~$5)")

    def test_a_line_with_no_cost_suffix_is_untouched(self):
        self.assertEqual(_roll_up_line("milk: 3000 ml"), "milk: 3000 ml")

    def test_roll_up_happens_in_build_category_sections(self):
        text = "salmon: 12000g (~$180)\nEstimated total: ~$180"
        sections, _other, total_line = _build_category_sections(text)
        all_lines = [line for _cat, lines in sections for line in lines]
        self.assertIn("salmon: 12 kg (~$180)", all_lines)
        self.assertEqual(total_line, "Estimated total: ~$180")


class DedupeIngredientLinesTests(unittest.TestCase):
    """The main merge pass sometimes emits the identical line twice in a
    row for the same ingredient despite the SYSTEM_PROMPT's "exactly one
    entry per distinct ingredient" instruction -- confirmed live (e.g.
    "garlic: 150 g (~$15)" appearing twice under Produce)."""

    def test_exact_duplicate_lines_are_collapsed_to_one(self):
        lines = [("garlic", "garlic: 150 g (~$15)"), ("garlic", "garlic: 150 g (~$15)")]
        result = _dedupe_ingredient_lines(lines)

        self.assertEqual(result, [("garlic", "garlic: 150 g (~$15)")])

    def test_duplicate_detection_is_case_and_whitespace_insensitive(self):
        lines = [("garlic", "Garlic:   150 g (~$15)"), ("garlic", "garlic: 150 g (~$15)")]
        result = _dedupe_ingredient_lines(lines)

        self.assertEqual(len(result), 1)

    def test_same_name_different_quantity_is_not_deduped(self):
        # A harder unit-summing problem this deliberately doesn't attempt
        # -- dropping either line here could undercount the true total.
        lines = [("garlic", "garlic: 150 g (~$15)"), ("garlic", "garlic: 90 g (~$9)")]
        result = _dedupe_ingredient_lines(lines)

        self.assertEqual(result, lines)

    def test_no_duplicates_returns_the_same_list(self):
        lines = [("garlic", "garlic: 150 g (~$15)"), ("onion", "onion: 2 kg (~$8)")]
        result = _dedupe_ingredient_lines(lines)

        self.assertEqual(result, lines)


class ParseTotalDollarsTests(unittest.TestCase):
    def test_parses_whole_dollar_amount(self):
        self.assertEqual(_parse_total_dollars("Estimated total: ~$450"), 450.0)

    def test_parses_amount_with_comma_thousands_separator(self):
        self.assertEqual(_parse_total_dollars("Estimated total: ~$1,234"), 1234.0)

    def test_parses_fractional_amount(self):
        self.assertEqual(_parse_total_dollars("Estimated total: ~$45.50"), 45.5)

    def test_no_dollar_amount_returns_none(self):
        self.assertIsNone(_parse_total_dollars("no total here"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_parse_total_dollars(""))


class AverageCostPerPlateLineTests(unittest.TestCase):
    """The per-plate figure is always computed in code from the total
    line's own parsed dollar amount and the target headcount, never left
    for the model to compute -- matching this project's established
    pattern of doing arithmetic in code rather than trusting the LLM
    with it."""

    def test_computes_average_from_total_and_headcount(self):
        result = _average_cost_per_plate_line("Estimated total: ~$450", 450)
        self.assertEqual(result, "Average cost per plate: ~$1")

    def test_rounds_to_cents_for_a_fractional_result(self):
        result = _average_cost_per_plate_line("Estimated total: ~$100", 3)
        self.assertEqual(result, "Average cost per plate: ~$33.33")

    def test_empty_total_line_returns_empty_string(self):
        self.assertEqual(_average_cost_per_plate_line("", 450), "")

    def test_zero_headcount_returns_empty_string_not_a_division_error(self):
        self.assertEqual(_average_cost_per_plate_line("Estimated total: ~$450", 0), "")

    def test_negative_headcount_returns_empty_string(self):
        self.assertEqual(_average_cost_per_plate_line("Estimated total: ~$450", -5), "")

    def test_unparseable_total_returns_empty_string(self):
        self.assertEqual(_average_cost_per_plate_line("Estimated total: unknown", 450), "")


class RecomputeTotalLineTests(unittest.TestCase):
    def test_sums_each_lines_cost(self):
        lines = [("garlic", "garlic: 150 g (~$15)"), ("onion", "onion: 2 kg (~$8)")]
        self.assertEqual(_recompute_total_line(lines), "Estimated total: ~$23")

    def test_drops_unnecessary_trailing_zeros(self):
        lines = [("garlic", "garlic: 150 g (~$15.50)"), ("onion", "onion: 2 kg (~$8.50)")]
        self.assertEqual(_recompute_total_line(lines), "Estimated total: ~$24")

    def test_keeps_meaningful_decimal_places(self):
        lines = [("garlic", "garlic: 150 g (~$15.25)")]
        self.assertEqual(_recompute_total_line(lines), "Estimated total: ~$15.25")

    def test_unparseable_line_cost_returns_none(self):
        lines = [("garlic", "garlic: 150 g (price unknown)")]
        self.assertIsNone(_recompute_total_line(lines))

    def test_empty_list_is_zero(self):
        self.assertEqual(_recompute_total_line([]), "Estimated total: ~$0")


class BuildCategorySectionsTests(unittest.TestCase):
    def test_exact_duplicate_ingredient_is_collapsed_and_total_is_recomputed(self):
        text = (
            "garlic: 150 g (~$15)\n"
            "garlic: 150 g (~$15)\n"
            "onion: 2 kg (~$8)\n"
            "Estimated total: ~$38"
        )
        with patch.object(sla, "_categorize_ingredients", return_value={"garlic": "Produce", "onion": "Produce"}):
            sections, other_lines, total_line = _build_category_sections(text)

        produce_lines = dict(sections)["Produce"]
        self.assertEqual(produce_lines.count("garlic: 150 g (~$15)"), 1)
        # The model's original total (~$38) double-counted the duplicate
        # garlic line -- the recomputed total must reflect only what's
        # actually shown: 15 + 8 = 23, not the stale 38.
        self.assertEqual(total_line, "Estimated total: ~$23")

    def test_no_duplicates_keeps_the_original_total_line_untouched(self):
        text = "garlic: 150 g (~$15)\nEstimated total: ~$15"
        with patch.object(sla, "_categorize_ingredients", return_value={"garlic": "Produce"}):
            sections, other_lines, total_line = _build_category_sections(text)

        self.assertEqual(total_line, "Estimated total: ~$15")


    def test_no_ingredient_lines_returns_empty_sections(self):
        with patch.object(sla, "_categorize_ingredients") as categorize:
            sections, other_lines, total_line = _build_category_sections("nothing to see here")

        categorize.assert_not_called()
        self.assertEqual(sections, [])

    def test_returns_sections_in_canonical_category_order_regardless_of_input_order(self):
        text = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        mapping = {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping):
            sections, other_lines, total_line = _build_category_sections(text)

        self.assertEqual([category for category, _ in sections], ["Produce", "Meat & Poultry"])
        self.assertEqual(total_line, "Estimated total: ~$48")


class RenderHtmlFromSectionsTests(unittest.TestCase):
    """The HTML rendering (shown in the browser's Analysis report popup,
    same mechanism Nutrition's chart already uses) puts each category name
    in bold and each ingredient on its own line as a real list item."""

    def test_empty_sections_is_empty_string(self):
        self.assertEqual(_render_html_from_sections([], [], "", headcount=0), "")

    def test_bolds_the_category_name(self):
        html = _render_html_from_sections([("Produce", ["garlic: 1kg (~$5)"])], [], "", headcount=0)
        self.assertIn("<strong>Produce</strong>", html)

    def test_one_list_item_per_ingredient(self):
        html = _render_html_from_sections(
            [("Produce", ["garlic: 1kg (~$5)", "onion: 2kg (~$4)"])], [], "", headcount=0
        )
        self.assertIn("<li>garlic: 1kg (~$5)</li>", html)
        self.assertIn("<li>onion: 2kg (~$4)</li>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_multiple_categories_each_get_their_own_bold_heading_and_list(self):
        html = _render_html_from_sections(
            [("Produce", ["garlic: 1kg (~$5)"]), ("Meat & Poultry", ["chicken: 2kg (~$10)"])], [], "", headcount=0
        )
        self.assertIn("<strong>Produce</strong>", html)
        self.assertIn("<strong>Meat &amp; Poultry</strong>", html)
        self.assertEqual(html.count("<ul>"), 2)

    def test_total_line_is_bolded(self):
        html = _render_html_from_sections([("Produce", ["garlic: 1kg (~$5)"])], [], "Estimated total: ~$5", headcount=0)
        self.assertIn("<strong>Estimated total: ~$5</strong>", html)

    def test_other_lines_are_included_without_bold(self):
        html = _render_html_from_sections(
            [("Produce", ["garlic: 1kg (~$5)"])], ["Dishes with no ingredient data found: Mystery Dish"], "", headcount=0
        )
        self.assertIn("Dishes with no ingredient data found: Mystery Dish", html)

    def test_html_special_characters_are_escaped(self):
        html = _render_html_from_sections([("Produce", ['garlic <script>alert("x")</script>: 1kg'])], [], "", headcount=0)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_average_cost_per_plate_follows_the_total_line_in_bold(self):
        html = _render_html_from_sections(
            [("Produce", ["garlic: 1kg (~$5)"])], [], "Estimated total: ~$100", headcount=50
        )
        self.assertIn("<strong>Estimated total: ~$100</strong>", html)
        self.assertIn("<strong>Average cost per plate: ~$2</strong>", html)

    def test_no_total_line_means_no_per_plate_line(self):
        html = _render_html_from_sections([("Produce", ["garlic: 1kg (~$5)"])], [], "", headcount=50)
        self.assertNotIn("Average cost per plate", html)


class CategorizedResponseTests(unittest.TestCase):
    """The text and html renderings must come from exactly ONE
    categorization pass, not one each -- otherwise the two could
    disagree (or the classifier gets called twice for no reason)."""

    def test_text_and_html_agree_and_categorize_only_once(self):
        raw = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        mapping = {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping) as categorize:
            result = _categorized_response(raw, headcount=0)

        categorize.assert_called_once()
        self.assertIn("Produce:\nromaine lettuce", result["text"])
        self.assertIn("<strong>Produce</strong>", result["html"])
        self.assertIn("<li>chicken breast: 5kg (~$40)</li>", result["html"])

    def test_no_ingredients_returns_fallback_text_and_empty_html(self):
        raw = "I couldn't find any ingredients for this menu."
        with patch.object(sla, "_categorize_ingredients") as categorize:
            result = _categorized_response(raw, headcount=100)

        categorize.assert_not_called()
        self.assertEqual(result["text"], raw)
        self.assertEqual(result["html"], "")

    def test_includes_average_cost_per_plate_when_headcount_given(self):
        raw = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        mapping = {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping):
            result = _categorized_response(raw, headcount=48)

        self.assertIn("Average cost per plate: ~$1", result["text"])
        self.assertIn("<strong>Average cost per plate: ~$1</strong>", result["html"])

    def test_html_includes_a_chart_before_the_list(self):
        raw = "chicken breast: 5kg (~$40)\nromaine lettuce: 2kg (~$8)\nEstimated total: ~$48"
        mapping = {"chicken breast": "Meat & Poultry", "romaine lettuce": "Produce"}
        with patch.object(sla, "_categorize_ingredients", return_value=mapping):
            result = _categorized_response(raw, headcount=0)

        chart_index = result["html"].find("<img")
        list_index = result["html"].find("<strong>Produce</strong>")
        self.assertNotEqual(chart_index, -1)
        self.assertLess(chart_index, list_index)


class FormatDollarsTests(unittest.TestCase):
    def test_whole_number_has_no_decimal(self):
        self.assertEqual(_format_dollars(23.0), "$23")

    def test_fractional_amount_keeps_two_decimals(self):
        self.assertEqual(_format_dollars(23.5), "$23.5")

    def test_zero_is_dollar_zero(self):
        self.assertEqual(_format_dollars(0), "$0")


class CategoryCostTotalsTests(unittest.TestCase):
    def test_sums_costs_within_each_category(self):
        sections = [("Produce", ["garlic: 1kg (~$5)", "onion: 2kg (~$8)"]), ("Meat & Poultry", ["beef: 3kg (~$15)"])]
        self.assertEqual(_category_cost_totals(sections), [("Produce", 13.0), ("Meat & Poultry", 15.0)])

    def test_unparseable_line_contributes_zero_not_an_error(self):
        sections = [("Produce", ["garlic: price unknown", "onion: 2kg (~$8)"])]
        self.assertEqual(_category_cost_totals(sections), [("Produce", 8.0)])

    def test_empty_sections_is_empty(self):
        self.assertEqual(_category_cost_totals([]), [])


class BuildCostChartTests(unittest.TestCase):
    """The cost-by-category chart -- colors come from _CATEGORY_COLORS,
    keyed by category name, so a category's color never shifts depending
    on which other categories happen to be present in a given response."""

    def test_empty_sections_returns_no_chart(self):
        self.assertEqual(_build_cost_chart([]), "")

    def test_all_zero_cost_sections_returns_no_chart(self):
        sections = [("Produce", ["garlic: price unknown"])]
        self.assertEqual(_build_cost_chart(sections), "")

    def test_produces_an_image_tag_for_a_real_category(self):
        sections = [("Produce", ["garlic: 1kg (~$5)"])]
        chart = _build_cost_chart(sections)
        self.assertIn("<img", chart)

    def test_zero_cost_categories_are_excluded_from_the_chart(self):
        sections = [("Produce", ["garlic: 1kg (~$5)"]), ("Frozen", ["mystery item: price unknown"])]
        # Can't inspect pixel content of the PNG itself here, but the
        # zero-cost category must not reach render_bar_chart_png at all.
        with patch.object(sla, "render_bar_chart_png", return_value="<img>") as render:
            _build_cost_chart(sections)

        rows = render.call_args[0][1]
        labels = [row[0] for row in rows]
        self.assertEqual(labels, ["Produce"])

    def test_colors_come_from_the_fixed_category_table(self):
        sections = [("Meat & Poultry", ["beef: 1kg (~$5)"]), ("Produce", ["garlic: 1kg (~$5)"])]
        with patch.object(sla, "render_bar_chart_png", return_value="<img>") as render:
            _build_cost_chart(sections)

        rows = render.call_args[0][1]
        colors = {row[0]: row[3] for row in rows}
        self.assertEqual(colors["Meat & Poultry"], sla._CATEGORY_COLORS["Meat & Poultry"])
        self.assertEqual(colors["Produce"], sla._CATEGORY_COLORS["Produce"])

    def test_rows_stay_in_canonical_category_order_not_sorted_by_cost(self):
        # Meat & Poultry has the bigger cost but comes after Produce in
        # CATEGORIES, and section order already reflects that -- the
        # chart must not re-sort by value.
        sections = [("Produce", ["garlic: 1kg (~$5)"]), ("Meat & Poultry", ["beef: 1kg (~$50)"])]
        with patch.object(sla, "render_bar_chart_png", return_value="<img>") as render:
            _build_cost_chart(sections)

        rows = render.call_args[0][1]
        self.assertEqual([row[0] for row in rows], ["Produce", "Meat & Poultry"])


if __name__ == "__main__":
    unittest.main()
