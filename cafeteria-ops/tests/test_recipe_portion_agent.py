import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.recipe_portion_specialist import recipe_portion_agent as rpa
from agents.recipe_portion_specialist.recipe_portion_agent import (
    _dish_query,
    _extract_dishes,
    _fetch_all_recipes,
    _fetch_recipe_details,
    _non_empty_results,
    RecipePortionAgent,
)


class DishQueryTests(unittest.TestCase):
    def test_broad_multi_day_planning_request_has_no_dish_query(self):
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal."
        )
        self.assertIsNone(_dish_query(text))

    def test_broad_request_with_max_words_instruction_still_has_no_dish_query(self):
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal.\n\n"
            "[Write approximately 400 words total. If this request covers multiple "
            "days, items, or parts, you MUST address EVERY one of them.]"
        )
        self.assertIsNone(_dish_query(text))

    def test_direct_recipe_request_extracts_the_dish_name(self):
        text = "Recipe Specialist, give me a recipe for chicken curry"
        self.assertEqual(_dish_query(text), "chicken curry")

    def test_direct_recipe_request_with_max_words_instruction_still_extracts_dish(self):
        text = (
            "Recipe Specialist, give me a recipe for chicken curry\n\n"
            "[Write approximately 125 words. If this request covers multiple days, "
            "items, or parts, you MUST address EVERY one of them.]"
        )
        self.assertEqual(_dish_query(text), "chicken curry")

    def test_bare_dish_name_is_used_as_is(self):
        self.assertEqual(_dish_query("lentil soup"), "lentil soup")

    def test_empty_text_has_no_dish_query(self):
        self.assertIsNone(_dish_query(""))


class NonEmptyResultsTests(unittest.TestCase):
    def test_empty_results_list_is_treated_as_no_data(self):
        self.assertIsNone(_non_empty_results('{"query": "xyz", "results": []}'))

    def test_populated_results_list_is_passed_through(self):
        raw = '{"query": "chicken curry", "results": [{"id": "1"}]}'
        self.assertEqual(_non_empty_results(raw), raw)

    def test_none_input_is_none(self):
        self.assertIsNone(_non_empty_results(None))

    def test_non_json_input_passes_through_unchanged(self):
        self.assertEqual(_non_empty_results("not json"), "not json")

    def test_error_shaped_json_passes_through_unchanged(self):
        raw = '{"error": "TheMealDB returned 500"}'
        self.assertEqual(_non_empty_results(raw), raw)


class FetchRecipeDetailsTests(unittest.TestCase):
    """search_by_name only returns a summary (id/name/category) -- the real
    ingredients/instructions require a second lookup by the top match's id.
    Confirmed live this was previously skipped entirely: the agent claimed
    "real recipe data" while actually having the LLM invent every
    ingredient list from scratch."""

    def test_none_summary_makes_no_call(self):
        with patch.object(rpa.mcp_client, "call_tool_sync_or_none") as call:
            result = _fetch_recipe_details(None)

        call.assert_not_called()
        self.assertIsNone(result)

    def test_summary_with_no_results_makes_no_call(self):
        summary = json.dumps({"query": "xyz", "results": []})
        with patch.object(rpa.mcp_client, "call_tool_sync_or_none") as call:
            result = _fetch_recipe_details(summary)

        call.assert_not_called()
        self.assertIsNone(result)

    def test_found_match_fetches_real_ingredients_by_id(self):
        summary = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]})
        detail = json.dumps({"id": "52", "name": "Nutty Chicken Curry", "ingredients": ["200g chicken breast"]})

        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=detail) as call:
            result = _fetch_recipe_details(summary)

        call.assert_called_once_with("themealdb", "get_recipe_details", {"meal_id": "52"})
        self.assertEqual(result, detail)

    def test_detail_lookup_with_no_ingredients_is_none(self):
        summary = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]})
        detail = json.dumps({"id": "52", "name": "Nutty Chicken Curry", "ingredients": []})

        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=detail):
            result = _fetch_recipe_details(summary)

        self.assertIsNone(result)

    def test_detail_lookup_failure_is_none(self):
        summary = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Nutty Chicken Curry"}]})

        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=None):
            result = _fetch_recipe_details(summary)

        self.assertIsNone(result)


class ExtractDishesTests(unittest.TestCase):
    def test_parses_dishes_from_llm_json_response(self):
        raw = '{"dishes": ["Grilled Chicken Caesar Salad", "Lentil Soup"]}'
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            result = _extract_dishes("Day 1: Grilled Chicken Caesar Salad. Day 2: Lentil Soup.")

        self.assertEqual(result, ["Grilled Chicken Caesar Salad", "Lentil Soup"])

    def test_response_with_no_json_object_is_empty(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="sorry, I can't help with that"):
            result = _extract_dishes("some menu text")

        self.assertEqual(result, [])

    def test_malformed_json_is_empty(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="{dishes: [oops]}"):
            result = _extract_dishes("some menu text")

        self.assertEqual(result, [])

    def test_blank_or_non_string_entries_are_dropped(self):
        raw = '{"dishes": ["Lentil Soup", "  ", 5, ""]}'
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            result = _extract_dishes("some menu text")

        self.assertEqual(result, ["Lentil Soup"])


