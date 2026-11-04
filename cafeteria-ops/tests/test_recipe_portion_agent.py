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
    _llm_candidate_terms,
    _multi_idea_request,
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

    def test_standard_cafeteria_portion_question_extracts_the_dish_name(self):
        # Confirmed live: this named no recipe-request phrase at all (no
        # "recipe for"), so nothing stripped and the 9-word question blew
        # past the 8-word cap -- returned None even though it plainly names
        # a dish. With a menu already saved from an earlier round in the
        # same conversation, that silently produced a whole-menu recipe
        # dump instead of answering about grilled chicken breast.
        text = "Recipe & Portion Specialist, what's a standard cafeteria portion for grilled chicken breast?"
        self.assertEqual(_dish_query(text), "grilled chicken breast")

    def test_portion_size_question_extracts_the_dish_name(self):
        text = "What portion size should we use for the roasted potatoes?"
        self.assertEqual(_dish_query(text), "the roasted potatoes")


class MultiIdeaRequestTests(unittest.TestCase):
    def test_three_different_ideas_extracts_count_and_dish(self):
        # Confirmed live: without this, "three different ideas for" was
        # never recognized as framing, so the whole sentence (quantity
        # word included) fell through as one garbled TheMealDB search
        # term that matched nothing -- with no real data to vary between,
        # the model just wrote one recipe and repeated it three times.
        text = "Recipe & Portion Specialist, give me three different ideas for inexpensive chicken curry recipes"
        self.assertEqual(_multi_idea_request(text), (3, "chicken curry"))

    def test_digit_count_and_recipe_ideas_wording(self):
        self.assertEqual(_multi_idea_request("give me 2 recipe ideas for salmon"), (2, "salmon"))

    def test_word_count_several_defaults_to_three(self):
        self.assertEqual(_multi_idea_request("several options for lentil soup"), (3, "lentil soup"))

    def test_count_is_capped_at_five(self):
        count, _ = _multi_idea_request("give me 20 different ideas for tofu stir-fry")
        self.assertEqual(count, 5)

    def test_plain_single_recipe_request_is_not_a_multi_idea_request(self):
        self.assertIsNone(_multi_idea_request("give me a recipe for chicken curry"))

    def test_empty_text_has_no_multi_idea_request(self):
        self.assertIsNone(_multi_idea_request(""))


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


