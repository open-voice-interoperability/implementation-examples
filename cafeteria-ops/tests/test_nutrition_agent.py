import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.nutrition_specialist import nutrition_agent as na
from agents.nutrition_specialist.nutrition_agent import (
    _extract_dishes,
    _fetch_all_nutrients,
    _food_query,
    NutritionAgent,
)


class FoodQueryTests(unittest.TestCase):
    """_food_query decides whether a USDA FDC search is even worth doing --
    a live cascade test found a broad five-day menu-planning request (no
    food named at all) getting searched verbatim, returning an unrelated
    branded cheeseburger that the agent then wrote a whole "assessment" of."""

    def test_broad_multi_day_planning_request_has_no_food_query(self):
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal."
        )
        self.assertIsNone(_food_query(text))

    def test_broad_request_with_max_words_instruction_still_has_no_food_query(self):
        # The maxWords slider's instruction (appended by
        # convener._question_text) is present on almost every real request
        # and must not itself be mistaken for the food being asked about.
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal.\n\n"
            "[Write approximately 400 words total. If this request covers multiple "
            "days, items, or parts, you MUST address EVERY one of them: give one "
            "compact entry per part (a short phrase or one sentence each), not a full "
            "paragraph on just the first. A short answer that covers every part is "
            "better than a longer one that only covers the first. Never stop after "
            "the first part while parts remain unaddressed.]"
        )
        self.assertIsNone(_food_query(text))

    def test_direct_calorie_question_extracts_the_food_name(self):
        text = "Nutrition Specialist, how many calories are in grilled chicken breast?"
        self.assertEqual(_food_query(text), "grilled chicken breast")

    def test_direct_calorie_question_with_max_words_instruction_still_extracts_food(self):
        text = (
            "Nutrition Specialist, how many calories are in grilled chicken breast?\n\n"
            "[Write approximately 125 words. If this request covers multiple days, "
            "items, or parts, you MUST address EVERY one of them.]"
        )
        self.assertEqual(_food_query(text), "grilled chicken breast")

    def test_bare_food_name_is_used_as_is(self):
        self.assertEqual(_food_query("brown rice"), "brown rice")

    def test_vague_menu_item_referent_has_no_food_query(self):
        self.assertIsNone(_food_query("evaluate this menu item"))

    def test_empty_text_has_no_food_query(self):
        self.assertIsNone(_food_query(""))

    def test_compound_calories_and_sodium_question_extracts_the_food_name(self):
        # Confirmed live: only the "how much sodium is in" half matched the
        # old framing pattern, leaving "how many calories and" attached to
        # the food name -- which pushed the cleaned text over the 8-word cap
        # and returned None. With a menu already on the floor, that silently
        # produced a whole-menu nutrition dump instead of answering about
        # the food actually named.
        text = "Nutrition Specialist, how many calories and how much sodium is in a grilled chicken caesar wrap?"
        self.assertEqual(_food_query(text), "grilled chicken caesar wrap")

    def test_compound_question_with_sodium_first_extracts_the_food_name(self):
        text = "Nutrition Specialist, how much sodium and how many calories are in a grilled chicken caesar wrap?"
        self.assertEqual(_food_query(text), "grilled chicken caesar wrap")


class ExtractDishesTests(unittest.TestCase):
    def test_parses_dishes_from_llm_json_response(self):
        raw = '{"dishes": ["Grilled Chicken Caesar Salad", "Lentil Soup"]}'
        with patch.object(na.llm_utils, "chat_sync", return_value=raw):
            result = _extract_dishes("Grilled Chicken Caesar Salad: 150g chicken. Lentil Soup: 100g lentils.")

        self.assertEqual(result, ["Grilled Chicken Caesar Salad", "Lentil Soup"])

    def test_response_with_no_json_object_is_empty(self):
        with patch.object(na.llm_utils, "chat_sync", return_value="sorry, I can't help with that"):
            result = _extract_dishes("some recipe text")

        self.assertEqual(result, [])

    def test_malformed_json_is_empty(self):
        with patch.object(na.llm_utils, "chat_sync", return_value="{dishes: [oops]}"):
            result = _extract_dishes("some recipe text")

        self.assertEqual(result, [])

    def test_blank_or_non_string_entries_are_dropped(self):
        raw = '{"dishes": ["Lentil Soup", "  ", 5, ""]}'
        with patch.object(na.llm_utils, "chat_sync", return_value=raw):
            result = _extract_dishes("some recipe text")

        self.assertEqual(result, ["Lentil Soup"])