class FetchAllRecipesTests(unittest.TestCase):
    """Batched two-round lookup (search round, then detail round) across
    every dish in a whole week's menu -- same two-stage shape as
    _fetch_recipe_details, but parallelized."""

    def test_empty_dish_list_makes_no_calls(self):
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync") as call:
            result = _fetch_all_recipes([])

        call.assert_not_called()
        self.assertEqual(result, {})

    def test_every_dish_found_maps_to_its_real_detail(self):
        search_results = [
            json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]}),
            json.dumps({"query": "Lentil Soup", "results": [{"id": "77", "name": "Lentil Soup"}]}),
        ]
        detail_results = [
            json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]}),
            json.dumps({"id": "77", "name": "Lentil Soup", "ingredients": ["100g lentils"]}),
        ]
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_recipes(["Chicken Curry", "Lentil Soup"])

        self.assertEqual(call.call_count, 2)
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Lentil Soup": detail_results[1]})

    def test_dish_with_no_search_match_maps_to_none_without_a_detail_call(self):
        search_results = [
            json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]}),
            json.dumps({"query": "Mystery Dish", "results": []}),
        ]
        detail_results = [
            json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]}),
        ]
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_recipes(["Chicken Curry", "Mystery Dish"])

        # Only the one real match should ever reach the detail round.
        detail_requests = call.call_args_list[1].args[0]
        self.assertEqual(detail_requests, [("themealdb", "get_recipe_details", {"meal_id": "52"})])
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Mystery Dish": None})

    def test_no_dish_found_at_all_skips_the_detail_round_entirely(self):
        search_results = [json.dumps({"query": "Mystery Dish", "results": []})]
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=search_results) as call:
            result = _fetch_all_recipes(["Mystery Dish"])

        call.assert_called_once()  # search round only, no detail round
        self.assertEqual(result, {"Mystery Dish": None})

    def test_detail_lookup_with_no_ingredients_maps_to_none(self):
        search_results = [json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]})]
        detail_results = [json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": []})]
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]):
            result = _fetch_all_recipes(["Chicken Curry"])

        self.assertEqual(result, {"Chicken Curry": None})


class OnObservedUtteranceTests(unittest.TestCase):
    """The Recipe & Portion Specialist watches Pass-Through broadcast traffic
    for the Menu Designer's proposed menu, keyed per-conversation, so it can
    later be asked to work out recipes/amounts for the WHOLE saved menu."""

    def test_saves_text_from_the_menu_designer(self):
        agent = RecipePortionAgent()

        agent.on_observed_utterance("conv-1", rpa._MENU_DESIGNER_SERVICE_URL, "Day 1: Chicken Curry.")

        self.assertEqual(agent._observed_menus, {"conv-1": "Day 1: Chicken Curry."})

    def test_matches_the_menu_designer_uri_case_and_slash_insensitively(self):
        agent = RecipePortionAgent()
        loud_uri = rpa._MENU_DESIGNER_SERVICE_URL.upper().rstrip("/")

        agent.on_observed_utterance("conv-1", loud_uri, "Day 1: Chicken Curry.")

        self.assertEqual(agent._observed_menus, {"conv-1": "Day 1: Chicken Curry."})

    def test_ignores_utterances_from_other_speakers(self):
        agent = RecipePortionAgent()

        agent.on_observed_utterance("conv-1", "http://127.0.0.1:8302/", "some nutrition commentary")

        self.assertEqual(agent._observed_menus, {})

    def test_a_later_menu_replaces_the_earlier_one_for_the_same_conversation(self):
        agent = RecipePortionAgent()

        agent.on_observed_utterance("conv-1", rpa._MENU_DESIGNER_SERVICE_URL, "first draft menu")
        agent.on_observed_utterance("conv-1", rpa._MENU_DESIGNER_SERVICE_URL, "revised menu")

        self.assertEqual(agent._observed_menus, {"conv-1": "revised menu"})

    def test_different_conversations_are_kept_separate(self):
        agent = RecipePortionAgent()

        agent.on_observed_utterance("conv-1", rpa._MENU_DESIGNER_SERVICE_URL, "menu for conv 1")
        agent.on_observed_utterance("conv-2", rpa._MENU_DESIGNER_SERVICE_URL, "menu for conv 2")

        self.assertEqual(agent._observed_menus, {"conv-1": "menu for conv 1", "conv-2": "menu for conv 2"})


