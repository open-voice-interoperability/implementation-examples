import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONVENER_SERVICE = ROOT / "convener_service"
if str(CONVENER_SERVICE) not in sys.path:
    sys.path.insert(0, str(CONVENER_SERVICE))

import convener


class ClassifyUtteranceLlmTests(unittest.TestCase):
    """Inputs here are chosen to NOT trip the regex fast-path (see
    ClassifyUtteranceFastPathTests below), so they actually exercise the
    LLM call and JSON parsing."""

    def setUp(self):
        # _classify_via_llm is memoized by exact utterance text; clear
        # between tests so one test's mocked response can't leak into
        # another test reusing the same input string.
        convener._classify_via_llm.cache_clear()

    def test_invite_only_action_parsed(self):
        raw = '{"action": "invite_only", "addressed_agent_key": null, "agent_keys": []}'
        text = "Please bring the full team into this conversation so we can move forward."
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = convener.classify_utterance(text)

        chat_sync.assert_called_once()
        self.assertEqual(result, {"action": "invite_only", "addressed_agent_key": None, "agent_keys": []})

    def test_invite_only_with_team_scope_parsed(self):
        # Deliberately avoids the regex fast-path's invite trigger words
        # ("invite"/"bring in"/"add") so this exercises the LLM call.
        raw = '{"action": "invite_only", "addressed_agent_key": null, "agent_keys": ["inventory", "procurement", "shopping_list"]}'
        text = "We should loop in the folks who handle sourcing and logistics for this conversation."
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = convener.classify_utterance(text)

        chat_sync.assert_called_once()
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], convener.SUPPLY_CHAIN_AGENTS)

    def test_ask_specific_agent_action_parsed(self):
        raw = '{"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []}'
        text = "What does the procurement person think about sourcing this?"
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = convener.classify_utterance(text)

        chat_sync.assert_called_once()
        self.assertEqual(
            result,
            {"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []},
        )

    def test_ask_agents_action_parsed(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition", "recipe_portion"]}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            result = convener.classify_utterance("A grilled chicken bowl with quinoa.")

        self.assertEqual(
            result,
            {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "recipe_portion"]},
        )

    def test_response_wrapped_in_extra_text_still_parses(self):
        raw = 'Sure, here you go:\n{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}\nthanks!'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            result = convener.classify_utterance("What about the calories?")

        self.assertEqual(result["action"], "ask_agents")
        self.assertEqual(result["agent_keys"], ["nutrition"])

    def test_hallucinated_agent_key_is_filtered_out(self):
        raw = '{"action": "ask_specific_agent", "addressed_agent_key": "not_a_real_agent", "agent_keys": []}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            result = convener.classify_utterance("some question")

        # No valid addressed agent -> downgraded to ask_agents with the full sequence.
        self.assertEqual(result["action"], "ask_agents")
        self.assertIsNone(result["addressed_agent_key"])
        self.assertEqual(result["agent_keys"], convener.FULL_ANALYSIS_SEQUENCE)

    def test_hallucinated_agent_keys_in_list_are_filtered(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition", "not_real", "procurement"]}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            result = convener.classify_utterance("some question")

        self.assertEqual(result["agent_keys"], ["nutrition", "procurement"])

    def test_ask_agents_with_empty_keys_defaults_to_full_sequence(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": []}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            result = convener.classify_utterance("some question")

        self.assertEqual(result["agent_keys"], convener.FULL_ANALYSIS_SEQUENCE)

    def test_malformed_json_falls_back_to_regex(self):
        text = "Please evaluate this weekly cafeteria menu for cost and variety."
        with patch.object(convener.llm_utils, "chat_sync", return_value="not json at all"):
            with patch.object(
                convener, "_classify_utterance_fallback", wraps=convener._classify_utterance_fallback
            ) as fallback:
                result = convener.classify_utterance(text)

        fallback.assert_called_once_with(text)
        self.assertEqual(result["action"], "ask_agents")
        self.assertEqual(result["agent_keys"], convener.FULL_ANALYSIS_SEQUENCE)

    def test_hallucinated_invite_only_with_no_invite_verb_falls_back_to_regex(self):
        # Regression test: a small/fast classifier model can misread a
        # message that merely OPENS with a greeting like "Welcome,
        # everyone..." as an instruction to invite everyone, even though the
        # rest is a real planning question with no invite verb anywhere
        # (confirmed via live testing -- this exact phrasing produced a
        # dead-end "already invited" reply instead of real analysis).
        text = (
            "Welcome, everyone. Our objective is to produce a five-day lunch menu "
            "for next week for the corporate cafeteria and a corresponding food "
            "order with estimated costs. we are planning for 450 lunches per day"
        )
        raw = '{"action": "invite_only", "addressed_agent_key": null, "agent_keys": []}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            with patch.object(
                convener, "_classify_utterance_fallback", wraps=convener._classify_utterance_fallback
            ) as fallback:
                result = convener.classify_utterance(text)

        fallback.assert_called_once_with(text)
        self.assertEqual(result["action"], "ask_agents")
        self.assertEqual(result["agent_keys"], convener.FULL_ANALYSIS_SEQUENCE)

    def test_genuine_invite_only_phrased_differently_is_still_trusted(self):
        # The sanity check must not reject a real invite_only classification
        # -- only one too long/multi-sentence to plausibly be "only" an
        # invite. Phrased so it skips the regex fast-path entirely (no
        # "invite"/"bring in"/"add" verb) -- this is exactly the case the
        # LLM classifier exists for: phrasing regex alone would miss.
        raw = '{"action": "invite_only", "addressed_agent_key": null, "agent_keys": []}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = convener.classify_utterance("Let's get the full roster of specialists in here.")

        chat_sync.assert_called_once()
        self.assertEqual(result["action"], "invite_only")

    def test_invite_only_length_threshold_is_word_or_sentence_based(self):
        # Direct unit coverage for the heuristic itself, independent of the
        # LLM plumbing above.
        self.assertFalse(convener._looks_like_more_than_an_invite("invite your specialists"))
        self.assertFalse(convener._looks_like_more_than_an_invite("Let's get the full roster of specialists in here."))
        self.assertTrue(convener._looks_like_more_than_an_invite(
            "Welcome, everyone. Our objective is to produce a five-day lunch menu "
            "for next week for the corporate cafeteria and a corresponding food "
            "order with estimated costs. we are planning for 450 lunches per day"
        ))
        # A single long run-on sentence (no terminal punctuation triggering
        # the sentence-count branch) should still trip the word-count branch.
        self.assertTrue(convener._looks_like_more_than_an_invite(
            "invite the whole team right now because we urgently need everyone "
            "to weigh in on this before the end of the day today please"
        ))

    def test_invalid_action_value_falls_back_to_regex(self):
        text = "Please evaluate this weekly cafeteria menu for cost and variety."
        raw = '{"action": "do_something_weird", "addressed_agent_key": null, "agent_keys": []}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            with patch.object(
                convener, "_classify_utterance_fallback", wraps=convener._classify_utterance_fallback
            ) as fallback:
                result = convener.classify_utterance(text)

        fallback.assert_called_once_with(text)
        self.assertEqual(result["action"], "ask_agents")

    def test_llm_exception_falls_back_to_regex(self):
        with patch.object(convener.llm_utils, "chat_sync", side_effect=RuntimeError("network down")):
            with patch.object(
                convener, "_classify_utterance_fallback", wraps=convener._classify_utterance_fallback
            ) as fallback:
                result = convener.classify_utterance("Please evaluate this weekly cafeteria menu.")

        fallback.assert_called_once_with("Please evaluate this weekly cafeteria menu.")
        self.assertEqual(result["action"], "ask_agents")
        self.assertEqual(result["agent_keys"], convener.FULL_ANALYSIS_SEQUENCE)


class ClassifyUtteranceFastPathTests(unittest.TestCase):
    """Protocol-layer consistency: a meta-instruction or direct address must
    be able to interrupt a round regardless of LLM availability/latency, and
    must never pay for an LLM round-trip to do so."""

    def setUp(self):
        convener._classify_via_llm.cache_clear()

    def test_invite_meta_instruction_skips_llm(self):
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("convener, invite your specialists")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "invite_only")

    def test_invite_team_scope_skips_llm(self):
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("invite the menu planning team")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], convener.MENU_PLANNING_AGENTS)

    def test_invite_single_specialist_scope_skips_llm(self):
        # Naming exactly one specialist (not a team, not "everyone") must
        # invite only that specialist -- confirmed live this previously
        # invited all 9 instead.
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("invite the menu designer")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], ["menu_designer"])

    def test_invite_shopping_list_specialist_scope_skips_llm(self):
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("invite the shopping list specialist")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], ["shopping_list"])

    def test_invite_two_named_specialists_falls_back_to_everyone(self):
        # Naming more than one specialist is ambiguous scope -- no single-
        # specialist match applies, and there's no team phrase either, so
        # this still falls through to "invite everyone not yet invited"
        # (unchanged pre-existing behavior, not a new capability).
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("invite the menu designer and the nutrition specialist")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], [])

    def test_direct_address_skips_llm(self):
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance("Procurement Specialist, what about pricing?")

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "ask_specific_agent")
        self.assertEqual(result["addressed_agent_key"], "procurement")

    def test_round_robin_roster_reused_without_llm_call(self):
        # Continuing round-robin turn: a roster is already invited and the
        # message is a plain follow-up (no meta-instruction, no direct
        # address) -- the LLM's "which agents" answer would be discarded in
        # favor of the roster anyway, so it must not be called at all.
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance(
                "What about sodium content?", round_robin_roster=["nutrition", "recipe_portion"]
            )

        chat_sync.assert_not_called()
        self.assertEqual(
            result,
            {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "recipe_portion"]},
        )

    def test_direct_address_overrides_roster_without_llm_call(self):
        # A direct address mid-round must still be able to interrupt the
        # round -- the roster hint must not blindly win over it.
        with patch.object(convener.llm_utils, "chat_sync") as chat_sync:
            result = convener.classify_utterance(
                "Procurement Specialist, what about pricing?", round_robin_roster=["nutrition", "recipe_portion"]
            )

        chat_sync.assert_not_called()
        self.assertEqual(result["action"], "ask_specific_agent")
        self.assertEqual(result["addressed_agent_key"], "procurement")

    def test_empty_roster_still_calls_llm(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            result = convener.classify_utterance("A grilled chicken bowl with quinoa.", round_robin_roster=[])

        chat_sync.assert_called_once()
        self.assertEqual(result["agent_keys"], ["nutrition"])


class ClassifyUtteranceLatencyTests(unittest.TestCase):
    """Covers the two follow-on latency optimizations: a short explicit
    timeout on the classifier's LLM call (distinct from the longer default
    used for full specialist analysis), and memoizing identical repeat
    utterances so a retry can't pay for a second round-trip or land on a
    different classification than the first."""

    def setUp(self):
        convener._classify_via_llm.cache_clear()

    def test_classifier_call_uses_short_explicit_timeout(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            convener.classify_utterance("A grilled chicken bowl with quinoa.")

        _, kwargs = chat_sync.call_args
        self.assertEqual(kwargs.get("timeout"), convener._CLASSIFIER_TIMEOUT_SECONDS)
        self.assertLess(convener._CLASSIFIER_TIMEOUT_SECONDS, 60)

    def test_classifier_call_uses_classifier_specific_models(self):
        # The classifier should opt into the smaller/faster models
        # (llm_utils.CLASSIFIER_LLM_MODEL / CLASSIFIER_OLLAMA_MODEL), not
        # whatever model full specialist analysis calls use.
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}'
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            convener.classify_utterance("A grilled chicken bowl with quinoa.")

        _, kwargs = chat_sync.call_args
        self.assertEqual(kwargs.get("openai_model"), convener.llm_utils.CLASSIFIER_LLM_MODEL)
        self.assertEqual(kwargs.get("ollama_model"), convener.llm_utils.CLASSIFIER_OLLAMA_MODEL)

    def test_identical_utterance_is_memoized_not_re_sent_to_llm(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}'
        text = "A grilled chicken bowl with quinoa."
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw) as chat_sync:
            first = convener.classify_utterance(text)
            second = convener.classify_utterance(text)

        chat_sync.assert_called_once()
        self.assertEqual(first, second)

    def test_memoized_result_is_not_shared_mutable_state(self):
        raw = '{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["nutrition"]}'
        text = "A grilled chicken bowl with quinoa."
        with patch.object(convener.llm_utils, "chat_sync", return_value=raw):
            first = convener.classify_utterance(text)
            first["agent_keys"].append("mutated")
            second = convener.classify_utterance(text)

        self.assertEqual(second["agent_keys"], ["nutrition"])

    def test_failed_llm_call_is_not_cached(self):
        text = "A grilled chicken bowl with quinoa."
        with patch.object(convener.llm_utils, "chat_sync", side_effect=RuntimeError("down")) as chat_sync:
            convener.classify_utterance(text)
            convener.classify_utterance(text)

        # A failure must be retried on the next call, not stuck in the cache.
        self.assertEqual(chat_sync.call_count, 2)


class ClassifyUtteranceFallbackTests(unittest.TestCase):
    def test_fallback_detects_invite_only(self):
        result = convener._classify_utterance_fallback("convener, invite your specialists")
        self.assertEqual(result["action"], "invite_only")

    def test_fallback_detects_invite_only_with_team_scope(self):
        result = convener._classify_utterance_fallback("invite the supply chain team")
        self.assertEqual(result["action"], "invite_only")
        self.assertEqual(result["agent_keys"], convener.SUPPLY_CHAIN_AGENTS)

    def test_fallback_detects_addressed_agent(self):
        result = convener._classify_utterance_fallback("Procurement Specialist, what about pricing?")
        self.assertEqual(result["action"], "ask_specific_agent")
        self.assertEqual(result["addressed_agent_key"], "procurement")

    def test_fallback_defaults_to_ask_agents(self):
        result = convener._classify_utterance_fallback("A grilled chicken bowl with quinoa.")
        self.assertEqual(result["action"], "ask_agents")
        self.assertTrue(result["agent_keys"])


if __name__ == "__main__":
    unittest.main()