class TermsFromSlotsTests(unittest.TestCase):
    """Deterministic priority order built from one dish's extracted slots
    -- this is what replaced asking the LLM to also rank a flat term
    list, which confirmed live was unreliable run to run even on the
    full model tier."""

    def test_dish_type_plus_main_ingredient_ranks_first(self):
        slots = {"main_ingredient": "chicken", "dish_type": "biryani"}
        self.assertEqual(rpa._terms_from_slots(slots)[0], "biryani chicken")

    def test_dish_type_alone_is_not_a_candidate(self):
        # Confirmed live: a bare dish-type word ("tacos", "pizza") matched
        # an unrelated dish sharing only that category ("tacos" -> the
        # unrelated "Breadfruit Tacos"; "pizza" -> the unrelated "Cassava
        # pizza") -- same risk as a bare main_ingredient or cuisine word,
        # so it's excluded the same way.
        slots = {"dish_type": "tacos"}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_secondary_ingredient_ranks_above_main_plus_sauce(self):
        # Confirmed live: "chorizo" alone matched a real, closely related
        # dish while combined phrases matched nothing at all.
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "chorizo", "sauce_or_style": "spicy"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("chorizo"), terms.index("chicken spicy"))

    def test_sauce_or_style_alone_is_not_a_candidate(self):
        # Confirmed live: a bare sauce/style word ("barbecue") matched an
        # unrelated dish sharing only that word ("barbecue" -> the
        # unrelated "Barbecue pork buns", even fed downstream for a dish
        # explicitly labeled Vegetarian) -- same risk as a bare
        # main_ingredient, cuisine, or dish_type word.
        slots = {"sauce_or_style": "barbecue"}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_cuisine_ranks_below_the_dish_own_identity(self):
        # Confirmed live: a bare cuisine word ("Moroccan") matched an
        # unrelated dish from that same cuisine ("Moroccan Carrot Soup")
        # -- it must never outrank the dish's own main ingredient. Bare
        # cuisine alone is no longer a candidate at all (see
        # test_cuisine_alone_is_not_a_candidate); cuisine+main is the
        # weakest tier that's still allowed, since it requires both
        # pieces of information to align in one title.
        slots = {"main_ingredient": "lamb", "dish_type": "stew", "cuisine": "Moroccan"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("stew lamb"), terms.index("Moroccan lamb"))

    def test_cuisine_alone_is_not_a_candidate(self):
        # Confirmed live: a bare cuisine word alone matched an unrelated
        # dish from that same cuisine ("Moroccan" -> "Moroccan Carrot
        # Soup") -- a wrong "real" recipe presented as grounded data is
        # worse than admitting no match was found, so this (and bare
        # main_ingredient alone) are deliberately never generated.
        slots = {"cuisine": "Moroccan"}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_main_ingredient_alone_is_not_a_candidate(self):
        slots = {"main_ingredient": "chicken"}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_generic_category_secondary_ingredient_is_dropped(self):
        # Confirmed live: "Grilled salmon with ... vegetables ..." extracted
        # secondary_ingredient="vegetables" (plural) -- the prompt's own
        # wording only named the singular "vegetable", so the model dodged
        # it just by pluralizing. Enforced in code instead of wording.
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "vegetables", "dish_type": "biryani"}
        terms = rpa._terms_from_slots(slots)
        self.assertNotIn("vegetables", terms)

    def test_generic_category_secondary_ingredient_singular_is_also_dropped(self):
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "meat"}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_specific_secondary_ingredient_is_not_dropped(self):
        slots = {"main_ingredient": "chicken", "secondary_ingredient": "berries"}
        self.assertIn("berries", rpa._terms_from_slots(slots))

    def test_cooking_method_plus_main_ranks_below_sauce(self):
        # Confirmed live: "roasted chicken"/"fried chicken" occasionally
        # land an exact-ish match, but it's a weaker signal than a named
        # sauce/style -- most cooking-method + main searches come back
        # empty, so it must never outrank main_ingredient + sauce_or_style.
        slots = {"main_ingredient": "chicken", "sauce_or_style": "teriyaki", "cooking_method": "grilled"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("chicken teriyaki"), terms.index("grilled chicken"))

    def test_cut_ranks_above_cooking_method(self):
        # Confirmed live: "lamb chop"/"pork chop"/"chicken wing" reliably
        # found real, distinctively relevant matches, and "chop"/"wing"/
        # "shank" alone did too (a cut name is rarely shared with an
        # unrelated dish the way "chicken" is) -- more reliable than
        # cooking-method combos, so it's ranked higher.
        slots = {"main_ingredient": "lamb", "cooking_method": "grilled", "cut": "chop"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("lamb chop"), terms.index("chop"))
        self.assertLess(terms.index("chop"), terms.index("grilled lamb"))

    def test_steak_fallback_is_tried_only_after_the_cut_itself(self):
        # Confirmed live: "sirloin" alone has zero TheMealDB coverage, but
        # "steak" does ("Steak Diane" etc.) -- "steak" must come AFTER the
        # cut's own name, never before, so a cut that DOES have real
        # coverage (e.g. "chop") still gets first crack at it.
        slots = {"main_ingredient": "beef", "cut": "sirloin"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("beef sirloin"), terms.index("beef steak"))
        self.assertLess(terms.index("sirloin"), terms.index("steak"))
        self.assertLess(terms.index("beef steak"), terms.index("steak"))

    def test_steak_fallback_is_absent_for_a_non_steak_cut(self):
        # "chop" is a real cut but not a steak cut -- no "steak" terms
        # should be generated at all.
        slots = {"main_ingredient": "lamb", "cut": "chop"}
        terms = rpa._terms_from_slots(slots)
        self.assertNotIn("steak", terms)
        self.assertNotIn("lamb steak", terms)

    def test_steak_fallback_ranks_below_sauce_and_cut(self):
        slots = {"main_ingredient": "beef", "sauce_or_style": "peppercorn", "cut": "ribeye"}
        terms = rpa._terms_from_slots(slots)
        self.assertLess(terms.index("beef peppercorn"), terms.index("steak"))
        self.assertLess(terms.index("ribeye"), terms.index("steak"))

    def test_empty_slots_return_no_terms(self):
        self.assertEqual(rpa._terms_from_slots({}), [])

    def test_non_string_slot_values_are_treated_as_absent(self):
        slots = {"main_ingredient": None, "dish_type": 5, "secondary_ingredient": "  "}
        self.assertEqual(rpa._terms_from_slots(slots), [])

    def test_duplicate_terms_are_not_repeated(self):
        # dish_type alone and cut alone can coincide (e.g. an unusual
        # extraction where both land on "chop") -- only one entry should
        # survive, keeping the first (higher-priority) occurrence.
        slots = {"main_ingredient": "lamb", "dish_type": "chop", "cut": "chop"}
        terms = rpa._terms_from_slots(slots)
        self.assertEqual(terms.count("chop"), 1)