class ProcessUtteranceBranchingTests(unittest.TestCase):
    """process_utterance is a 3-way dispatcher: a single named dish wins
    first, then a saved whole-week menu, then a general-reasoning fallback."""

    def _make_agent(self, conv_id="conv-1", saved_menu=""):
        agent = RecipePortionAgent()
        agent._current_conv_id = conv_id
        if saved_menu:
            agent._observed_menus[conv_id] = saved_menu
        return agent

    def test_single_named_dish_takes_priority_even_with_a_saved_menu(self):
        agent = self._make_agent(saved_menu="Day 1: Lentil Soup.")
        with patch.object(agent, "_respond_for_one_dish", return_value="one-dish reply") as one_dish, \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu:
            result = agent.process_utterance("give me a recipe for chicken curry")

        one_dish.assert_called_once_with("give me a recipe for chicken curry", "chicken curry")
        whole_menu.assert_not_called()
        self.assertEqual(result, "one-dish reply")

    def test_broad_request_with_saved_menu_and_extractable_dishes_uses_whole_menu(self):
        agent = self._make_agent(saved_menu="Day 1: Chicken Curry. Day 2: Lentil Soup.")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]) as extract, \
             patch.object(agent, "_respond_for_whole_menu", return_value="whole-menu reply") as whole_menu:
            result = agent.process_utterance(broad_text)

        extract.assert_called_once_with("Day 1: Chicken Curry. Day 2: Lentil Soup.")
        whole_menu.assert_called_once_with("Day 1: Chicken Curry. Day 2: Lentil Soup.", ["Chicken Curry", "Lentil Soup"])
        self.assertEqual(result, "whole-menu reply")

    def test_broad_request_with_no_saved_menu_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_menu="")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(rpa.llm_utils, "chat_sync", return_value="fallback reply") as chat_sync:
            result = agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()
        self.assertEqual(result["text"], "fallback reply")

    def test_saved_menu_that_extracts_no_dishes_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_menu="not actually a menu")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(rpa, "_extract_dishes", return_value=[]), \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(rpa.llm_utils, "chat_sync", return_value="fallback reply") as chat_sync:
            result = agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()
        self.assertEqual(result["text"], "fallback reply")


class RespondForWholeMenuTests(unittest.TestCase):
    def test_asks_for_one_serving_not_a_headcount(self):
        agent = RecipePortionAgent()
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Lentil Soup": None}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("Day 1: Lentil Soup.", ["Lentil Soup"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("ONE serving of EVERY dish", user_message)
        self.assertNotIn("people", user_message)

    def test_per_dish_word_budget_is_computed_and_injected(self):
        # Same fix as Menu Designer's per-day budget hint: without explicit
        # arithmetic, the model exhausts the word budget on the first dish
        # and _limit_words truncates the reply before later dishes are ever
        # covered (confirmed live with a 2-dish menu at a 300-word budget).
        agent = RecipePortionAgent()
        agent._current_max_words = 300
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Chicken Curry": None, "Lentil Soup": None, "Beef Stew": None}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu(
                "Day 1: Chicken Curry. Day 2: Lentil Soup. Day 3: Beef Stew.",
                ["Chicken Curry", "Lentil Soup", "Beef Stew"],
            )

        user_message = chat_sync.call_args[0][1]
        self.assertIn("This menu has 3 dishes", user_message)
        self.assertIn("100 words", user_message)  # 300 // 3

    def test_per_dish_word_budget_never_drops_below_the_floor(self):
        agent = RecipePortionAgent()
        agent._current_max_words = 20
        dishes = [f"Dish {i}" for i in range(7)]
        with patch.object(rpa, "_fetch_all_recipes", return_value={d: None for d in dishes}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("a menu", dishes)

        user_message = chat_sync.call_args[0][1]
        self.assertIn("20 words", user_message)  # max(20, 20 // 7) == 20

    def test_dishes_with_no_recipe_data_are_named_not_silently_dropped(self):
        agent = RecipePortionAgent()
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Lentil Soup": None, "Chicken Curry": '{"ingredients": ["200g chicken"]}'}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("Day 1: Lentil Soup. Day 2: Chicken Curry.", ["Lentil Soup", "Chicken Curry"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Dishes with no recipe data found: Lentil Soup", user_message)
        self.assertIn("Chicken Curry", user_message)

    def test_multi_dish_response_becomes_an_html_list(self):
        agent = RecipePortionAgent()
        raw_reply = "Chicken curry: 150g chicken.\nLentil soup: 100g lentils."
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Chicken Curry": None, "Lentil Soup": None}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent._respond_for_whole_menu("Day 1: Chicken Curry. Day 2: Lentil Soup.", ["Chicken Curry", "Lentil Soup"])

        self.assertEqual(result["text"], raw_reply)
        self.assertEqual(result["html"], "<ul><li>Chicken curry: 150g chicken.</li><li>Lentil soup: 100g lentils.</li></ul>")


class RespondForOneDishHtmlTests(unittest.TestCase):
    def test_single_dish_response_has_no_html_list(self):
        agent = RecipePortionAgent()
        raw_reply = "Use 150g chicken breast, 30g romaine lettuce, and 1 tbsp Caesar dressing."
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=[None, None]), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent._respond_for_one_dish("give me a recipe for chicken curry", "chicken curry")

        self.assertEqual(result["text"], raw_reply)
        self.assertEqual(result["html"], "")


if __name__ == "__main__":
    unittest.main()
