import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.menu_optimization_specialist import menu_optimization_agent as moa
from agents.menu_optimization_specialist.menu_optimization_agent import MenuOptimizationAgent


class OnObservedUtteranceTests(unittest.TestCase):
    """The Menu Optimization Specialist watches Pass-Through broadcast
    traffic for the Menu Designer's proposed menu, keyed per-conversation,
    so it evaluates the ACTUAL menu rather than the raw planning request
    text it happens to be asked with."""

    def test_saves_text_from_the_menu_designer(self):
        agent = MenuOptimizationAgent()

        agent.on_observed_utterance("conv-1", moa._MENU_DESIGNER_SERVICE_URL, "Day 1: Chicken Curry.")

        self.assertEqual(agent._observed_menus, {"conv-1": "Day 1: Chicken Curry."})

    def test_matches_the_menu_designer_uri_case_and_slash_insensitively(self):
        agent = MenuOptimizationAgent()
        loud_uri = moa._MENU_DESIGNER_SERVICE_URL.upper().rstrip("/")

        agent.on_observed_utterance("conv-1", loud_uri, "Day 1: Chicken Curry.")

        self.assertEqual(agent._observed_menus, {"conv-1": "Day 1: Chicken Curry."})

    def test_ignores_utterances_from_other_speakers(self):
        agent = MenuOptimizationAgent()

        agent.on_observed_utterance("conv-1", "http://127.0.0.1:8303/", "some recipe commentary")

        self.assertEqual(agent._observed_menus, {})

    def test_a_later_menu_replaces_the_earlier_one_for_the_same_conversation(self):
        agent = MenuOptimizationAgent()

        agent.on_observed_utterance("conv-1", moa._MENU_DESIGNER_SERVICE_URL, "first draft menu")
        agent.on_observed_utterance("conv-1", moa._MENU_DESIGNER_SERVICE_URL, "revised menu")

        self.assertEqual(agent._observed_menus, {"conv-1": "revised menu"})

    def test_different_conversations_are_kept_separate(self):
        agent = MenuOptimizationAgent()

        agent.on_observed_utterance("conv-1", moa._MENU_DESIGNER_SERVICE_URL, "menu for conv 1")
        agent.on_observed_utterance("conv-2", moa._MENU_DESIGNER_SERVICE_URL, "menu for conv 2")

        self.assertEqual(agent._observed_menus, {"conv-1": "menu for conv 1", "conv-2": "menu for conv 2"})


class ProcessUtteranceTests(unittest.TestCase):
    def _make_agent(self, conv_id="conv-1", saved_menu=""):
        agent = MenuOptimizationAgent()
        agent._current_conv_id = conv_id
        if saved_menu:
            agent._observed_menus[conv_id] = saved_menu
        return agent

    def test_uses_the_saved_menu_when_available_not_the_raw_request_text(self):
        agent = self._make_agent(saved_menu="Day 1: Chicken Curry. Day 2: Lentil Soup.")
        with patch.object(moa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Plan a two-day lunch menu for 300 people with a budget of $6 per meal.")

        self.assertEqual(chat_sync.call_args[0][0], moa.SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("Day 1: Chicken Curry. Day 2: Lentil Soup.", user_message)
        self.assertNotIn("Plan a two-day lunch menu", user_message)

    def test_falls_back_to_the_raw_request_text_when_no_menu_was_observed(self):
        agent = self._make_agent(saved_menu="")
        with patch.object(moa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Day 1: Chicken Curry. Day 2: Lentil Soup.")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Day 1: Chicken Curry. Day 2: Lentil Soup.", user_message)

    def test_prior_conversation_history_is_included_when_present(self):
        agent = self._make_agent(saved_menu="Day 1: Chicken Curry.")
        agent._current_history_text = "User: keep it under $6 a meal"
        with patch.object(moa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Plan a menu.")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Prior conversation so far:\nUser: keep it under $6 a meal", user_message)

    def test_no_history_section_when_nothing_has_been_recorded_yet(self):
        agent = self._make_agent(saved_menu="")
        with patch.object(moa.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Day 1: Chicken Curry.")

        user_message = chat_sync.call_args[0][1]
        self.assertNotIn("Prior conversation so far:", user_message)

    def test_multi_line_response_keeps_the_opening_sentence_out_of_the_bullet_list(self):
        agent = self._make_agent(saved_menu="Day 1: Chicken Curry. Day 2: Beef Stew.")
        raw_reply = (
            "Here are cost and waste-reduction recommendations:\n"
            "Reuse the diced onions from Day 1 in Day 2's stew base.\n"
            "Swap the imported cheese for a domestic equivalent to cut cost."
        )
        with patch.object(moa.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent.process_utterance("Optimize this menu.")

        self.assertEqual(
            result["html"],
            "<p>Here are cost and waste-reduction recommendations:</p>"
            "<ul><li>Reuse the diced onions from Day 1 in Day 2&#x27;s stew base.</li>"
            "<li>Swap the imported cheese for a domestic equivalent to cut cost.</li></ul>",
        )


if __name__ == "__main__":
    unittest.main()