class LlmCandidateTermsTests(unittest.TestCase):
    """The exact dish name is always prepended as the first, free
    attempt, followed by the deterministic term order built from that
    dish's LLM-extracted slots (see TermsFromSlotsTests)."""

    def test_dish_name_is_prepended_before_the_slot_derived_terms(self):
        raw = json.dumps({"Grilled Teriyaki Chicken": {"main_ingredient": "chicken", "sauce_or_style": "teriyaki"}})
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            result = _llm_candidate_terms(["Grilled Teriyaki Chicken"])

        # No trailing bare "chicken" or bare "teriyaki" -- main_ingredient
        # alone and sauce_or_style alone are deliberately not candidates
        # (see TermsFromSlotsTests).
        self.assertEqual(
            result["Grilled Teriyaki Chicken"],
            ["Grilled Teriyaki Chicken", "chicken teriyaki"],
        )

    def test_dish_missing_from_the_llm_response_falls_back_to_itself_alone(self):
        raw = json.dumps({"Chicken Curry": {"main_ingredient": "chicken"}})  # "Lentil Soup" omitted
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            result = _llm_candidate_terms(["Chicken Curry", "Lentil Soup"])

        self.assertEqual(result["Lentil Soup"], ["Lentil Soup"])

    def test_malformed_json_response_falls_back_to_the_dish_name_alone(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="not json at all"):
            result = _llm_candidate_terms(["Chicken Curry"])

        self.assertEqual(result["Chicken Curry"], ["Chicken Curry"])

    def test_non_dict_slots_for_a_dish_fall_back_to_the_dish_name_alone(self):
        raw = json.dumps({"Chicken Curry": ["not", "a", "dict"]})
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            result = _llm_candidate_terms(["Chicken Curry"])

        self.assertEqual(result["Chicken Curry"], ["Chicken Curry"])

    def test_empty_dish_list_makes_no_llm_call(self):
        with patch.object(rpa.llm_utils, "chat_sync") as chat_sync:
            result = _llm_candidate_terms([])

        chat_sync.assert_not_called()
        self.assertEqual(result, {})

    def test_multiple_dishes_are_extracted_in_one_call(self):
        raw = json.dumps({
            "Chicken and Chorizo Quesadillas": {
                "main_ingredient": "chicken", "secondary_ingredient": "chorizo", "dish_type": "quesadillas",
            },
            "Grilled Salmon": {"main_ingredient": "salmon"},
        })
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = _llm_candidate_terms(["Chicken and Chorizo Quesadillas", "Grilled Salmon"])

        chat_sync.assert_called_once()
        self.assertEqual(
            result["Chicken and Chorizo Quesadillas"],
            ["Chicken and Chorizo Quesadillas", "quesadillas chicken", "chorizo"],
        )
        # "Grilled Salmon" has only a bare main_ingredient and nothing
        # else distinguishing -- no fallback candidates beyond its own
        # exact name (see TermsFromSlotsTests.test_main_ingredient_alone_is_not_a_candidate).
        self.assertEqual(result["Grilled Salmon"], ["Grilled Salmon"])


