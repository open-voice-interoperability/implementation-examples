import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.procurement_specialist import procurement_agent as pa
from agents.procurement_specialist.procurement_agent import (
    _commodity_query,
    _extract_ingredients,
    _fetch_all_market_data,
    _fetch_all_web_prices,
    _fetch_report_data,
    _fetch_web_price_context,
    _non_empty_results,
    _rows_matching_type,
    _search_terms_for,
    _single_commodity_budget_hint,
    _summarize_commodity_rows,
    _usable_web_search_result,
    ProcurementAgent,
)


class CommodityQueryTests(unittest.TestCase):
    def test_broad_multi_day_planning_request_has_no_commodity_query(self):
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal."
        )
        self.assertIsNone(_commodity_query(text))

    def test_broad_request_with_max_words_instruction_still_has_no_commodity_query(self):
        text = (
            "Plan a five-day lunch menu for 450 people in a corporate cafeteria "
            "with specific items and itemized costs, with a budget of $7.00 per meal.\n\n"
            "[Write approximately 400 words total. If this request covers multiple "
            "days, items, or parts, you MUST address EVERY one of them.]"
        )
        self.assertIsNone(_commodity_query(text))

    def test_direct_price_question_extracts_the_commodity(self):
        text = "Procurement Specialist, what's the market price for chicken?"
        self.assertEqual(_commodity_query(text), "chicken")

    def test_direct_price_question_with_max_words_instruction_still_extracts_commodity(self):
        text = (
            "Procurement Specialist, what's the market price for chicken?\n\n"
            "[Write approximately 125 words. If this request covers multiple days, "
            "items, or parts, you MUST address EVERY one of them.]"
        )
        self.assertEqual(_commodity_query(text), "chicken")

    def test_bare_commodity_name_is_used_as_is(self):
        self.assertEqual(_commodity_query("beef"), "beef")

    def test_trailing_time_filler_is_stripped(self):
        # Confirmed live: leaving "right now" attached made the derived
        # keyword "beef right now" match zero report titles even though
        # "beef" alone matches several real USDA AMS reports.
        self.assertEqual(_commodity_query("What's the market price for beef right now?"), "beef")

    def test_trailing_today_is_stripped(self):
        self.assertEqual(_commodity_query("What's the market price for chicken today?"), "chicken")

    def test_leading_quantity_with_of_is_stripped(self):
        # Confirmed live: leaving "100 kg of" attached made
        # _search_terms_for try "100" and "breast" (first/last word of
        # the whole uncleaned phrase) but never "chicken", the one word
        # that actually matches real USDA AMS report titles.
        self.assertEqual(_commodity_query("What's the price for 100 kg of chicken breast?"), "chicken breast")

    def test_leading_quantity_without_decimal_is_stripped(self):
        self.assertEqual(_commodity_query("What's the price of 50 lbs of beef?"), "beef")

    def test_leading_quantity_with_decimal_is_stripped(self):
        self.assertEqual(_commodity_query("What's the price of 2.5 kg of butter?"), "butter")

    def test_how_much_does_x_cost_extracts_the_commodity(self):
        # Confirmed live: the old single regex spanning "how much
        # does...cost" ate everything between them, including the
        # commodity name itself -- this returned None, not "chicken
        # breast", for this exact phrasing.
        self.assertEqual(_commodity_query("How much does chicken breast cost?"), "chicken breast")

    def test_how_much_does_x_cost_with_trailing_filler_extracts_the_commodity(self):
        self.assertEqual(_commodity_query("How much does beef cost right now?"), "beef")

    def test_how_much_does_x_cost_with_leading_quantity_extracts_the_commodity(self):
        self.assertEqual(_commodity_query("How much does 100 kg of chicken breast cost?"), "chicken breast")

    def test_empty_text_has_no_commodity_query(self):
        self.assertIsNone(_commodity_query(""))

    def test_current_wholesale_price_question_extracts_the_commodity(self):
        # Confirmed live: "current wholesale" sitting between "the" and
        # "price" didn't match the old framing pattern at all, so the
        # whole 8-word sentence either fell through as the "commodity" or
        # got rejected by the 6-word cap -- either way, a real USDA AMS
        # lookup for chicken thighs never happened.
        text = "Procurement Specialist, what's the current wholesale price of chicken thighs?"
        self.assertEqual(_commodity_query(text), "chicken thighs")

    def test_current_price_question_extracts_the_commodity(self):
        self.assertEqual(_commodity_query("What's the current price of quinoa?"), "quinoa")


class NonEmptyResultsTests(unittest.TestCase):
    def test_empty_results_list_is_treated_as_no_data(self):
        self.assertIsNone(_non_empty_results('{"keyword": "xyz", "results": []}'))

    def test_populated_results_list_is_passed_through(self):
        raw = '{"keyword": "chicken", "results": [{"slug_id": "1"}]}'
        self.assertEqual(_non_empty_results(raw), raw)

    def test_none_input_is_none(self):
        self.assertIsNone(_non_empty_results(None))

    def test_non_json_input_passes_through_unchanged(self):
        self.assertEqual(_non_empty_results("not json"), "not json")

    def test_error_shaped_json_passes_through_unchanged(self):
        raw = '{"error": "MARS API returned 401"}'
        self.assertEqual(_non_empty_results(raw), raw)


class SearchTermsForTests(unittest.TestCase):
    """A specific, multi-word ingredient name (e.g. "cheddar cheese")
    rarely matches a USDA AMS report title on its own -- confirmed live
    it matches zero, while the commodity word it contains ("cheese")
    matches several real reports. Which word (first or last) is the
    actual commodity varies by ingredient, so both are tried."""

    def test_single_word_name_has_only_itself(self):
        self.assertEqual(_search_terms_for("beef"), ["beef"])

    def test_two_word_name_tries_full_then_first_then_last(self):
        self.assertEqual(_search_terms_for("cheddar cheese"), ["cheddar cheese", "cheddar", "cheese"])

    def test_no_duplicate_terms_for_a_repeated_word(self):
        self.assertEqual(_search_terms_for("chicken chicken"), ["chicken chicken", "chicken"])

    def test_three_word_name_still_only_tries_first_and_last_as_fallbacks(self):
        self.assertEqual(_search_terms_for("grilled chicken breast"), ["grilled chicken breast", "grilled", "breast"])


