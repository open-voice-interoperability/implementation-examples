import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.menu_designer import menu_designer_agent as mda


class SystemPromptScopeTests(unittest.TestCase):
    """A compound request ("plan a menu, then assess inventory risk for
    it") was confirmed live to make Menu Designer drift into answering
    the inventory-risk part too, duplicating (less well) what the
    Inventory Specialist's own turn already covers. This just guards
    against the explicit "stay in your lane" instruction being edited
    away by accident -- actual model compliance is verified live, not by
    this unit test, matching this project's established pattern that
    prompt wording alone is confirmed by running it, not just reading it."""

    def test_prompt_tells_the_model_to_ignore_non_menu_parts_of_the_request(self):
        self.assertIn("IGNORE that part entirely", mda.SYSTEM_PROMPT)
        self.assertIn("inventory", mda.SYSTEM_PROMPT.lower())

    def test_prompt_tells_the_model_not_to_add_a_redirect_sentence(self):
        # A live-confirmed second failure mode: even after the model
        # stopped answering the non-menu part itself, it started adding a
        # sentence like "For the shopping list, ask the Procurement
        # Specialist" instead -- meta-commentary that isn't part of the
        # menu either.
        self.assertIn("SILENTLY", mda.SYSTEM_PROMPT)
        self.assertIn("no meta-commentary", mda.SYSTEM_PROMPT)

    def test_prompt_does_not_hand_the_model_a_concrete_dish_to_anchor_on(self):
        # Confirmed live: the prompt's own illustrative example ("Grilled
        # chicken Caesar salad with garlic bread," used to show what
        # "enough detail" looks like) became the model's own go-to
        # default dish. Naming ANY concrete dish in the prompt -- even as
        # something to avoid defaulting to, which is how turkey sandwich/
        # pasta primavera were previously called out -- risks teaching
        # the model to reach for it, so the whole instruction (both the
        # detail-level example and the anti-default guidance) now
        # describes the PATTERN abstractly instead of naming any specific
        # dish.
        self.assertNotIn("Caesar", mda.SYSTEM_PROMPT)
        self.assertNotIn("turkey sandwich", mda.SYSTEM_PROMPT.lower())
        self.assertNotIn("pasta primavera", mda.SYSTEM_PROMPT.lower())
        self.assertIn("protein", mda.SYSTEM_PROMPT.lower())


class RequestedDayCountTests(unittest.TestCase):
    def test_hyphenated_word_form(self):
        self.assertEqual(mda._requested_day_count("Design a five-day lunch menu for next week."), 5)

    def test_hyphenated_digit_form(self):
        self.assertEqual(mda._requested_day_count("Plan a 5-day lunch menu for next week."), 5)

    def test_spaced_word_form(self):
        self.assertEqual(mda._requested_day_count("Design a five day lunch menu."), 5)

    def test_spaced_digit_form(self):
        self.assertEqual(mda._requested_day_count("Design a 3 day lunch menu."), 3)

    def test_no_day_count_mentioned(self):
        self.assertIsNone(mda._requested_day_count("Design a Mediterranean-themed lunch menu for next week."))

    def test_single_day_is_still_parsed(self):
        self.assertEqual(mda._requested_day_count("Design a one-day menu for a special event."), 1)