class FetchAllRecipesTests(unittest.TestCase):
    """Batched round-based lookup (one parallel search round per candidate-
    term rank, then one parallel detail round) across every dish in a
    whole week's menu -- same two-stage shape as _fetch_recipe_details.
    _llm_candidate_terms itself is mocked throughout (its own behavior is
    covered by LlmCandidateTermsTests) so these tests isolate the round-
    advancing/dedup mechanics from the term-ranking logic."""

    def test_empty_dish_list_makes_no_calls(self):
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync") as call:
            result = _fetch_all_recipes([])

        call.assert_not_called()
        self.assertEqual(result, {})

    def test_every_dish_found_maps_to_its_real_detail(self):
        terms = {"Chicken Curry": ["Chicken Curry"], "Lentil Soup": ["Lentil Soup"]}
        search_results = [
            json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]}),
            json.dumps({"query": "Lentil Soup", "results": [{"id": "77", "name": "Lentil Soup"}]}),
        ]
        detail_results = [
            json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]}),
            json.dumps({"id": "77", "name": "Lentil Soup", "ingredients": ["100g lentils"]}),
        ]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_recipes(["Chicken Curry", "Lentil Soup"])

        self.assertEqual(call.call_count, 2)
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Lentil Soup": detail_results[1]})

    def test_dish_with_no_search_match_maps_to_none_without_a_detail_call(self):
        # "Chicken Curry" hits its first candidate term; "Mystery Dish"
        # misses its first and its only fallback term. Only the one real
        # match should ever reach the detail round.
        terms = {"Chicken Curry": ["Chicken Curry"], "Mystery Dish": ["Mystery Dish", "mystery"]}
        round1 = [
            json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]}),
            json.dumps({"query": "Mystery Dish", "results": []}),
        ]
        round2_retry = [json.dumps({"query": "mystery", "results": []})]
        detail_results = [
            json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]}),
        ]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2_retry, detail_results]) as call:
            result = _fetch_all_recipes(["Chicken Curry", "Mystery Dish"])

        detail_requests = call.call_args_list[-1].args[0]
        self.assertEqual(detail_requests, [("themealdb", "get_recipe_details", {"meal_id": "52"})])
        self.assertEqual(result, {"Chicken Curry": detail_results[0], "Mystery Dish": None})

    def test_full_name_miss_is_retried_down_the_candidate_term_list(self):
        # The dish's full name finds nothing, nor do its first three
        # LLM-ranked fallback terms -- but the fourth does, and that
        # match's detail is what the dish maps to.
        dish = "Grilled salmon with a lemon-pepper crust"
        terms = {dish: [dish, "salmon lemon pepper", "pepper", "lemon", "salmon"]}
        round1 = [json.dumps({"query": dish, "results": []})]
        round2 = [json.dumps({"query": "salmon lemon pepper", "results": []})]
        round3 = [json.dumps({"query": "pepper", "results": []})]
        round4 = [json.dumps({"query": "lemon", "results": []})]
        round5 = [json.dumps({"query": "salmon", "results": [{"id": "99", "name": "Salmon Dinner"}]})]
        detail_results = [json.dumps({"id": "99", "name": "Salmon Dinner", "ingredients": ["150g salmon"]})]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3, round4, round5, detail_results]) as call:
            result = _fetch_all_recipes([dish])

        terms_tried = [c.args[0][0][2]["name"] for c in call.call_args_list[:5]]
        self.assertEqual(terms_tried, [dish, "salmon lemon pepper", "pepper", "lemon", "salmon"])
        self.assertEqual(result, {dish: detail_results[0]})

    def test_no_dish_found_even_after_retry_skips_the_detail_round_entirely(self):
        terms = {"Mystery Dish": ["Mystery Dish", "mystery"]}
        empty = [json.dumps({"query": "Mystery Dish", "results": []})]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=empty) as call:
            result = _fetch_all_recipes(["Mystery Dish"])

        self.assertEqual(call.call_count, 2)  # full-name round + one fallback term, no detail round
        self.assertEqual(result, {"Mystery Dish": None})

    def test_detail_lookup_with_no_ingredients_maps_to_none(self):
        terms = {"Chicken Curry": ["Chicken Curry"]}
        search_results = [json.dumps({"query": "Chicken Curry", "results": [{"id": "52", "name": "Chicken Curry"}]})]
        detail_results = [json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": []})]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]):
            result = _fetch_all_recipes(["Chicken Curry"])

        self.assertEqual(result, {"Chicken Curry": None})

    def test_two_dishes_that_resolve_to_the_same_recipe_do_not_both_carry_it(self):
        # Both dishes' candidate terms eventually reduce to the bare
        # "chicken" and land on the same meal id. Only the first (menu
        # order) keeps the recipe; the second is left None so the model
        # doesn't print the identical block twice.
        terms = {
            "Grilled chicken breast": ["Grilled chicken breast", "chicken"],
            "Chicken tikka masala": ["Chicken tikka masala", "chicken tikka masala", "chicken"],
        }
        round1 = [
            json.dumps({"query": "Grilled chicken breast", "results": []}),
            json.dumps({"query": "Chicken tikka masala", "results": []}),
        ]
        round2 = [
            json.dumps({"query": "chicken", "results": [{"id": "52", "name": "Chicken"}]}),
            json.dumps({"query": "chicken tikka masala", "results": []}),
        ]
        round3 = [
            json.dumps({"query": "chicken", "results": [{"id": "52", "name": "Chicken"}]}),
        ]
        detail = [json.dumps({"id": "52", "name": "Chicken", "ingredients": ["200g chicken"]})]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3, detail]) as call:
            result = _fetch_all_recipes(["Grilled chicken breast", "Chicken tikka masala"])

        # exactly one detail lookup, for the single shared meal id
        self.assertEqual(call.call_args_list[-1].args[0], [("themealdb", "get_recipe_details", {"meal_id": "52"})])
        self.assertEqual(result, {"Grilled chicken breast": detail[0], "Chicken tikka masala": None})

    def test_a_dish_that_loses_the_dedupe_retries_with_its_own_next_candidate(self):
        # "Dish A" and "Dish B" both reduce to a shared "shared" term and
        # collide on the same meal id -- but "Dish B" still has a further,
        # more specific candidate ("unique") of its own. Confirmed live
        # this exact scenario (two different steak cuts both falling back
        # to a shared "steak" term) previously meant the SECOND dish was
        # silently lost even though it had a real, different match of its
        # own left to try -- both dishes must now end up with real,
        # DIFFERENT recipes instead of the second one going to None.
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
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3_retry, detail]) as call:
            result = _fetch_all_recipes(["Dish A", "Dish B"])

        detail_requests = call.call_args_list[-1].args[0]
        self.assertEqual(
            detail_requests,
            [("themealdb", "get_recipe_details", {"meal_id": "99"}),
             ("themealdb", "get_recipe_details", {"meal_id": "100"})],
        )
        self.assertEqual(result, {"Dish A": detail[0], "Dish B": detail[1]})

    def test_a_middle_ingredient_word_is_tried_when_the_full_phrase_matches_nothing(self):
        # Confirmed live: TheMealDB's small catalog has no title matching
        # the combined "chicken chorizo quesadillas" phrase, nor "chicken"
        # alone landing on anything relevant -- but "chorizo" alone
        # matches a real, closely related dish.
        dish = "Chicken and Chorizo Quesadillas"
        terms = {dish: [dish, "chicken chorizo quesadillas", "quesadillas", "chorizo", "chicken"]}
        round1 = [json.dumps({"query": dish, "results": []})]
        round2 = [json.dumps({"query": "chicken chorizo quesadillas", "results": []})]
        round3 = [json.dumps({"query": "quesadillas", "results": []})]
        round4 = [json.dumps({"query": "chorizo", "results": [{"id": "77", "name": "Chicken & chorizo rice pot"}]})]
        detail = [json.dumps({"id": "77", "name": "Chicken & chorizo rice pot", "ingredients": ["200g chorizo"]})]
        with patch.object(rpa, "_llm_candidate_terms", return_value=terms), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[round1, round2, round3, round4, detail]) as call:
            result = _fetch_all_recipes([dish])

        terms_tried = [c.args[0][0][2]["name"] for c in call.call_args_list[:4]]
        self.assertEqual(terms_tried, [dish, "chicken chorizo quesadillas", "quesadillas", "chorizo"])
        self.assertEqual(result, {dish: detail[0]})


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

    def test_multi_idea_request_takes_priority_over_the_single_dish_path(self):
        # Confirmed live: before _multi_idea_request existed, this fell
        # into the single-dish path with the whole garbled sentence as the
        # search query, which matched nothing on TheMealDB.
        agent = self._make_agent()
        text = "Recipe & Portion Specialist, give me three different ideas for inexpensive chicken curry recipes"
        with patch.object(agent, "_respond_with_multiple_ideas", return_value="multi-idea reply") as multi, \
             patch.object(agent, "_respond_for_one_dish") as one_dish:
            result = agent.process_utterance(text)

        multi.assert_called_once_with(text, "chicken curry", 3)
        one_dish.assert_not_called()
        self.assertEqual(result, "multi-idea reply")

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


