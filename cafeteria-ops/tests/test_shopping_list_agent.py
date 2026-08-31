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
    _parse_ingredient_lines,
    _parse_total_dollars,
    _recompute_total_line,
    _render_html_from_sections,
    _render_text_from_sections,
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

        with patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
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
        no_match = json.dumps({"query": "xyz", "results": []})

        with patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [[no_match]]
            result = sla._fetch_dish_ingredients(["totally made up dish"])

        parallel.assert_called_once()  # only the search round, no detail round
        self.assertIsNone(result["totally made up dish"])

    def test_mixed_found_and_not_found_dishes(self):
        search_results = [
            json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]}),
            json.dumps({"query": "xyz", "results": []}),
        ]
        detail_results = [json.dumps({"id": "52", "name": "Nutty Chicken Curry", "ingredients": ["200g chicken"]})]

        with patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [search_results, detail_results]
            result = sla._fetch_dish_ingredients(["chicken curry", "made up dish"])

        self.assertIsNotNone(result["chicken curry"])
        self.assertIsNone(result["made up dish"])

    def test_detail_lookup_failure_leaves_dish_as_none(self):
        search_result = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]})

        with patch.object(sla.mcp_client, "call_tools_parallel_sync") as parallel:
            parallel.side_effect = [[search_result], [None]]
            result = sla._fetch_dish_ingredients(["chicken curry"])

        self.assertIsNone(result["chicken curry"])


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