class FetchReportDataTests(unittest.TestCase):
    """search_reports only returns matching report names/slug_ids -- the
    real pricing rows require a second lookup by the top match's slug_id.
    Confirmed live this was previously skipped entirely: the agent claimed
    "real USDA wholesale commodity market data" while the LLM silently
    invented every price figure, since search_reports's bare slug list
    was passed straight through as if it were the market data itself."""

    def test_none_search_result_makes_no_call(self):
        with patch.object(pa.mcp_client, "call_tool_sync_or_none") as call:
            result = _fetch_report_data(None)

        call.assert_not_called()
        self.assertIsNone(result)

    def test_search_result_with_no_results_makes_no_call(self):
        search_result = json.dumps({"keyword": "xyz", "results": []})
        with patch.object(pa.mcp_client, "call_tool_sync_or_none") as call:
            result = _fetch_report_data(search_result)

        call.assert_not_called()
        self.assertIsNone(result)

    def test_found_match_fetches_real_pricing_rows_by_slug_id(self):
        search_result = json.dumps({"keyword": "beef", "results": [{"slug_id": "2991", "report_title": "National Weekly Beef Review"}]})
        report = json.dumps({"slug_id": "2991", "rows": [{"commodity": "Beef", "price": "$4.50/lb"}]})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", return_value=report) as call:
            result = _fetch_report_data(search_result, commodity_term="beef")

        call.assert_called_once_with("usda_ams", "get_report", {"slug_id": "2991", "commodity": "beef", "limit": 500})
        self.assertEqual(result, report)

    def test_report_lookup_with_no_rows_is_none(self):
        search_result = json.dumps({"keyword": "beef", "results": [{"slug_id": "2991", "report_title": "National Weekly Beef Review"}]})
        report = json.dumps({"slug_id": "2991", "rows": []})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", return_value=report):
            result = _fetch_report_data(search_result)

        self.assertIsNone(result)

    def test_report_lookup_failure_is_none(self):
        search_result = json.dumps({"keyword": "beef", "results": [{"slug_id": "2991", "report_title": "National Weekly Beef Review"}]})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", return_value=None):
            result = _fetch_report_data(search_result)

        self.assertIsNone(result)

    def test_falls_through_to_the_next_candidate_when_the_top_one_has_no_rows(self):
        # Confirmed live: the top-ranked report for a keyword sometimes
        # has zero data rows for the current day (USDA AMS reports don't
        # all publish daily) -- the second candidate should still be tried
        # rather than giving up on the whole commodity.
        search_result = json.dumps({"keyword": "dairy", "results": [
            {"slug_id": "1001", "report_title": "Empty Dairy Report"},
            {"slug_id": "1002", "report_title": "National Dairy Review"},
        ]})
        empty_report = json.dumps({"slug_id": "1001", "rows": []})
        real_report = json.dumps({"slug_id": "1002", "rows": [{"price": "$3.50/gal"}]})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", side_effect=[empty_report, real_report]) as call:
            result = _fetch_report_data(search_result)

        self.assertEqual(call.call_count, 2)
        self.assertEqual(result, real_report)

    def test_gives_up_only_after_every_candidate_has_no_rows(self):
        search_result = json.dumps({"keyword": "dairy", "results": [
            {"slug_id": "1001", "report_title": "Empty Dairy Report"},
            {"slug_id": "1002", "report_title": "Also Empty Dairy Report"},
        ]})
        empty_report_1 = json.dumps({"slug_id": "1001", "rows": []})
        empty_report_2 = json.dumps({"slug_id": "1002", "rows": []})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", side_effect=[empty_report_1, empty_report_2]):
            result = _fetch_report_data(search_result)

        self.assertIsNone(result)


class RowsMatchingTypeTests(unittest.TestCase):
    """USDA AMS report data has no server-side filter for the specific
    cut/item within a commodity -- confirmed live that asked about
    "chicken thighs", the model was handed hundreds of raw price rows
    across every cut/type/region and never found the one that said
    "Thighs, Boneless/Skinless", defaulting to vague hedging instead of
    the real $9.99/lb sitting right there in the data. The query passed
    in here is the CUT residual (see _cut_residual) -- a row's "type"
    field never names the commodity itself (that's a separate field), so
    matching the full "chicken thighs" phrase against it would never hit."""

    def test_matches_a_type_containing_all_significant_words(self):
        rows = [
            {"type": "Thighs, Boneless/Skinless", "region": "NATIONAL", "price_avg": 9.99},
            {"type": "Breast, Boneless/Skinless", "region": "NATIONAL", "price_avg": 4.99},
        ]
        result = _rows_matching_type(rows, "thighs")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "Thighs, Boneless/Skinless")

    def test_prefers_the_national_region_row_over_a_regional_one(self):
        rows = [
            {"type": "Thighs, Boneless/Skinless", "region": "Southeast", "price_avg": 8.50},
            {"type": "Thighs, Boneless/Skinless", "region": "NATIONAL", "price_avg": 9.99},
        ]
        result = _rows_matching_type(rows, "thighs")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["region"], "NATIONAL")

    def test_no_matching_type_returns_empty(self):
        rows = [{"type": "Breast, Boneless/Skinless", "region": "NATIONAL", "price_avg": 4.99}]
        self.assertEqual(_rows_matching_type(rows, "thighs"), [])

    def test_short_words_are_not_treated_as_significant(self):
        # "of"/"a"/"an" etc. (<=3 letters) would match almost any row's
        # type field and defeat the whole point of filtering.
        rows = [{"type": "Breast, Boneless/Skinless", "region": "NATIONAL"}]
        self.assertEqual(_rows_matching_type(rows, "leg of lamb"), [])

    def test_empty_query_returns_empty(self):
        rows = [{"type": "Thighs, Boneless/Skinless", "region": "NATIONAL"}]
        self.assertEqual(_rows_matching_type(rows, ""), [])