class ImagePromptTests(unittest.TestCase):
    def test_strips_leading_day_label(self):
        prompt = mda._image_prompt("Day 1: Chicken curry.")
        self.assertIn("Chicken curry.", prompt)
        self.assertNotIn("Day 1:", prompt)

    def test_day_label_match_is_case_insensitive(self):
        prompt = mda._image_prompt("day 3: Lentil soup")
        self.assertIn("Lentil soup", prompt)
        self.assertNotIn("day 3", prompt)

    def test_keeps_every_item_the_line_lists(self):
        # A line often lists a main dish plus separate sides -- all of it
        # is kept in the prompt (see the anti-duplication instruction
        # test below for why simply handing the model everything is safe
        # here, unlike an earlier version of this prompt that dropped
        # everything but the main dish to work around a duplication bug).
        prompt = mda._image_prompt(
            "Day 4: Chicken and chorizo tacos with avocado salsa, grilled vegetable tacos, corn tortillas."
        )
        self.assertIn("Chicken and chorizo tacos with avocado salsa", prompt)
        self.assertIn("grilled vegetable tacos", prompt)
        self.assertIn("corn tortillas", prompt)

    def test_instructs_one_cohesive_plate_with_nothing_duplicated(self):
        # Confirmed live: handing the model a multi-item line with no
        # further guidance produced visibly DUPLICATED food (e.g. two
        # near-identical sets of tacos) instead of one coherent plate.
        # This instruction fixes the actual problem (composition) rather
        # than working around it by dropping information -- confirmed
        # live to compose a 3-item line onto one plate with each element
        # appearing exactly once.
        prompt = mda._image_prompt("Day 1: Chicken curry, rice, cucumber salad.")
        self.assertIn("one cohesive", prompt.lower())
        self.assertIn("do not repeat or duplicate", prompt.lower())

    def test_no_day_label_is_used_as_is(self):
        prompt = mda._image_prompt("Grilled chicken Caesar salad with garlic bread.")
        self.assertIn("Grilled chicken Caesar salad with garlic bread.", prompt)

    def test_no_comma_line_is_unaffected(self):
        prompt = mda._image_prompt("Day 1: Lentil soup")
        self.assertIn("Lentil soup", prompt)

    def test_savoury_line_is_plated_as_a_lunch_plate(self):
        prompt = mda._image_prompt("Day 1: Chicken curry, rice, cucumber salad.")
        self.assertIn("cafeteria lunch plate", prompt)
        self.assertNotIn("dessert", prompt.lower())

    def test_dessert_line_is_plated_as_a_dessert(self):
        for line in [
            "Day 2: Lemon tart with raspberry coulis",
            "Dark chocolate mousse",
            "Day 5: Apple cobbler with vanilla ice cream",
            "Sticky toffee pudding",
        ]:
            prompt = mda._image_prompt(line)
            self.assertIn("cafeteria dessert serving", prompt, line)
            self.assertIn("dessert plate or bowl", prompt, line)
            self.assertNotIn("lunch plate", prompt, line)
            # anti-duplication instruction still present
            self.assertIn("do not repeat or duplicate", prompt.lower(), line)


class GenerateMealImagesTests(unittest.TestCase):
    """Parallel, honest (generated-or-empty) AI illustration per line of a
    Menu Designer response -- llm_utils.generate_image_sync already
    degrades to "" on any failure or missing config, so this just needs
    to fan that call out across lines and preserve order."""

    def test_empty_line_list_makes_no_calls(self):
        with patch.object(mda.llm_utils, "generate_image_sync") as gen:
            result = mda._generate_meal_images([])

        gen.assert_not_called()
        self.assertEqual(result, [])

    def test_one_call_per_line_with_its_own_prompt(self):
        with patch.object(mda.llm_utils, "generate_image_sync", side_effect=lambda p: f"data:image/png;base64,{p[:5]}") as gen:
            result = mda._generate_meal_images(["Day 1: Chicken curry.", "Day 2: Lentil soup."])

        self.assertEqual(gen.call_count, 2)
        called_prompts = {call.args[0] for call in gen.call_args_list}
        self.assertTrue(any("Chicken curry." in p for p in called_prompts))
        self.assertTrue(any("Lentil soup." in p for p in called_prompts))
        self.assertEqual(len(result), 2)

    def test_generation_failure_yields_empty_string_not_a_placeholder(self):
        with patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            result = mda._generate_meal_images(["Day 1: Some invented fusion dish."])

        self.assertEqual(result, [""])

    def test_results_align_with_input_order(self):
        def fake_generate(prompt):
            return "data:image/png;base64,AAA" if "Lentil soup" in prompt else ""

        with patch.object(mda.llm_utils, "generate_image_sync", side_effect=fake_generate):
            result = mda._generate_meal_images(["Day 1: Mystery dish.", "Day 2: Lentil soup."])

        self.assertEqual(result, ["", "data:image/png;base64,AAA"])