class RespondWithMultipleIdeasTests(unittest.TestCase):
    """Ground each requested idea in a DIFFERENT real TheMealDB recipe
    where possible, instead of asking the LLM to invent several
    "distinct" versions of the one recipe it would otherwise settle on."""

    def test_grounds_each_idea_in_a_different_real_recipe(self):
        search_result = json.dumps({"query": "chicken curry", "results": [
            {"id": "52", "name": "Chicken Curry"},
            {"id": "53", "name": "Chicken Karahi"},
            {"id": "54", "name": "Chicken Tikka Masala"},
        ]})
        detail_results = [
            json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]}),
            json.dumps({"id": "53", "name": "Chicken Karahi", "ingredients": ["200g chicken thigh"]}),
            json.dumps({"id": "54", "name": "Chicken Tikka Masala", "ingredients": ["200g chicken breast", "yogurt"]}),
        ]
        agent = RecipePortionAgent()
        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=search_result), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=detail_results), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            result = agent._respond_with_multiple_ideas(
                "give me three different ideas for chicken curry", "chicken curry", 3)

        self.assertEqual(chat_sync.call_args[0][0], rpa._MULTI_IDEA_SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("3 real distinct recipe option(s) were found", user_message)
        self.assertIn("Chicken Karahi", user_message)
        self.assertIn("Chicken Tikka Masala", user_message)
        self.assertIn("3 genuinely DIFFERENT recipe ideas", user_message)
        self.assertEqual(result["text"], "ok")

    def test_fewer_real_options_than_requested_notes_the_shortfall(self):
        search_result = json.dumps({"query": "chicken curry", "results": [{"id": "52", "name": "Chicken Curry"}]})
        detail_results = [json.dumps({"id": "52", "name": "Chicken Curry", "ingredients": ["200g chicken breast"]})]
        agent = RecipePortionAgent()
        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=search_result), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=detail_results), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_with_multiple_ideas("give me three ideas for chicken curry", "chicken curry", 3)

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Only 1 real option(s) were found, fewer than the 3 requested", user_message)

    def test_no_real_options_found_falls_back_to_general_knowledge(self):
        agent = RecipePortionAgent()
        with patch.object(rpa.mcp_client, "call_tool_sync_or_none", return_value=None), \
             patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=[]), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_with_multiple_ideas("give me three ideas for zzz-nonexistent-dish", "zzz-nonexistent-dish", 3)

        user_message = chat_sync.call_args[0][1]
        self.assertIn("No distinct real recipe options were found", user_message)
        self.assertIn("Provide all ideas from general culinary knowledge", user_message)