class FetchAllNutrientsTests(unittest.TestCase):
    """Batched two-round lookup (search round, then detail round) across
    every dish in a whole week's menu -- same two-stage shape as
    recipe_portion_agent.py's _fetch_all_recipes."""

    def test_empty_dish_list_makes_no_calls(self):
        with patch.object(na.mcp_client, "call_tools_parallel_sync") as call:
            result = _fetch_all_nutrients([])

        call.assert_not_called()
        self.assertEqual(result, {})

    def test_every_dish_found_maps_to_its_real_detail(self):
        search_results = [
            json.dumps({"query": "Chicken Curry", "results": [{"fdcId": "111"}]}),
            json.dumps({"query": "Lentil Soup", "results": [{"fdcId": "222"}]}),
        ]
        detail_results = [
            json.dumps({"fdcId": "111", "description": "Chicken Curry", "calories": 350}),
            json.dumps({"fdcId": "222", "description": "Lentil Soup", "calories": 210}),
        ]
        with patch.object(na.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_nutrients(["Chicken Curry", "Lentil Soup"])

        self.assertEqual(call.call_count, 2)
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Lentil Soup": detail_results[1]})

    def test_dish_with_no_search_match_maps_to_none_without_a_detail_call(self):
        search_results = [
            json.dumps({"query": "Chicken Curry", "results": [{"fdcId": "111"}]}),
            json.dumps({"query": "Mystery Dish", "results": []}),
        ]
        detail_results = [
            json.dumps({"fdcId": "111", "description": "Chicken Curry", "calories": 350}),
        ]
        with patch.object(na.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_nutrients(["Chicken Curry", "Mystery Dish"])

        detail_requests = call.call_args_list[1].args[0]
        self.assertEqual(detail_requests, [("usda_fdc", "get_food_details", {"fdc_id": "111"})])
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Mystery Dish": None})

    def test_no_dish_found_at_all_skips_the_detail_round_entirely(self):
        search_results = [json.dumps({"query": "Mystery Dish", "results": []})]
        with patch.object(na.mcp_client, "call_tools_parallel_sync", return_value=search_results) as call:
            result = _fetch_all_nutrients(["Mystery Dish"])

        call.assert_called_once()
        self.assertEqual(result, {"Mystery Dish": None})


class OnObservedUtteranceTests(unittest.TestCase):
    """The Nutrition Specialist watches Pass-Through broadcast traffic for
    the Recipe & Portion Specialist's one-serving recipe writeup, keyed
    per-conversation, so it can later be asked to work out per-serving
    nutrition for the WHOLE saved menu."""

    def test_saves_text_from_recipe_portion(self):
        agent = NutritionAgent()

        agent.on_observed_utterance("conv-1", na._RECIPE_PORTION_SERVICE_URL, "Chicken Curry: 150g chicken breast.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken Curry: 150g chicken breast."})

    def test_matches_the_recipe_portion_uri_case_and_slash_insensitively(self):
        agent = NutritionAgent()
        loud_uri = na._RECIPE_PORTION_SERVICE_URL.upper().rstrip("/")

        agent.on_observed_utterance("conv-1", loud_uri, "Chicken Curry: 150g chicken breast.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken Curry: 150g chicken breast."})

    def test_ignores_utterances_from_other_speakers(self):
        agent = NutritionAgent()

        agent.on_observed_utterance("conv-1", "http://127.0.0.1:8301/", "some menu designer commentary")

        self.assertEqual(agent._observed_recipes, {})

    def test_different_conversations_are_kept_separate(self):
        agent = NutritionAgent()

        agent.on_observed_utterance("conv-1", na._RECIPE_PORTION_SERVICE_URL, "recipes for conv 1")
        agent.on_observed_utterance("conv-2", na._RECIPE_PORTION_SERVICE_URL, "recipes for conv 2")

        self.assertEqual(agent._observed_recipes, {"conv-1": "recipes for conv 1", "conv-2": "recipes for conv 2"})


