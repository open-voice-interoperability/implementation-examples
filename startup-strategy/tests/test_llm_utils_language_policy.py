import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_utils import _build_chat_messages, _with_language_response_policy, LANGUAGE_RESPONSE_POLICY


class LanguagePolicyTests(unittest.TestCase):
    def test_policy_instructs_the_model_to_mirror_the_requester_language(self):
        system_prompt = "You are a helpful specialist."

        prompt = _with_language_response_policy(system_prompt)

        self.assertIn(LANGUAGE_RESPONSE_POLICY, prompt)
        self.assertIn("same natural language", prompt.lower())

    def test_policy_tells_the_model_to_ignore_embedded_reference_data(self):
        # Regression guard: the old regex detector misfired on ordinary English
        # business text (e.g. "per seat", "die", "met") because it scanned the
        # whole combined prompt, including injected research/filing snippets.
        # The model-driven policy must explicitly steer around that.
        prompt = _with_language_response_policy("You are a helpful specialist.")

        self.assertIn("reference data", prompt.lower())

    def test_policy_is_not_duplicated_when_already_present(self):
        system_prompt = f"You are a helpful specialist.\n\n{LANGUAGE_RESPONSE_POLICY}"

        prompt = _with_language_response_policy(system_prompt)

        self.assertEqual(prompt.count(LANGUAGE_RESPONSE_POLICY), 1)

    def test_chat_messages_embed_language_policy_in_system_turn_only(self):
        system_prompt = "You are a helpful specialist."
        user_message = "Please analyze this startup idea. Pricing is $10 per seat."

        messages, user_turn = _build_chat_messages(system_prompt, user_message)

        self.assertIn(LANGUAGE_RESPONSE_POLICY, messages[0]["content"])
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")

        # The user's own text must pass through unmodified: no language
        # instruction injected into it, and business text containing common
        # short words (e.g. "per") must not be altered or trigger anything.
        self.assertEqual(user_turn, user_message)
        self.assertEqual(messages[1]["content"], user_message)


if __name__ == "__main__":
    unittest.main()