class SummarizeCommodityRowsTests(unittest.TestCase):
    def test_none_report_data_is_none(self):
        self.assertEqual(_summarize_commodity_rows(None, "thighs"), (None, False))

    def test_no_rows_is_none(self):
        report = json.dumps({"slug_id": "2756", "rows": []})
        self.assertEqual(_summarize_commodity_rows(report, "thighs"), (None, False))

    def test_exact_match_returns_the_matching_rows_and_true(self):
        report = json.dumps({"slug_id": "2756", "rows": [
            {"type": "Thighs, Boneless/Skinless", "region": "NATIONAL", "price_avg": 9.99},
            {"type": "Breast, Boneless/Skinless", "region": "NATIONAL", "price_avg": 4.99},
        ]})
        summary, exact_match = _summarize_commodity_rows(report, "thighs")
        self.assertTrue(exact_match)
        self.assertIn("Thighs, Boneless/Skinless", summary)
        self.assertNotIn("Breast", summary)

    def test_no_exact_match_falls_back_to_national_sample_and_false(self):
        report = json.dumps({"slug_id": "2756", "rows": [
            {"type": "Breast, Boneless/Skinless", "region": "NATIONAL", "price_avg": 4.99},
            {"type": "Breast, Boneless/Skinless", "region": "Southeast", "price_avg": 4.50},
        ]})
        summary, exact_match = _summarize_commodity_rows(report, "thighs")
        self.assertFalse(exact_match)
        self.assertIn("Breast, Boneless/Skinless", summary)
        self.assertNotIn("Southeast", summary)  # only the NATIONAL row, not the regional one

    def test_no_national_rows_falls_back_to_whatever_rows_exist(self):
        report = json.dumps({"slug_id": "2756", "rows": [
            {"type": "Breast, Boneless/Skinless", "region": "Southeast", "price_avg": 4.50},
        ]})
        summary, exact_match = _summarize_commodity_rows(report, "thighs")
        self.assertFalse(exact_match)
        self.assertIn("Southeast", summary)


class CutResidualTests(unittest.TestCase):
    """The commodity word (used as get_report's server-side filter) has
    to be stripped before matching a row's "type" field -- confirmed live
    that "chicken" never appears in "type" (it's the separate "commodity"
    field), so leaving it in made every single cut look like "no exact
    match" regardless of what was actually in the data."""

    def test_strips_the_matched_commodity_word(self):
        self.assertEqual(pa._cut_residual("chicken thighs", "chicken"), "thighs")

    def test_is_case_insensitive(self):
        self.assertEqual(pa._cut_residual("Chicken Thighs", "chicken"), "Thighs")

    def test_multi_word_commodity_term_is_fully_stripped(self):
        self.assertEqual(pa._cut_residual("cheddar cheese block", "cheddar cheese"), "block")

    def test_no_residual_left_falls_back_to_the_full_query(self):
        # e.g. term == commodity_query itself (the full-name search
        # attempt succeeded) -- there's no cut-specific residual to match
        # against "type", so matching against the full query is the best
        # available fallback rather than matching nothing at all.
        self.assertEqual(pa._cut_residual("beef", "beef"), "beef")


class ExtractIngredientsTests(unittest.TestCase):
    """Extracts the ACTUAL ingredient names, not a generalized bucket
    category -- confirmed the user explicitly wants "cheddar cheese" in
    the response, not "dairy"; matching that specific name against real
    USDA report titles is handled separately (see SearchTermsForTests)."""

    def test_parses_ingredients_from_llm_json_response(self):
        raw = '{"ingredients": ["chicken breast", "parmesan cheese"]}'
        with patch.object(pa.llm_utils, "chat_sync", return_value=raw):
            result = _extract_ingredients("Chicken breast: 150g. Parmesan cheese: 30g.")

        self.assertEqual(result, ["chicken breast", "parmesan cheese"])

    def test_response_with_no_json_object_is_empty(self):
        with patch.object(pa.llm_utils, "chat_sync", return_value="sorry, I can't help with that"):
            result = _extract_ingredients("some recipe text")

        self.assertEqual(result, [])

    def test_malformed_json_is_empty(self):
        with patch.object(pa.llm_utils, "chat_sync", return_value="{ingredients: [oops]}"):
            result = _extract_ingredients("some recipe text")

        self.assertEqual(result, [])

    def test_blank_or_non_string_entries_are_dropped(self):
        raw = '{"ingredients": ["chicken breast", "  ", 5, ""]}'
        with patch.object(pa.llm_utils, "chat_sync", return_value=raw):
            result = _extract_ingredients("some recipe text")

        self.assertEqual(result, ["chicken breast"])


