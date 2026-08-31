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


def conversant_record(agent_key):
    """Flat {speakerUri, serviceUrl} shape -- what _conversant_records()
    already produces, and what _decide_for_human_utterance/
    _decide_for_specialist_reply take directly."""
    info = convener.AGENTS[agent_key]
    return {"speakerUri": f"tag:{agent_key}", "serviceUrl": info["url"]}


def wrapped_conversant(agent_key):
    """The raw conversation.conversants wire shape (identification-wrapped)
    that _conversant_records() itself parses -- for tests that go through
    _decide_delegated_utterance, which calls _conversant_records internally."""
    record = conversant_record(agent_key)
    return {"identification": record}


ALL_RECORDS = [conversant_record(k) for k in convener.FULL_ANALYSIS_SEQUENCE]
ALL_WRAPPED_RECORDS = [wrapped_conversant(k) for k in convener.FULL_ANALYSIS_SEQUENCE]


class DecideForHumanUtteranceTests(unittest.TestCase):
    def test_invite_only_returns_invite_events_for_not_yet_invited(self):
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, [])

        self.assertEqual(len(events), len(convener.FULL_ANALYSIS_SEQUENCE))
        self.assertTrue(all(isinstance(e, convener.InviteEvent) for e in events))

    def test_invite_only_skips_already_invited(self):
        already_invited = [conversant_record("market")]
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, already_invited)

        self.assertEqual(len(events), len(convener.FULL_ANALYSIS_SEQUENCE) - 1)

    def test_invite_only_when_everyone_already_invited_returns_status_text(self):
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, ALL_RECORDS)

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.UtteranceEvent)

    def test_ask_specific_agent_grants_and_asks_privately(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "risk", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("risk identifier, what about compliance?", "", 50, ALL_RECORDS)

        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["risk"]["url"])
        self.assertIsInstance(events[1], convener.UtteranceEvent)
        self.assertTrue(events[1].to.private)
        self.assertEqual(events[1].to.serviceUrl, convener.AGENTS["risk"]["url"])

    def test_round_robin_grants_only_the_first_agent(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["market", "risk", "funding"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("evaluate this idea", "round_robin", 50, ALL_RECORDS)

        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["market"]["url"])
        self.assertIsInstance(events[1], convener.UtteranceEvent)
        self.assertTrue(events[1].to.private)

    def test_full_sweep_grants_everyone_and_sends_one_public_utterance(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["market", "risk", "funding"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("evaluate this idea", "", 50, ALL_RECORDS)

        grant_events = [e for e in events if isinstance(e, convener.GrantFloorEvent)]
        utterance_events = [e for e in events if isinstance(e, convener.UtteranceEvent)]
        self.assertEqual(len(grant_events), 3)
        self.assertEqual({e.to.serviceUrl for e in grant_events}, {convener.AGENTS[k]["url"] for k in ("market", "risk", "funding")})
        self.assertEqual(len(utterance_events), 1)
        # Public: no `to` at all (Pass-Through to every conversant, each
        # agent's own local floor gate filters out the ungranted ones).
        self.assertIsNone(getattr(utterance_events[0], "to", None))

    def test_max_words_appends_instruction_to_question_text(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "market", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("what's the TAM?", "", 125, ALL_RECORDS)

        utterance_event = events[1]
        text = utterance_event.dialogEvent.features["text"].tokens[0].value
        self.assertIn("[Write approximately 125 words.]", text)

    def test_default_max_words_does_not_append_instruction(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "market", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("what's the TAM?", "", convener.MAX_RESPONSE_WORDS, ALL_RECORDS)

        utterance_event = events[1]
        text = utterance_event.dialogEvent.features["text"].tokens[0].value
        self.assertNotIn("[Write approximately", text)


class DecideForSpecialistReplyTests(unittest.TestCase):
    def test_round_robin_advances_to_next_agent(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["market", "risk", "funding"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:market", "round_robin", "evaluate this idea", 50, ["tag:market"], ALL_RECORDS
            )

        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:market")
        self.assertIsInstance(events[1], convener.GrantFloorEvent)
        self.assertEqual(events[1].to.serviceUrl, convener.AGENTS["risk"]["url"])
        self.assertIsInstance(events[2], convener.UtteranceEvent)

    def test_round_robin_sequence_complete_only_revokes(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["market", "risk"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:risk", "round_robin", "evaluate this idea", 50, ["tag:market", "tag:risk"], ALL_RECORDS
            )

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:risk")

    def test_full_sweep_only_revokes_no_reclassification(self):
        with patch.object(convener, "classify_utterance") as mocked_classify:
            events = convener._decide_for_specialist_reply(
                "tag:market", "", "evaluate this idea", 50, [], ALL_RECORDS
            )

        mocked_classify.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)

    def test_missing_question_text_only_revokes(self):
        with patch.object(convener, "classify_utterance") as mocked_classify:
            events = convener._decide_for_specialist_reply(
                "tag:market", "round_robin", "", 50, [], ALL_RECORDS
            )

        mocked_classify.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)


class ClassifySpeakerTests(unittest.TestCase):
    def test_recognizes_a_known_specialist(self):
        self.assertEqual(convener._classify_speaker("tag:market", ALL_RECORDS), "specialist")

    def test_treats_unknown_speaker_as_human(self):
        self.assertEqual(convener._classify_speaker("tag:some-human-client", ALL_RECORDS), "human")


class DecideDelegatedUtteranceDispatchTests(unittest.TestCase):
    """End-to-end through _decide_delegated_utterance using real openfloor
    Event/Parameters objects, matching what handle_envelope_json actually
    hands it (not hand-built plain dicts)."""

    def _utterance_event(self, speaker_uri, text, round_question, round_routing_mode="", round_turn_order=None):
        dialog = convener.DialogEvent(speakerUri=speaker_uri)
        text_feature = convener.TextFeature()
        text_feature.tokens = [convener.Token(value=text)]
        dialog.features = {"text": text_feature}
        params = convener.Parameters({
            "roundHistory": [],
            "roundTurnOrder": round_turn_order or [],
            "roundQuestion": round_question,
            "roundRoutingMode": round_routing_mode,
            "roundMaxWords": 50,
        })
        return convener.UtteranceEvent(dialogEvent=dialog, parameters=params)

    def test_fresh_human_utterance_routes_to_human_decision(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "market", "agent_keys": []}
        event = self._utterance_event("tag:human", "ignored -- roundQuestion wins", "what's the TAM?")
        with patch.object(convener, "classify_utterance", return_value=classification) as mocked:
            events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})

        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], "what's the TAM?")
        self.assertIsInstance(events[0], convener.GrantFloorEvent)

    def test_specialist_reply_routes_to_specialist_decision(self):
        event = self._utterance_event("tag:market", "TAM is $1B", "what's the TAM?", round_routing_mode="")
        events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:market")

    def test_empty_round_question_yields_no_decision(self):
        event = self._utterance_event("tag:human", "hi", "")
        events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