class RespondForWholeMenuTests(unittest.TestCase):
    def test_asks_for_one_serving_not_a_headcount(self):
        agent = RecipePortionAgent()
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Lentil Soup": None}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value="Lentil Soup: 100g lentils.") as chat_sync:
            agent._respond_for_whole_menu("Day 1: Lentil Soup.", ["Lentil Soup"])

        # The dish got its own line, so no missing-dish repair call fired --
        # this asserts against the one and only call.
        chat_sync.assert_called_once()
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
        covering_reply = "Chicken Curry: a.\nLentil Soup: b.\nBeef Stew: c."
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Chicken Curry": None, "Lentil Soup": None, "Beef Stew": None}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=covering_reply) as chat_sync:
            agent._respond_for_whole_menu(
                "Day 1: Chicken Curry. Day 2: Lentil Soup. Day 3: Beef Stew.",
                ["Chicken Curry", "Lentil Soup", "Beef Stew"],
            )

        # Every dish got its own line, so no missing-dish repair call fired.
        chat_sync.assert_called_once()
        user_message = chat_sync.call_args[0][1]
        self.assertIn("This menu has 3 dishes", user_message)
        self.assertIn("100 words", user_message)  # 300 // 3

    def test_per_dish_word_budget_never_drops_below_the_floor(self):
        agent = RecipePortionAgent()
        agent._current_max_words = 20
        dishes = [f"Dish {i}" for i in range(7)]
        covering_reply = "\n".join(f"{d}: x." for d in dishes)
        with patch.object(rpa, "_fetch_all_recipes", return_value={d: None for d in dishes}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=covering_reply) as chat_sync:
            agent._respond_for_whole_menu("a menu", dishes)

        # Every dish got its own line, so no missing-dish repair call fired.
        chat_sync.assert_called_once()
        user_message = chat_sync.call_args[0][1]
        self.assertIn("20 words", user_message)  # max(20, 20 // 7) == 20

    def test_dishes_with_no_recipe_data_are_named_not_silently_dropped(self):
        agent = RecipePortionAgent()
        covering_reply = "Lentil Soup: no data, best guess.\nChicken Curry: 200g chicken."
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Lentil Soup": None, "Chicken Curry": '{"ingredients": ["200g chicken"]}'}), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=covering_reply) as chat_sync:
            agent._respond_for_whole_menu("Day 1: Lentil Soup. Day 2: Chicken Curry.", ["Lentil Soup", "Chicken Curry"])

        # Both dishes got their own line, so no missing-dish repair call fired.
        chat_sync.assert_called_once()
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

    def test_a_dish_merged_onto_another_dishs_line_is_repaired_with_its_own_line(self):
        # Same live failure this whole mechanism exists for: "Pan-seared
        # duck: No recipe data found: Caprese panini: 18 kg mozzarella..."
        # all one line, so the Caprese panini popup would show nothing (or
        # duck's) instead of its own data.
        agent = RecipePortionAgent()
        merged_reply = "Pan-seared duck: No recipe data found: Caprese panini: 40g mozzarella: grill: 200g"
        repair_reply = "Caprese panini: 40g mozzarella, 20g tomato: grill: 200g"
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Pan-seared duck": None, "Caprese panini": None}), \
             patch.object(rpa.llm_utils, "chat_sync", side_effect=[merged_reply, repair_reply]) as chat_sync:
            result = agent._respond_for_whole_menu(
                "Day 1: Pan-seared duck. Day 2: Caprese panini.", ["Pan-seared duck", "Caprese panini"],
            )

        self.assertEqual(chat_sync.call_count, 2)
        lines = result["text"].split("\n")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("Caprese panini:"))
        self.assertIn("40g mozzarella, 20g tomato", lines[1])

    def test_a_silently_dropped_dish_is_repaired_with_its_own_line(self):
        agent = RecipePortionAgent()
        dropped_reply = "Chicken curry: 150g chicken: fry: 200g"  # Lentil soup never appears
        repair_reply = "Lentil soup: 100g lentils: simmer: 250g bowl"
        with patch.object(rpa, "_fetch_all_recipes", return_value={"Chicken curry": None, "Lentil soup": None}), \
             patch.object(rpa.llm_utils, "chat_sync", side_effect=[dropped_reply, repair_reply]) as chat_sync:
            result = agent._respond_for_whole_menu(
                "Day 1: Chicken curry. Day 2: Lentil soup.", ["Chicken curry", "Lentil soup"],
            )

        self.assertEqual(chat_sync.call_count, 2)
        self.assertIn("Lentil soup: 100g lentils: simmer: 250g bowl", result["text"])