class FetchAllMarketDataTests(unittest.TestCase):
    """Batched two-round lookup (search round, then detail round) across
    every ingredient in a whole week's menu -- same two-stage shape as
    recipe_portion_agent.py's _fetch_all_recipes and nutrition_agent.py's
    _fetch_all_nutrients. Since every ingredient here is a single word,
    the search-term fallback (see SearchTermsForTests) never triggers, so
    these behave like a plain one-term-per-ingredient search."""

    def test_empty_ingredient_list_makes_no_calls(self):
        with patch.object(pa.mcp_client, "call_tools_parallel_sync") as call:
            result = _fetch_all_market_data([])

        call.assert_not_called()
        self.assertEqual(result, {})

    def test_every_ingredient_found_maps_to_its_real_detail(self):
        search_results = [
            json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]}),
            json.dumps({"keyword": "beef", "results": [{"slug_id": "222", "report_title": "Weekly Beef Report"}]}),
        ]
        chicken_rows = [{"price": "$1.50/lb"}]
        beef_rows = [{"price": "$4.50/lb"}]
        detail_results = [
            json.dumps({"slug_id": "111", "rows": chicken_rows}),
            json.dumps({"slug_id": "222", "rows": beef_rows}),
        ]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_market_data(["chicken", "beef"])

        self.assertEqual(call.call_count, 2)
        detail_requests = call.call_args_list[1].args[0]
        self.assertEqual(detail_requests, [
            ("usda_ams", "get_report", {"slug_id": "111", "commodity": "chicken", "limit": 500}),
            ("usda_ams", "get_report", {"slug_id": "222", "commodity": "beef", "limit": 500}),
        ])
        # No "type"/"region" fields on these fixture rows, so the
        # cut/NATIONAL matching in _summarize_commodity_rows finds
        # nothing to narrow to and falls back to the rows as retrieved.
        self.assertEqual(result, {"chicken": json.dumps(chicken_rows), "beef": json.dumps(beef_rows)})

    def test_ingredient_with_no_search_match_maps_to_none_without_a_detail_call(self):
        search_results = [
            json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]}),
            json.dumps({"keyword": "kumquat", "results": []}),
        ]
        chicken_rows = [{"price": "$1.50/lb"}]
        detail_results = [json.dumps({"slug_id": "111", "rows": chicken_rows})]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]) as call:
            result = _fetch_all_market_data(["chicken", "kumquat"])

        detail_requests = call.call_args_list[1].args[0]
        self.assertEqual(detail_requests, [("usda_ams", "get_report", {"slug_id": "111", "commodity": "chicken", "limit": 500})])
        self.assertEqual(result, {"chicken": json.dumps(chicken_rows), "kumquat": None})

    def test_no_ingredient_found_at_all_skips_the_detail_round_entirely(self):
        search_results = [json.dumps({"keyword": "kumquat", "results": []})]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", return_value=search_results) as call:
            result = _fetch_all_market_data(["kumquat"])

        call.assert_called_once()
        self.assertEqual(result, {"kumquat": None})

    def test_detail_lookup_with_no_rows_maps_to_none(self):
        search_results = [json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]})]
        detail_results = [json.dumps({"slug_id": "111", "rows": []})]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]):
            result = _fetch_all_market_data(["chicken"])

        self.assertEqual(result, {"chicken": None})

    def test_falls_through_to_the_next_candidate_when_the_top_one_has_no_rows(self):
        # Confirmed live: the top-ranked report sometimes has zero data
        # rows for the current day -- a second retry round, still
        # parallel, should pick up the next candidate for whichever
        # ingredients failed on their first try.
        search_results = [json.dumps({"keyword": "milk", "results": [
            {"slug_id": "1001", "report_title": "Empty Milk Report"},
            {"slug_id": "1002", "report_title": "National Milk Review"},
        ]})]
        empty_report = json.dumps({"slug_id": "1001", "rows": []})
        milk_rows = [{"price": "$3.50/gal"}]
        real_report = json.dumps({"slug_id": "1002", "rows": milk_rows})

        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, [empty_report], [real_report]]) as call:
            result = _fetch_all_market_data(["milk"])

        self.assertEqual(call.call_count, 3)  # search round + 2 detail rounds
        second_detail_requests = call.call_args_list[2].args[0]
        self.assertEqual(second_detail_requests, [("usda_ams", "get_report", {"slug_id": "1002", "commodity": "milk", "limit": 500})])
        self.assertEqual(result, {"milk": json.dumps(milk_rows)})

    def test_retry_rounds_do_not_affect_an_ingredient_that_already_found_data(self):
        # One ingredient needs a retry round; another finds data on its
        # first try and must not be re-fetched in the second round.
        search_results = [
            json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]}),
            json.dumps({"keyword": "milk", "results": [
                {"slug_id": "1001", "report_title": "Empty Milk Report"},
                {"slug_id": "1002", "report_title": "National Milk Review"},
            ]}),
        ]
        chicken_rows = [{"price": "$1.50/lb"}]
        milk_rows = [{"price": "$3.50/gal"}]
        chicken_report = json.dumps({"slug_id": "111", "rows": chicken_rows})
        empty_milk_report = json.dumps({"slug_id": "1001", "rows": []})
        real_milk_report = json.dumps({"slug_id": "1002", "rows": milk_rows})

        with patch.object(
            pa.mcp_client, "call_tools_parallel_sync",
            side_effect=[search_results, [chicken_report, empty_milk_report], [real_milk_report]],
        ) as call:
            result = _fetch_all_market_data(["chicken", "milk"])

        second_detail_requests = call.call_args_list[2].args[0]
        self.assertEqual(second_detail_requests, [("usda_ams", "get_report", {"slug_id": "1002", "commodity": "milk", "limit": 500})])
        self.assertEqual(result, {"chicken": json.dumps(chicken_rows), "milk": json.dumps(milk_rows)})

    def test_gives_up_only_after_every_candidate_has_no_rows(self):
        search_results = [json.dumps({"keyword": "milk", "results": [
            {"slug_id": "1001", "report_title": "Empty Milk Report"},
            {"slug_id": "1002", "report_title": "Also Empty Milk Report"},
        ]})]
        empty_report_1 = json.dumps({"slug_id": "1001", "rows": []})
        empty_report_2 = json.dumps({"slug_id": "1002", "rows": []})

        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, [empty_report_1], [empty_report_2]]) as call:
            result = _fetch_all_market_data(["milk"])

        self.assertEqual(call.call_count, 3)  # search round + 2 detail rounds, then gives up
        self.assertEqual(result, {"milk": None})

    def test_falls_back_to_a_shorter_search_term_when_the_full_name_matches_nothing(self):
        # "cheddar cheese" itself matches no report title, and neither
        # does its first word "cheddar" -- but its last word "cheese"
        # does (confirmed live). _search_terms_for tries all three in
        # order (full, first, last), so all three search rounds happen
        # before the detail round.
        no_match_full = json.dumps({"keyword": "cheddar cheese", "results": []})
        no_match_first = json.dumps({"keyword": "cheddar", "results": []})
        real_match = json.dumps({"keyword": "cheese", "results": [{"slug_id": "5001", "report_title": "Cheese - Oceania"}]})
        cheese_rows = [{"price": "$2.10/lb"}]
        report = json.dumps({"slug_id": "5001", "rows": cheese_rows})

        with patch.object(
            pa.mcp_client, "call_tools_parallel_sync",
            side_effect=[[no_match_full], [no_match_first], [real_match], [report]],
        ) as call:
            result = _fetch_all_market_data(["cheddar cheese"])

        self.assertEqual(call.call_count, 4)  # 3 search rounds (full, first, last word) + 1 detail round
        third_search_requests = call.call_args_list[2].args[0]
        self.assertEqual(third_search_requests, [("usda_ams", "search_reports", {"keyword": "cheese", "limit": 3})])
        fourth_detail_requests = call.call_args_list[3].args[0]
        self.assertEqual(fourth_detail_requests, [("usda_ams", "get_report", {"slug_id": "5001", "commodity": "cheese", "limit": 500})])
        self.assertEqual(result, {"cheddar cheese": json.dumps(cheese_rows)})

    def test_two_ingredients_landing_on_the_same_report_do_not_both_carry_it(self):
        # "chicken breast" and "chicken thigh" both fall back to the word
        # "chicken" and match report 111. The first ingredient keeps it;
        # the second, with no other candidate, ends up None -- the same
        # pricing block is not printed twice.
        search_results = [
            json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]}),
            json.dumps({"keyword": "chicken", "results": [{"slug_id": "111", "report_title": "Weekly Chicken Report"}]}),
        ]
        chicken_rows = [{"price": "$1.50/lb"}]
        report = json.dumps({"slug_id": "111", "rows": chicken_rows})
        with patch.object(pa.mcp_client, "call_tools_parallel_sync",
                          side_effect=[search_results, [report, report]]) as call:
            result = _fetch_all_market_data(["chicken breast", "chicken thigh"])

        self.assertEqual(result, {"chicken breast": json.dumps(chicken_rows), "chicken thigh": None})

    def test_narrows_to_the_specific_cut_out_of_many_unrelated_rows(self):
        # Confirmed live: asked to source "lamb" (via a whole-menu run),
        # the report matched on "lamb" carried dozens of rows for OTHER
        # cuts/items -- with no filtering, the model never found the one
        # for lamb specifically and invented a fictional retailer instead.
        # This proves the real fix: only the matching row(s) reach the LLM.
        search_results = [json.dumps({"keyword": "lamb", "results": [{"slug_id": "9001", "report_title": "Weekly Lamb Report"}]})]
        rows = [
            {"type": "Leg, Bone-In", "region": "NATIONAL", "price_avg": 7.99},
            {"type": "Loin Chops", "region": "NATIONAL", "price_avg": 12.99},
            {"type": "Ground", "region": "Southeast", "price_avg": 6.49},
        ]
        detail_results = [json.dumps({"slug_id": "9001", "rows": rows})]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", side_effect=[search_results, detail_results]):
            result = _fetch_all_market_data(["lamb"])

        # "lamb" itself matches no row's "type" (that word lives in the
        # separate "commodity" field), so this falls back to a NATIONAL
        # sample -- but critically, NOT the Southeast-only ground lamb row.
        stored = json.loads(result["lamb"])
        self.assertEqual(len(stored), 2)
        self.assertTrue(all(row["region"] == "NATIONAL" for row in stored))