class BuildMenuHtmlTests(unittest.TestCase):
    def test_multi_line_becomes_an_html_list(self):
        html = mda._build_menu_html("Day 1: Chicken curry.\nDay 2: Lentil soup.", ["", ""])
        self.assertEqual(html, "<ul><li>Day 1: Chicken curry.</li><li>Day 2: Lentil soup.</li></ul>")

    def test_multi_line_with_an_image_embeds_it_in_its_own_item(self):
        html = mda._build_menu_html(
            "Day 1: Chicken curry.\nDay 2: Lentil soup.",
            ["data:image/png;base64,AAA", ""],
        )
        self.assertIn('<li>Day 1: Chicken curry.<br><img src="data:image/png;base64,AAA"', html)
        self.assertIn("<li>Day 2: Lentil soup.</li>", html)

    def test_single_line_with_no_image_produces_no_html(self):
        html = mda._build_menu_html("Grilled chicken Caesar salad with garlic bread.", [""])
        self.assertEqual(html, "")

    def test_single_line_with_an_image_produces_a_paragraph_with_it(self):
        html = mda._build_menu_html(
            "Grilled chicken Caesar salad with garlic bread.",
            ["data:image/png;base64,AAA"],
        )
        self.assertEqual(
            html,
            '<p>Grilled chicken Caesar salad with garlic bread.<br>'
            '<img src="data:image/png;base64,AAA" alt="Grilled chicken Caesar salad with garlic bread." '
            'style="max-width:200px;border-radius:6px;margin-top:4px"></p>',
        )

    def test_empty_text_produces_no_html(self):
        self.assertEqual(mda._build_menu_html("", []), "")

    def test_html_escapes_special_characters(self):
        html = mda._build_menu_html("Day 1: Mac & cheese.\nDay 2: <special> dish.", ["", ""])
        self.assertIn("Mac &amp; cheese.", html)
        self.assertIn("&lt;special&gt; dish.", html)


class ProcessUtteranceBudgetHintTests(unittest.TestCase):
    def _make_agent(self, max_words):
        agent = mda.MenuDesignerAgent()
        agent._current_max_words = max_words
        return agent

    def test_multi_day_request_gets_a_computed_per_day_budget_hint(self):
        agent = self._make_agent(125)
        with patch.object(mda.llm_utils, "chat_sync", return_value="ok") as chat_sync, \
                patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            agent.process_utterance("Design a five-day lunch menu for next week.")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("This request covers 5 days", user_message)
        self.assertIn("25 words", user_message)  # 125 // 5

    def test_single_day_request_gets_no_budget_hint(self):
        agent = self._make_agent(125)
        with patch.object(mda.llm_utils, "chat_sync", return_value="ok") as chat_sync, \
                patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            agent.process_utterance("Design a Mediterranean-themed lunch menu for next week.")

        user_message = chat_sync.call_args[0][1]
        self.assertNotIn("This request covers", user_message)

    def test_per_day_budget_never_drops_below_the_floor(self):
        # A tiny overall budget for many days must not compute down to a
        # useless (or zero) per-day word count.
        agent = self._make_agent(20)
        with patch.object(mda.llm_utils, "chat_sync", return_value="ok") as chat_sync, \
                patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            agent.process_utterance("Design a seven-day lunch menu.")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("15 words", user_message)  # max(15, 20 // 7) == 15


class ProcessUtteranceHtmlListTests(unittest.TestCase):
    """A multi-day response is already one line per day (see the budget
    hint above), so it should also render as a real HTML list in the
    browser's Analysis report popup; a single-day response with no image
    generated is plain prose and should not be listified."""

    def _make_agent(self, max_words=125):
        agent = mda.MenuDesignerAgent()
        agent._current_max_words = max_words
        return agent

    def test_multi_day_response_becomes_an_html_list(self):
        agent = self._make_agent()
        with patch.object(mda.llm_utils, "chat_sync", return_value="Day 1: Chicken curry.\nDay 2: Lentil soup."), \
                patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            result = agent.process_utterance("Design a five-day lunch menu for next week.")

        self.assertEqual(result["text"], "Day 1: Chicken curry.\nDay 2: Lentil soup.")
        self.assertEqual(result["html"], "<ul><li>Day 1: Chicken curry.</li><li>Day 2: Lentil soup.</li></ul>")

    def test_single_day_response_has_no_html_list(self):
        agent = self._make_agent()
        with patch.object(mda.llm_utils, "chat_sync", return_value="Grilled chicken Caesar salad with garlic bread."), \
                patch.object(mda.llm_utils, "generate_image_sync", return_value=""):
            result = agent.process_utterance("Design a Mediterranean-themed lunch menu for next week.")

        self.assertEqual(result["html"], "")

    def test_multi_day_response_with_a_generated_image_embeds_it(self):
        agent = self._make_agent()

        def fake_generate(prompt):
            return "data:image/png;base64,AAA" if "Chicken curry" in prompt else ""

        with patch.object(mda.llm_utils, "chat_sync", return_value="Day 1: Chicken curry.\nDay 2: Lentil soup."), \
                patch.object(mda.llm_utils, "generate_image_sync", side_effect=fake_generate):
            result = agent.process_utterance("Design a five-day lunch menu for next week.")

        self.assertIn('<img src="data:image/png;base64,AAA"', result["html"])
        self.assertIn("<li>Day 2: Lentil soup.</li>", result["html"])


if __name__ == "__main__":
    unittest.main()