class RespondForOneDishHtmlTests(unittest.TestCase):
    def test_single_dish_response_has_no_html_list(self):
        agent = RecipePortionAgent()
        raw_reply = "Use 150g chicken breast, 30g romaine lettuce, and 1 tbsp Caesar dressing."
        with patch.object(rpa.mcp_client, "call_tools_parallel_sync", return_value=[None, None]), \
             patch.object(rpa.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent._respond_for_one_dish("give me a recipe for chicken curry", "chicken curry")

        self.assertEqual(result["text"], raw_reply)
        self.assertEqual(result["html"], "")


class NeedsUnavailableDataTests(unittest.TestCase):
    """Questions about what recipe was used before / how a dish was made
    here previously are declined without an LLM call -- the system keeps
    no such history and qwen2.5:7b otherwise just answers with a standard
    recipe and never says it can't know."""

    def test_recipe_history_questions_are_flagged(self):
        for q in [
            "What recipe did we use for the chicken curry the last time we made it?",
            "How did we make the beef stew before?",
            "Give me our recipe for lentil soup.",
        ]:
            self.assertTrue(rpa._needs_unavailable_data(q), q)

    def test_plain_recipe_requests_are_not_flagged(self):
        for q in [
            "Give me a recipe for chicken curry.",
            "What's a one-serving portion of grilled salmon?",
            "How much rice per serving for jambalaya?",
        ]:
            self.assertFalse(rpa._needs_unavailable_data(q), q)

    def test_a_flagged_question_is_declined_without_an_llm_call(self):
        agent = RecipePortionAgent()
        agent._current_conv_id = "conv-1"
        with patch.object(rpa.llm_utils, "chat_sync") as chat_sync:
            result = agent.process_utterance("What recipe did we use the last time we made chicken curry?")

        chat_sync.assert_not_called()
        self.assertIn("don't have any record of recipes previously used", result["text"])
        self.assertEqual(result["html"], "")


class ScaleRecipeTextTests(unittest.TestCase):
    def test_masses_scale_and_roll_up_to_kg(self):
        out = rpa._scale_recipe_text("150 g chicken breast, 90 g farro", 450)
        self.assertEqual(out, "67.5 kg chicken breast, 40.5 kg farro")

    def test_times_temperatures_and_dimensions_pass_through(self):
        line = "sear 3-4 min per side, bake at 400 F for 12 min, cut into 1 inch cubes"
        self.assertEqual(rpa._scale_recipe_text(line, 450), line)

    def test_a_per_plate_figure_is_left_as_written(self):
        self.assertEqual(rpa._scale_recipe_text("... ; 220 g plate", 450), "... ; 220 g plate")

    def test_scaling_by_one_is_identity(self):
        self.assertEqual(rpa._scale_recipe_text("150 g rice", 1), "150 g rice")

    def test_apply_servings_prepends_the_board_marker(self):
        out = RecipePortionAgent._apply_servings("150 g rice", 450)
        self.assertTrue(out.lower().startswith("full service"))
        self.assertIn("67.5 kg rice", out)


class NormalizeMenuRecipeLinesTests(unittest.TestCase):
    """The browser board shows only the dish NAME per line, so each dish must
    end up on exactly one line "<name>: <rest>". The model sometimes wraps a
    dish name or its amounts across several lines."""

    def test_explicit_name_colon_lines_are_left_alone(self):
        text = "Grilled salmon: 150g salmon; sear; 220g plate.\nFalafel bowl: 120g falafel; fry; 300g bowl."
        self.assertEqual(rpa._normalize_menu_recipe_lines(text), text)

    def test_a_wrapped_dish_name_and_amounts_collapse_to_one_line(self):
        text = (
            "Grilled lamb chops with roasted eggplant\n"
            "lemon tahini sauce, and couscous pilaf.\n"
            "150g lamb, 100g eggplant; sear 3 min/side; 240g plate.\n"
            "Chickpea and spinach stew: 180g stew, 75g rice; simmer; 300g bowl."
        )
        lines = rpa._normalize_menu_recipe_lines(text).split("\n")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("Grilled lamb chops with roasted eggplant:"))
        self.assertIn("150g lamb", lines[0])
        self.assertTrue(lines[1].startswith("Chickpea and spinach stew:"))

    def test_field_labels_and_notes_do_not_become_dishes(self):
        text = (
            "Grilled salmon: 150g salmon; 220g plate.\n"
            "Prep: keep the skin on.\n"
            "Dishes with no recipe data found: Falafel bowl"
        )
        lines = rpa._normalize_menu_recipe_lines(text).split("\n")
        self.assertEqual(lines[0], "Grilled salmon: 150g salmon; 220g plate. Prep: keep the skin on.")
        self.assertEqual(lines[1], "Dishes with no recipe data found: Falafel bowl")

    def test_a_prep_sentence_is_not_mistaken_for_a_dish_name(self):
        text = "Chicken curry: 150g chicken; 250g plate.\nSeason and sear the chicken before simmering."
        lines = rpa._normalize_menu_recipe_lines(text).split("\n")
        self.assertEqual(len(lines), 1)
        self.assertIn("Season and sear", lines[0])


class MissingDishesTests(unittest.TestCase):
    """Confirmed live: under word-budget pressure the whole-menu writeup
    LLM call sometimes drops a dish's entry entirely, or runs a terse "No
    recipe data found:" stub for one dish onto the SAME line as the next
    dish instead of a new line -- reported live as "Pan-seared duck: No
    recipe data found: Caprese panini: 18 kg mozzarella..." all one line,
    so the "Pan-seared duck" popup showed Caprese panini's ingredients."""

    def test_a_dish_that_got_its_own_line_is_not_missing(self):
        text = "Chicken curry: 150g chicken.\nLentil soup: 100g lentils."
        self.assertEqual(rpa._missing_dishes(text, ["Chicken curry", "Lentil soup"]), [])

    def test_a_dropped_dish_is_reported_missing(self):
        text = "Chicken curry: 150g chicken."
        self.assertEqual(rpa._missing_dishes(text, ["Chicken curry", "Lentil soup"]), ["Lentil soup"])

    def test_a_dish_merged_onto_the_previous_dishs_line_is_reported_missing(self):
        # The exact live failure shape: the second dish never starts its
        # own line, so it never becomes a "covered" dish name even though
        # its name and data appear somewhere in the text.
        text = "Pan-seared duck: No recipe data found: Caprese panini: 40g mozzarella, 20g tomato: Grill: 200g"
        self.assertEqual(rpa._missing_dishes(text, ["Pan-seared duck", "Caprese panini"]), ["Caprese panini"])

    def test_matching_is_case_insensitive_and_tolerates_minor_rewording(self):
        text = "GRILLED SALMON with lemon: 150g salmon."
        self.assertEqual(rpa._missing_dishes(text, ["Grilled salmon"]), [])


class RepairMissingDishLineTests(unittest.TestCase):
    def test_a_clean_one_line_reply_is_used_as_is(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="Lentil soup: 100g lentils: simmer: 250g bowl"):
            line = rpa._repair_missing_dish_line("Lentil soup", None)
        self.assertEqual(line, "Lentil soup: 100g lentils: simmer: 250g bowl")

    def test_only_the_first_line_of_a_multi_line_reply_is_kept(self):
        # The repair call exists specifically because the main call
        # couldn't be trusted to stay on one line -- the repair itself
        # must not trust that either.
        raw = "Lentil soup: 100g lentils: simmer: 250g bowl\nSome extra unwanted line"
        with patch.object(rpa.llm_utils, "chat_sync", return_value=raw):
            line = rpa._repair_missing_dish_line("Lentil soup", None)
        self.assertEqual(line, "Lentil soup: 100g lentils: simmer: 250g bowl")

    def test_a_reply_missing_the_dish_name_prefix_gets_it_prepended(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="100g lentils: simmer: 250g bowl"):
            line = rpa._repair_missing_dish_line("Lentil soup", None)
        self.assertEqual(line, "Lentil soup: 100g lentils: simmer: 250g bowl")

    def test_a_blank_reply_falls_back_to_an_honest_no_data_line(self):
        with patch.object(rpa.llm_utils, "chat_sync", return_value="   \n  "):
            line = rpa._repair_missing_dish_line("Lentil soup", None)
        self.assertEqual(line, "Lentil soup: No recipe data found -- use general culinary knowledge for this dish.")