class UsableWebSearchResultTests(unittest.TestCase):
    """The web_search MCP tool returns a JSON {"error": ...} payload
    rather than failing the call outright when TAVILY_API_KEY is unset --
    _usable_web_search_result is what actually distinguishes "configured
    but found nothing" from "not configured" from a genuinely usable
    result, since raw truthiness alone can't tell them apart."""

    def test_none_input_is_not_usable(self):
        self.assertIsNone(_usable_web_search_result(None))

    def test_error_payload_is_not_usable(self):
        raw = json.dumps({"error": "TAVILY_API_KEY not configured"})
        self.assertIsNone(_usable_web_search_result(raw))

    def test_empty_results_and_no_answer_is_not_usable(self):
        raw = json.dumps({"query": "quinoa price", "answer": None, "results": []})
        self.assertIsNone(_usable_web_search_result(raw))

    def test_results_present_is_usable(self):
        raw = json.dumps({"query": "quinoa price", "answer": None, "results": [{"title": "x", "url": "y", "content": "z"}]})
        self.assertEqual(_usable_web_search_result(raw), raw)

    def test_answer_present_with_no_results_is_still_usable(self):
        raw = json.dumps({"query": "quinoa price", "answer": "About $4/lb.", "results": []})
        self.assertEqual(_usable_web_search_result(raw), raw)

    def test_malformed_json_is_not_usable(self):
        self.assertIsNone(_usable_web_search_result("not json"))


class FetchWebPriceContextTests(unittest.TestCase):
    def test_queries_web_search_for_current_retail_pricing(self):
        web_result = json.dumps({"query": "quinoa price per pound grocery store", "answer": "About $4/lb.", "results": []})
        with patch.object(pa.mcp_client, "call_tool_sync_or_none", return_value=web_result) as call:
            result = _fetch_web_price_context("quinoa")

        call.assert_called_once_with("web_search", "search", {"query": "quinoa price per pound grocery store", "max_results": 5})
        self.assertEqual(result, web_result)

    def test_unconfigured_or_no_result_returns_none(self):
        with patch.object(pa.mcp_client, "call_tool_sync_or_none", return_value=json.dumps({"error": "TAVILY_API_KEY not configured"})):
            result = _fetch_web_price_context("quinoa")

        self.assertIsNone(result)


class FetchAllWebPricesTests(unittest.TestCase):
    def test_empty_ingredient_list_makes_no_calls(self):
        with patch.object(pa.mcp_client, "call_tools_parallel_sync") as call:
            result = _fetch_all_web_prices([])

        call.assert_not_called()
        self.assertEqual(result, {})

    def test_one_search_per_ingredient_in_parallel(self):
        results = [
            json.dumps({"query": "quinoa price per pound grocery store", "answer": "About $4/lb.", "results": []}),
            json.dumps({"error": "TAVILY_API_KEY not configured"}),
        ]
        with patch.object(pa.mcp_client, "call_tools_parallel_sync", return_value=results) as call:
            result = _fetch_all_web_prices(["quinoa", "shrimp"])

        requests = call.call_args[0][0]
        self.assertEqual(requests[0], ("web_search", "search", {"query": "quinoa price per pound grocery store", "max_results": 5}))
        self.assertEqual(requests[1], ("web_search", "search", {"query": "shrimp price per pound grocery store", "max_results": 5}))
        self.assertEqual(result["quinoa"], results[0])
        self.assertIsNone(result["shrimp"])


class SingleCommodityBudgetHintTests(unittest.TestCase):
    """A single-commodity/general answer is about ONE thing, not a whole
    menu -- confirmed live that sharing the whole-menu path's 300-word
    class default produced verbose, repetitive answers (the same generic
    hedge padded out across unrelated commodities)."""

    def test_caps_at_the_target_when_the_callers_budget_is_larger(self):
        hint = _single_commodity_budget_hint(300)
        self.assertIn("roughly 60 words", hint)

    def test_respects_a_smaller_caller_budget(self):
        hint = _single_commodity_budget_hint(30)
        self.assertIn("roughly 30 words", hint)