class ProcessUtteranceBranchingTests(unittest.TestCase):
    """process_utterance is a 3-way dispatcher: a single named food wins
    first, then a saved whole-menu recipe writeup, then a general-reasoning
    fallback -- same shape as recipe_portion_agent.py's dispatcher."""

    def _make_agent(self, conv_id="conv-1", saved_recipes=""):
        agent = NutritionAgent()
        agent._current_conv_id = conv_id
        if saved_recipes:
            agent._observed_recipes[conv_id] = saved_recipes
        return agent

    def test_single_named_food_takes_priority_even_with_saved_recipes(self):
        agent = self._make_agent(saved_recipes="Lentil Soup: 100g lentils.")
        with patch.object(agent, "_respond_for_one_food", return_value="one-food reply") as one_food, \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu:
            result = agent.process_utterance("how many calories are in grilled chicken breast?")

        one_food.assert_called_once_with("how many calories are in grilled chicken breast?", "grilled chicken breast")
        whole_menu.assert_not_called()
        self.assertEqual(result, "one-food reply")

    def test_broad_request_with_saved_recipes_and_extractable_dishes_uses_whole_menu(self):
        agent = self._make_agent(saved_recipes="Chicken Curry: 150g chicken. Lentil Soup: 100g lentils.")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(na, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]) as extract, \
             patch.object(agent, "_respond_for_whole_menu", return_value="whole-menu reply") as whole_menu:
            result = agent.process_utterance(broad_text)

        extract.assert_called_once_with("Chicken Curry: 150g chicken. Lentil Soup: 100g lentils.")
        whole_menu.assert_called_once_with("Chicken Curry: 150g chicken. Lentil Soup: 100g lentils.", ["Chicken Curry", "Lentil Soup"])
        self.assertEqual(result, "whole-menu reply")

    def test_broad_request_with_no_saved_recipes_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_recipes="")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()

    def test_saved_recipes_that_extract_no_dishes_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_recipes="not actually a recipe writeup")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(na, "_extract_dishes", return_value=[]), \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()


