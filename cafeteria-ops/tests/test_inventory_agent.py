import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.inventory_specialist import inventory_agent as ia
from agents.inventory_specialist.inventory_agent import InventoryAgent


class ProcessUtteranceTests(unittest.TestCase):
    """Inventory has no MCP data source and no bespoke on_observed_utterance
    override (unlike Procurement/Nutrition/etc) -- BaseStrategyAgent's
    automatic conversation-history recording (self._history_block()) is
    its ONLY source of grounding beyond the raw request text. Without it,
    live testing showed generic, one-size-fits-all advice regardless of
    what was actually asked."""

    def _make_agent(self):
        return InventoryAgent()

    def test_sends_the_system_prompt_and_request_text(self):
        agent = self._make_agent()
        with patch.object(ia.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("How should we handle stock for fresh basil?")

        self.assertEqual(chat_sync.call_args[0][0], ia.SYSTEM_PROMPT)
        user_message = chat_sync.call_args[0][1]
        self.assertIn("How should we handle stock for fresh basil?", user_message)

    def test_prior_conversation_history_is_included_when_present(self):
        agent = self._make_agent()
        agent._current_history_text = (
            "Menu Designer: Day 1: Chicken Curry.\n"
            "Recipe & Portion Specialist: chicken curry: 150g chicken breast, 50g yogurt, ..."
        )
        with patch.object(ia.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Assess stock risk for this week's menu.")

        user_message = chat_sync.call_args[0][1]
        self.assertIn("Prior conversation so far:", user_message)
        self.assertIn("Recipe & Portion Specialist: chicken curry: 150g chicken breast", user_message)

    def test_no_history_section_when_nothing_has_been_recorded_yet(self):
        agent = self._make_agent()
        with patch.object(ia.llm_utils, "chat_sync", return_value="ok") as chat_sync:
            agent.process_utterance("Assess stock risk for fresh basil.")

        user_message = chat_sync.call_args[0][1]
        self.assertNotIn("Prior conversation so far:", user_message)

    def test_returns_a_text_and_html_dict(self):
        agent = self._make_agent()
        with patch.object(ia.llm_utils, "chat_sync", return_value="Basil spoils fast; keep a tight par level."):
            result = agent.process_utterance("How should we handle stock for fresh basil?")

        self.assertEqual(result["text"], "Basil spoils fast; keep a tight par level.")
        self.assertEqual(result["html"], "")  # single-paragraph response, not a list

    def test_multi_line_response_keeps_the_opening_sentence_out_of_the_bullet_list(self):
        agent = self._make_agent()
        raw_reply = (
            "Here is the stock assessment for this week's menu:\n"
            "Chicken breast: par level 40lb, reorder every 2 days.\n"
            "Basil: par level 2lb, reorder daily."
        )
        with patch.object(ia.llm_utils, "chat_sync", return_value=raw_reply):
            result = agent.process_utterance("Assess stock risk for this week's menu.")

        self.assertEqual(
            result["html"],
            "<p>Here is the stock assessment for this week&#x27;s menu:</p>"
            "<ul><li>Chicken breast: par level 40lb, reorder every 2 days.</li>"
            "<li>Basil: par level 2lb, reorder daily.</li></ul>",
        )


if __name__ == "__main__":
    unittest.main()