class SystemPromptTests(unittest.TestCase):
    def test_does_not_hand_the_model_a_concrete_recommendation_to_anchor_on(self):
        # Confirmed live: "(e.g. lock in a contract price vs. buy spot)"
        # became the model's own go-to recommendation, echoed back nearly
        # verbatim regardless of the commodity or what the retrieved data
        # actually showed -- the same anchoring failure mode already
        # fixed for Menu Designer's Caesar salad example.
        self.assertNotIn("e.g. lock in a contract", pa.SYSTEM_PROMPT)

    def test_forbids_substituting_a_different_cut_than_the_one_asked_about(self):
        # Confirmed live: asked about "chicken thighs", the model answered
        # about "chicken breast" instead -- the retrieved USDA report
        # covered the broader commodity with no cut-level detail, and
        # nothing told the model to stick to the exact cut named in the
        # question rather than substitute a different one.
        self.assertIn("EXACT commodity/cut named in the question", pa.SYSTEM_PROMPT)

    def test_forbids_inventing_a_retailer_name(self):
        # Confirmed live: the model named a specific fictional supplier
        # ("Local Meats R Us") that appears nowhere in real USDA AMS
        # wholesale report data -- the whole-menu prompt already forbids
        # inventing a retailer; the single-commodity prompt didn't.
        self.assertIn("Never invent a specific retailer, supplier, or vendor name", pa.SYSTEM_PROMPT)

    def test_forbids_claiming_real_data_grounding_when_none_was_retrieved(self):
        # Confirmed live: the model opened with "Based on the recent USDA
        # wholesale market data" while giving vague, ungrounded guidance --
        # the existing "don't imply you found real data" instruction wasn't
        # concrete enough to stop this specific framing.
        self.assertIn('"based on recent USDA data"', pa.SYSTEM_PROMPT)

    def test_forbids_vague_hedging_when_broader_commodity_data_exists(self):
        # Confirmed live: told correctly that thighs weren't broken out
        # separately, the model then padded the rest with generic hedge
        # language ("prices are volatile, monitor closely") instead of
        # citing the real numbers the broader-commodity report did show.
        self.assertIn("do NOT then fall back to vague, generic language", pa.SYSTEM_PROMPT)


class OnObservedUtteranceTests(unittest.TestCase):
    """The Procurement Specialist watches Pass-Through broadcast traffic
    for the Recipe & Portion Specialist's one-serving recipe writeup, keyed
    per-conversation, so a broad planning question can still be grounded
    in real market data for every ingredient the actual menu uses."""

    def test_saves_text_from_recipe_portion(self):
        agent = ProcurementAgent()

        agent.on_observed_utterance("conv-1", pa._RECIPE_PORTION_SERVICE_URL, "Chicken breast: 150g.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken breast: 150g."})

    def test_matches_the_recipe_portion_uri_case_and_slash_insensitively(self):
        agent = ProcurementAgent()
        loud_uri = pa._RECIPE_PORTION_SERVICE_URL.upper().rstrip("/")

        agent.on_observed_utterance("conv-1", loud_uri, "Chicken breast: 150g.")

        self.assertEqual(agent._observed_recipes, {"conv-1": "Chicken breast: 150g."})

    def test_ignores_utterances_from_other_speakers(self):
        agent = ProcurementAgent()

        agent.on_observed_utterance("conv-1", "http://127.0.0.1:8301/", "some menu designer commentary")

        self.assertEqual(agent._observed_recipes, {})

    def test_different_conversations_are_kept_separate(self):
        agent = ProcurementAgent()

        agent.on_observed_utterance("conv-1", pa._RECIPE_PORTION_SERVICE_URL, "recipes for conv 1")
        agent.on_observed_utterance("conv-2", pa._RECIPE_PORTION_SERVICE_URL, "recipes for conv 2")

        self.assertEqual(agent._observed_recipes, {"conv-1": "recipes for conv 1", "conv-2": "recipes for conv 2"})


class RespondGeneralTests(unittest.TestCase):
    def test_includes_a_single_commodity_budget_hint(self):
        agent = ProcurementAgent()
        agent._current_max_words = 300
        with patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_general("what should we do about groceries this week?")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("ONE commodity, not a whole menu", user_message)
        self.assertIn("roughly 60 words", user_message)


class ProcessUtteranceBranchingTests(unittest.TestCase):
    """process_utterance is a 3-way dispatcher: a single named commodity
    wins first, then a saved whole-menu recipe writeup, then a
    general-reasoning fallback -- same shape as recipe_portion_agent.py's
    and nutrition_agent.py's dispatchers."""

    def _make_agent(self, conv_id="conv-1", saved_recipes=""):
        agent = ProcurementAgent()
        agent._current_conv_id = conv_id
        if saved_recipes:
            agent._observed_recipes[conv_id] = saved_recipes
        return agent

    def test_single_named_commodity_takes_priority_even_with_saved_recipes(self):
        agent = self._make_agent(saved_recipes="Chicken breast: 150g.")
        with patch.object(agent, "_respond_for_one_commodity", return_value="one-commodity reply") as one_commodity, \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu:
            result = agent.process_utterance("What's the market price for beef?")

        one_commodity.assert_called_once_with("What's the market price for beef?", "beef")
        whole_menu.assert_not_called()
        self.assertEqual(result, "one-commodity reply")

    def test_broad_request_with_saved_recipes_and_extractable_ingredients_uses_whole_menu(self):
        agent = self._make_agent(saved_recipes="Chicken breast: 150g. Parmesan cheese: 30g.")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(pa, "_extract_ingredients", return_value=["chicken breast", "parmesan cheese"]) as extract, \
             patch.object(agent, "_respond_for_whole_menu", return_value="whole-menu reply") as whole_menu:
            result = agent.process_utterance(broad_text)

        extract.assert_called_once_with("Chicken breast: 150g. Parmesan cheese: 30g.")
        whole_menu.assert_called_once_with("Chicken breast: 150g. Parmesan cheese: 30g.", ["chicken breast", "parmesan cheese"])
        self.assertEqual(result, "whole-menu reply")

    def test_broad_request_with_no_saved_recipes_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_recipes="")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()

    def test_saved_recipes_that_extract_no_ingredients_falls_back_to_general_reasoning(self):
        agent = self._make_agent(saved_recipes="not actually a recipe writeup")
        broad_text = "Plan a five-day lunch menu for 450 people with itemized costs, budget of $7.00 per meal."
        with patch.object(pa, "_extract_ingredients", return_value=[]), \
             patch.object(agent, "_respond_for_whole_menu") as whole_menu, \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance(broad_text)

        whole_menu.assert_not_called()
        chat_sync.assert_called_once()