class RespondForWholeMenuTests(unittest.TestCase):
    def test_asks_for_one_serving_nutrition_for_every_dish(self):
        agent = NutritionAgent()
        with patch.object(na, "_fetch_all_nutrients", return_value={"Lentil Soup": None}), \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("Lentil Soup: 100g lentils.", ["Lentil Soup"])

        self.assertEqual(chat_sync.call_args[0][0], na._WHOLE_MENU_SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("one-serving nutritional assessment for EVERY dish", user_message)

    def test_final_instruction_asks_for_a_concluding_cross_menu_note(self):
        agent = NutritionAgent()
        with patch.object(na, "_fetch_all_nutrients", return_value={"Lentil Soup": None}), \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("Lentil Soup: 100g lentils.", ["Lentil Soup"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("concluding note on any nutrition problems across the whole menu", user_message)

    def test_per_dish_word_budget_is_computed_and_injected(self):
        agent = NutritionAgent()
        agent._current_max_words = 300
        with patch.object(na, "_fetch_all_nutrients", return_value={"Chicken Curry": None, "Lentil Soup": None, "Beef Stew": None}), \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu(
                "Chicken Curry: 150g. Lentil Soup: 100g. Beef Stew: 200g.",
                ["Chicken Curry", "Lentil Soup", "Beef Stew"],
            )

        user_message = chat_sync.call_args[0][1]
        self.assertIn("This menu has 3 dishes", user_message)
        self.assertIn("90 words", user_message)  # (300 - 30 reserved for the conclusion) // 3
        self.assertIn("last 30 words for the closing", user_message)

    def test_per_dish_word_budget_never_drops_below_the_floor(self):
        agent = NutritionAgent()
        agent._current_max_words = 20
        dishes = [f"Dish {i}" for i in range(7)]
        with patch.object(na, "_fetch_all_nutrients", return_value={d: None for d in dishes}), \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("a recipe writeup", dishes)

        user_message = chat_sync.call_args[0][1]
        self.assertIn("20 words", user_message)  # max(20, 20 // 7) == 20

    def test_dishes_with_no_nutrient_data_are_named_not_silently_dropped(self):
        agent = NutritionAgent()
        with patch.object(na, "_fetch_all_nutrients", return_value={"Lentil Soup": None, "Chicken Curry": '{"calories": 350}'}), \
             patch.object(na.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_whole_menu("Lentil Soup: 100g. Chicken Curry: 150g.", ["Lentil Soup", "Chicken Curry"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Dishes with no USDA nutrient data found: Lentil Soup", user_message)
        self.assertIn("Chicken Curry", user_message)

    def test_multi_dish_response_becomes_an_html_list_with_the_conclusion_kept_separate(self):
        # The closing cross-menu note (see _WHOLE_MENU_SYSTEM_PROMPT's "end
        # with a short concluding note, on its own final line" instruction)
        # is a synthesis of everything above it, not one more per-dish
        # item -- it must NOT be swept into the same <ul> as the dishes.
        agent = NutritionAgent()
        raw_reply = "Chicken curry: 350 calories.\nLentil soup: 210 calories.\nNo notable nutrition problems."
        with patch.object(na, "_fetch_all_nutrients", return_value={"Chicken Curry": None, "Lentil Soup": None}), \
             patch.object(na.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent._respond_for_whole_menu("Chicken Curry: 150g. Lentil Soup: 100g.", ["Chicken Curry", "Lentil Soup"])

        self.assertEqual(result["text"], raw_reply)
        self.assertEqual(
            result["html"],
            "<ul><li>Chicken curry: 350 calories.</li><li>Lentil soup: 210 calories.</li></ul>"
            '<p style="margin-top:8px">No notable nutrition problems.</p>',
        )


class BuildWholeMenuHtmlTests(unittest.TestCase):
    def test_last_line_becomes_a_paragraph_not_a_list_item(self):
        html = na._build_whole_menu_html("Chicken curry: 350 cal.\nLentil soup: 210 cal.\nNo notable problems.")

        self.assertEqual(
            html,
            "<ul><li>Chicken curry: 350 cal.</li><li>Lentil soup: 210 cal.</li></ul>"
            '<p style="margin-top:8px">No notable problems.</p>',
        )

    def test_exactly_two_lines_still_splits_dish_from_conclusion(self):
        html = na._build_whole_menu_html("Chicken curry: 350 cal.\nNo notable problems.")

        self.assertEqual(
            html,
            "<ul><li>Chicken curry: 350 cal.</li></ul>"
            '<p style="margin-top:8px">No notable problems.</p>',
        )

    def test_single_line_produces_no_html(self):
        self.assertEqual(na._build_whole_menu_html("Just one line."), "")

    def test_empty_text_produces_no_html(self):
        self.assertEqual(na._build_whole_menu_html(""), "")

    def test_html_special_characters_are_escaped(self):
        html = na._build_whole_menu_html("Mac & cheese: 400 cal.\nToo much <sodium> overall.")

        self.assertIn("Mac &amp; cheese: 400 cal.", html)
        self.assertIn("Too much &lt;sodium&gt; overall.", html)

    def test_markdown_is_stripped_from_both_list_and_conclusion(self):
        html = na._build_whole_menu_html("1. **Chicken curry**: 350 cal.\n**No notable problems.**")

        self.assertNotIn("**", html)
        self.assertIn("<li>Chicken curry: 350 cal.</li>", html)
        self.assertIn("<p", html)
        self.assertIn("No notable problems.</p>", html)


class NeedsUnavailableDataTests(unittest.TestCase):
    """Questions about what diners actually ate/chose or historical menu
    records are declined without an LLM call -- the system has no such
    data and qwen2.5:7b otherwise invents a 'typical' range."""

    def test_consumption_history_questions_are_flagged(self):
        for q in [
            "What's the average sodium of the lunches our diners actually chose last month?",
            "How does this compare to what people usually eat here?",
            "What did we serve last week and how much sodium was in it?",
        ]:
            self.assertTrue(na._needs_unavailable_data(q), q)

    def test_ordinary_nutrition_questions_are_not_flagged(self):
        for q in [
            "How many calories are in a serving of grilled chicken breast?",
            "Give me the macros for salmon with quinoa.",
            "Is this menu high in sodium?",
        ]:
            self.assertFalse(na._needs_unavailable_data(q), q)

    def test_a_flagged_question_is_declined_without_an_llm_call(self):
        agent = NutritionAgent()
        agent._current_conv_id = "conv-1"
        with patch.object(na.llm_utils, "chat_sync") as chat_sync:
            result = agent.process_utterance("What did our diners actually eat last month, on average, for sodium?")

        chat_sync.assert_not_called()
        self.assertIn("don't have data on what diners actually ate", result["text"])
        self.assertEqual(result["html"], "")


if __name__ == "__main__":
    unittest.main()