class VerbalRecipeViewTests(unittest.TestCase):
    """A person can ask this agent directly to see the recipes (scaled to the
    whole cafeteria) or ask for a single serving; the round-robin planning
    request stays one serving so Nutrition / Shopping List still work."""

    def _agent(self, saved_menu="Day 1: Chicken Curry. Day 2: Lentil Soup."):
        agent = RecipePortionAgent()
        agent._current_conv_id = "conv-1"
        agent._observed_menus["conv-1"] = saved_menu
        return agent

    def test_show_me_the_recipes_scales_to_the_headcount(self):
        agent = self._agent()
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
             patch.object(agent, "_respond_for_whole_menu", return_value="scaled") as whole_menu:
            agent.process_utterance("show me the recipes")

        _args, kwargs = whole_menu.call_args
        self.assertEqual(kwargs.get("servings"), rpa.DEFAULT_SERVINGS)

    def test_recipe_view_with_an_explicit_headcount_uses_it(self):
        agent = self._agent()
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
             patch.object(agent, "_respond_for_whole_menu", return_value="scaled") as whole_menu:
            agent.process_utterance("show me the recipes for 300 people")

        self.assertEqual(whole_menu.call_args.kwargs.get("servings"), 300)

    def test_single_serving_request_is_not_scaled(self):
        agent = self._agent()
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
             patch.object(agent, "_respond_for_whole_menu", return_value="one") as whole_menu:
            agent.process_utterance("show me the recipes for a single serving")

        whole_menu.assert_called_once_with("Day 1: Chicken Curry. Day 2: Lentil Soup.", ["Chicken Curry", "Lentil Soup"])

    def test_round_robin_planning_request_is_not_scaled(self):
        agent = self._agent()
        broad = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
             patch.object(agent, "_respond_for_whole_menu", return_value="one") as whole_menu:
            agent.process_utterance(broad)

        whole_menu.assert_called_once_with("Day 1: Chicken Curry. Day 2: Lentil Soup.", ["Chicken Curry", "Lentil Soup"])

    def test_the_recipes_is_not_searched_as_a_dish(self):
        agent = self._agent()
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry"]), \
             patch.object(agent, "_respond_for_one_dish") as one_dish, \
             patch.object(agent, "_respond_for_whole_menu", return_value="ok") as whole_menu:
            agent.process_utterance("show me the recipes")

        one_dish.assert_not_called()
        whole_menu.assert_called_once()

    def test_small_stated_headcount_scales_to_that_number(self):
        for phrasing, expected in [
            ("food for four people", 4),
            ("give me the recipes for 4 people", 4),
            ("recipe & portion, the recipes to feed six", 6),
            ("serves 12", 12),
        ]:
            agent = self._agent()
            with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
                 patch.object(agent, "_respond_for_whole_menu", return_value="scaled") as whole_menu:
                agent.process_utterance(phrasing)
            self.assertEqual(whole_menu.call_args.kwargs.get("servings"), expected, phrasing)

    def test_planning_request_with_a_headcount_still_stays_one_serving(self):
        agent = self._agent()
        broad = "Plan a Mediterranean 5-day lunch menu for 4 people."
        with patch.object(rpa, "_extract_dishes", return_value=["Chicken Curry", "Lentil Soup"]), \
             patch.object(agent, "_respond_for_whole_menu", return_value="one") as whole_menu:
            agent.process_utterance(broad)
        whole_menu.assert_called_once_with("Day 1: Chicken Curry. Day 2: Lentil Soup.", ["Chicken Curry", "Lentil Soup"])

    def test_a_day_or_dish_count_is_not_read_as_a_headcount(self):
        for text in ["give me the recipes for 5 days", "the recipes for 3 dishes"]:
            self.assertIsNone(rpa._explicit_servings(text), text)


class ExplicitServingsTests(unittest.TestCase):
    def test_digits_and_number_words(self):
        self.assertEqual(rpa._explicit_servings("for 4 people"), 4)
        self.assertEqual(rpa._explicit_servings("food for four people"), 4)
        self.assertEqual(rpa._explicit_servings("cook for six"), 6)
        self.assertEqual(rpa._explicit_servings("serves 12"), 12)
        self.assertEqual(rpa._explicit_servings("feeding 8"), 8)
        self.assertEqual(rpa._explicit_servings("for 450 people"), 450)

    def test_no_headcount_returns_none(self):
        for text in ["give me a recipe for chicken curry", "for 5 days", "for the whole team", ""]:
            self.assertIsNone(rpa._explicit_servings(text), text)


if __name__ == "__main__":
    unittest.main()