class RespondForOneCommodityTests(unittest.TestCase):
    def test_falls_back_to_a_shorter_search_term_when_the_full_query_matches_nothing(self):
        agent = ProcurementAgent()
        no_match_full = json.dumps({"keyword": "cheddar cheese", "results": []})
        no_match_first = json.dumps({"keyword": "cheddar", "results": []})
        real_match = json.dumps({"keyword": "cheese", "results": [{"slug_id": "5001", "report_title": "Cheese - Oceania"}]})
        report = json.dumps({"slug_id": "5001", "rows": [{"price": "$2.10/lb"}]})

        with patch.object(
            pa.mcp_client, "call_tool_sync_or_none",
            side_effect=[no_match_full, no_match_first, real_match, report],
        ) as call, \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_one_commodity("what's the price of cheddar cheese?", "cheddar cheese")

        search_calls = [c for c in call.call_args_list if c.args[1] == "search_reports"]
        self.assertEqual([c.args[2]["keyword"] for c in search_calls], ["cheddar cheese", "cheddar", "cheese"])
        user_message = chat_sync.call_args[0][1]
        self.assertIn("$2.10/lb", user_message)

    def test_includes_a_single_commodity_budget_hint(self):
        agent = ProcurementAgent()
        agent._current_max_words = 300
        no_match = json.dumps({"keyword": "beef", "results": []})
        with patch.object(pa.mcp_client, "call_tool_sync_or_none", side_effect=[no_match, None]), \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_one_commodity("what's the price of beef?", "beef")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("ONE commodity, not a whole menu", user_message)
        self.assertIn("roughly 60 words", user_message)

    def test_no_match_on_any_fallback_term_falls_back_to_web_search(self):
        # "xyz" is a single word, so _search_terms_for tries exactly one
        # USDA search term before falling through to web search.
        agent = ProcurementAgent()
        no_match = json.dumps({"keyword": "xyz", "results": []})
        web_result = json.dumps({"query": "xyz price per pound grocery store", "answer": "About $3/lb.", "results": []})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", side_effect=[no_match, web_result]) as call, \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_one_commodity("what's the price of xyz?", "xyz")

        web_call = call.call_args_list[-1]
        self.assertEqual(web_call.args[:2], ("web_search", "search"))
        user_message = chat_sync.call_args[0][1]
        self.assertIn("Web search results for current retail pricing", user_message)
        self.assertIn("About $3/lb.", user_message)

    def test_no_match_from_usda_or_web_search_uses_general_guidance(self):
        agent = ProcurementAgent()
        no_match = json.dumps({"keyword": "xyz", "results": []})
        web_no_result = json.dumps({"error": "TAVILY_API_KEY not configured"})

        with patch.object(pa.mcp_client, "call_tool_sync_or_none", side_effect=[no_match, web_no_result]), \
             patch.object(pa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent._respond_for_one_commodity("what's the price of xyz?", "xyz")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("No matching USDA market data or web search results found", user_message)


class RenderIngredientGuidanceTests(unittest.TestCase):
    """The whole-menu response asks for structured JSON (one object per
    ingredient) specifically so Python code -- not the model -- decides
    where each ingredient's line breaks. Confirmed live that a plain-
    prose "keep it on one line" instruction was not reliable even after
    tightening it twice (the model still split a multi-sentence entry
    across two, then three, lines)."""

    def test_renders_one_line_per_ingredient(self):
        raw = json.dumps({"ingredients": [
            {"name": "Chicken breast", "guidance": "Buy spot. Prices are stable."},
            {"name": "Beef sirloin", "guidance": "Lock in a contract."},
        ]})
        result = pa._render_ingredient_guidance(raw)

        self.assertEqual(
            result,
            "Chicken breast: Buy spot. Prices are stable.\nBeef sirloin: Lock in a contract.",
        )

    def test_multi_sentence_guidance_stays_on_one_line(self):
        # Confirmed live: this is exactly the case a plain-text
        # instruction failed to hold -- a guidance value spanning several
        # sentences must never introduce a raw newline of its own.
        raw = json.dumps({"ingredients": [
            {"name": "Cornstarch", "guidance": "Buy from a bulk supplier. Choose a reputable brand. Store dry."},
        ]})
        result = pa._render_ingredient_guidance(raw)

        self.assertEqual(result, "Cornstarch: Buy from a bulk supplier. Choose a reputable brand. Store dry.")

    def test_guidance_with_embedded_newlines_is_collapsed(self):
        raw = json.dumps({"ingredients": [{"name": "Garlic", "guidance": "Buy from local suppliers.\nCheck freshness."}]})
        result = pa._render_ingredient_guidance(raw)

        self.assertEqual(result, "Garlic: Buy from local suppliers. Check freshness.")

    def test_entries_missing_name_or_guidance_are_dropped(self):
        raw = json.dumps({"ingredients": [
            {"name": "Garlic", "guidance": "Buy local."},
            {"name": "", "guidance": "some guidance"},
            {"name": "Broccoli", "guidance": ""},
        ]})
        result = pa._render_ingredient_guidance(raw)

        self.assertEqual(result, "Garlic: Buy local.")

    def test_no_json_object_falls_back_to_raw_text(self):
        raw = "sorry, I can't help with that"
        self.assertEqual(pa._render_ingredient_guidance(raw), raw)

    def test_malformed_json_falls_back_to_raw_text(self):
        raw = "{ingredients: [oops]}"
        self.assertEqual(pa._render_ingredient_guidance(raw), raw)

    def test_no_usable_entries_falls_back_to_raw_text(self):
        raw = json.dumps({"ingredients": [{"name": "", "guidance": ""}]})
        self.assertEqual(pa._render_ingredient_guidance(raw), raw)

    def test_multiple_brand_entries_for_one_ingredient_collapse_to_one_line(self):
        raw = json.dumps({"ingredients": [
            {"name": "Le Sueur Very Young Small Sweet Peas", "guidance": "Buy local or online; organic preferred."},
            {"name": "Great Value Organic Frozen Steamable Sweet Peas", "guidance": "Get from local grocery stores."},
            {"name": "Del Monte No Salt Added Sweet Peas", "guidance": "Purchase from local grocery stores."},
            {"name": "Chicken breast", "guidance": "Buy the 40 lb case."},
        ]})
        result = pa._render_ingredient_guidance(raw, ["peas", "chicken breast"])

        self.assertEqual(
            result,
            "peas: Buy local or online; organic preferred.\nChicken breast: Buy the 40 lb case.",
        )

    def test_a_plain_name_matching_the_menu_keeps_its_own_casing(self):
        raw = json.dumps({"ingredients": [{"name": "Chicken Breast", "guidance": "Buy spot."}]})
        self.assertEqual(
            pa._render_ingredient_guidance(raw, ["chicken breast"]),
            "Chicken Breast: Buy spot.",
        )

    def test_near_duplicate_lines_in_the_raw_fallback_are_collapsed(self):
        raw = (
            "Le Sueur Very Young Small Sweet Peas - buy local or online.\n"
            "Great Value Organic Frozen Sweet Peas - buy local or online.\n"
            "Cheddar cheese - restaurant supply, 5 lb block."
        )
        self.assertEqual(
            pa._render_ingredient_guidance("not json\n" + raw, ["peas", "cheddar cheese"]),
            "not json\npeas: buy local or online.\nCheddar cheese: restaurant supply, 5 lb block.",
        )


class RespondForWholeMenuTests(unittest.TestCase):
    def test_asks_for_guidance_covering_every_ingredient(self):
        agent = ProcurementAgent()
        empty_reply = json.dumps({"ingredients": []})
        with patch.object(pa, "_fetch_all_market_data", return_value={"chicken breast": None}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={}), \
             patch.object(pa.llm_utils, "chat_sync", return_value=empty_reply) as chat_sync:
            agent._respond_for_whole_menu("Chicken breast: 150g.", ["chicken breast"])

        self.assertEqual(chat_sync.call_args[0][0], pa._WHOLE_MENU_SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("EVERY ingredient", user_message)
        self.assertIn("chicken breast", user_message)

    def test_per_ingredient_word_budget_is_computed_and_injected(self):
        agent = ProcurementAgent()
        agent._current_max_words = 300
        empty_reply = json.dumps({"ingredients": []})
        with patch.object(pa, "_fetch_all_market_data", return_value={"chicken": None, "beef": None, "milk": None}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={}), \
             patch.object(pa.llm_utils, "chat_sync", return_value=empty_reply) as chat_sync:
            agent._respond_for_whole_menu("some recipe text", ["chicken", "beef", "milk"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("This menu uses 3 ingredients", user_message)
        self.assertIn("100 words", user_message)  # 300 // 3

    def test_per_ingredient_word_budget_never_drops_below_the_floor(self):
        agent = ProcurementAgent()
        agent._current_max_words = 20
        ingredients = [f"ingredient{i}" for i in range(7)]
        empty_reply = json.dumps({"ingredients": []})
        with patch.object(pa, "_fetch_all_market_data", return_value={i: None for i in ingredients}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={}), \
             patch.object(pa.llm_utils, "chat_sync", return_value=empty_reply) as chat_sync:
            agent._respond_for_whole_menu("some recipe text", ingredients)

        user_message = chat_sync.call_args[0][1]
        self.assertIn("20 words", user_message)  # max(20, 20 // 7) == 20

    def test_ingredients_with_no_usda_or_web_data_are_named_not_silently_dropped(self):
        agent = ProcurementAgent()
        empty_reply = json.dumps({"ingredients": []})
        with patch.object(pa, "_fetch_all_market_data", return_value={"chicken breast": None, "beef sirloin": '{"rows": [{"price": "$4.50/lb"}]}'}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={"chicken breast": None}) as fetch_web, \
             patch.object(pa.llm_utils, "chat_sync", return_value=empty_reply) as chat_sync:
            agent._respond_for_whole_menu("some recipe text", ["chicken breast", "beef sirloin"])

        # Only the ingredient USDA had nothing for gets a web search --
        # no point re-searching one already grounded in real wholesale data.
        fetch_web.assert_called_once_with(["chicken breast"])
        user_message = chat_sync.call_args[0][1]
        self.assertIn("Ingredients with no data found (USDA or web search): chicken breast", user_message)
        self.assertIn("beef sirloin", user_message)

    def test_ingredient_with_no_usda_data_uses_web_search_pricing_instead(self):
        agent = ProcurementAgent()
        empty_reply = json.dumps({"ingredients": []})
        web_result = json.dumps({"query": "quinoa price per pound grocery store", "answer": "About $4/lb at most grocers.", "results": []})
        with patch.object(pa, "_fetch_all_market_data", return_value={"quinoa": None}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={"quinoa": web_result}), \
             patch.object(pa.llm_utils, "chat_sync", return_value=empty_reply) as chat_sync:
            agent._respond_for_whole_menu("some recipe text", ["quinoa"])

        user_message = chat_sync.call_args[0][1]
        self.assertIn("quinoa (web search retail pricing)", user_message)
        self.assertIn("About $4/lb at most grocers.", user_message)
        self.assertNotIn("Ingredients with no data found", user_message)

    def test_multi_ingredient_response_becomes_an_html_list(self):
        agent = ProcurementAgent()
        raw_reply = json.dumps({"ingredients": [
            {"name": "Chicken breast", "guidance": "Buy spot."},
            {"name": "Beef sirloin", "guidance": "Lock in a contract."},
        ]})
        with patch.object(pa, "_fetch_all_market_data", return_value={"chicken breast": None, "beef sirloin": None}), \
             patch.object(pa, "_fetch_all_web_prices", return_value={}), \
             patch.object(pa.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent._respond_for_whole_menu("some recipe text", ["chicken breast", "beef sirloin"])

        self.assertEqual(result["text"], "Chicken breast: Buy spot.\nBeef sirloin: Lock in a contract.")
        self.assertEqual(
            result["html"],
            "<ul><li>Chicken breast: Buy spot.</li><li>Beef sirloin: Lock in a contract.</li></ul>",
        )


class NeedsUnavailableDataTests(unittest.TestCase):
    """Questions about this cafeteria's own purchasing (past prices paid,
    suppliers, contracts) are declined without an LLM call -- the system
    has no such records and qwen2.5:7b otherwise pads with generic
    'monitor the market' advice."""

    def test_own_purchasing_record_questions_are_flagged(self):
        for q in [
            "What did we pay per pound for chicken breast last quarter?",
            "Who is our current supplier for produce?",
            "What's our contract price on beef?",
            "How much have we spent so far this year on seafood?",
        ]:
            self.assertTrue(pa._needs_unavailable_data(q), q)

    def test_plain_market_questions_are_not_flagged(self):
        for q in [
            "What's the current wholesale price of russet potatoes?",
            "How have beef prices moved this quarter?",
            "Should we buy chicken now or wait?",
        ]:
            self.assertFalse(pa._needs_unavailable_data(q), q)

    def test_a_flagged_question_is_declined_without_an_llm_call(self):
        agent = ProcurementAgent()
        agent._current_conv_id = "conv-1"
        with patch.object(pa.llm_utils, "chat_sync") as chat_sync:
            result = agent.process_utterance("What did we pay for chicken breast last quarter, and who is our supplier?")

        chat_sync.assert_not_called()
        self.assertIn("don't have data on this cafeteria's own purchasing", result["text"])
        self.assertEqual(result["html"], "")


if __name__ == "__main__":
    unittest.main()
