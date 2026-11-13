import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents import base_strategy_agent as bsa
from agents.base_strategy_agent import BaseStrategyAgent

HUMAN_URI = "openFloor://localhost:8090/CafeteriaOpsLineCheck"


class EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Specialist"
    AGENT_PORT = 8399
    AGENT_SYNOPSIS = "echoes"
    AGENT_KEYPHRASES = ["echo"]

    def process_utterance(self, user_text):
        return "answer: " + user_text


class PrivateRepliesTests(unittest.TestCase):
    """OFP 1.1.1 section 2.1: private utterances get private responses."""

    def setUp(self):
        self.agent = EchoAgent()
        self.agent._enforce_scope_gate = False
        self.me = {"speakerUri": self.agent.speakerUri, "serviceUrl": self.agent.serviceUrl}
        self._send([{"eventType": "grantFloor", "to": self.me}])

    def _send(self, events):
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "conv-private"},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": events,
        }}
        return json.loads(self.agent.handle_json_envelope(json.dumps(envelope)))["openFloor"].get("events") or []

    def _utterance(self, text, private):
        event = {"eventType": "utterance", "parameters": {"dialogEvent": {
            "speakerUri": HUMAN_URI, "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": text}]}}}}}
        event["to"] = {**self.me, "private": True} if private else self.me
        return event

    def test_private_question_gets_a_private_answer_to_the_asker(self):
        reply = self._send([self._utterance("echo this quietly", private=True)])[0]
        self.assertEqual(reply["to"], {"speakerUri": HUMAN_URI, "private": True})

    def test_public_question_gets_a_public_answer(self):
        reply = self._send([self._utterance("echo this", private=False)])[0]
        self.assertNotIn("to", reply)

    def test_privacy_carries_over_to_an_answer_collected_after_a_status(self):
        # Slow work: the agent first sends a "working on it" status, then the
        # gateway's resume request collects the answer. Both stay private.
        def slow(text):
            time.sleep(0.5)
            return "answer: " + text

        with patch.object(bsa, "_FLOOR_HOLDER_ENABLED", True), patch.object(bsa, "_RACE_DEADLINE_S", 0.05), \
                patch.object(self.agent, "process_utterance", side_effect=slow):
            status = self._send([self._utterance("echo slowly", private=True)])[0]
            resume = {"eventType": "utterance", "to": self.me, "parameters": {"dialogEvent": {
                "speakerUri": "tag:web-floor,2026:floor-manager",
                "features": {bsa.RESUME_FEATURE: {"mimeType": "text/plain", "tokens": [{"value": "conv-private"}]}}}}}
            answer = self._send([resume])[0]

        self.assertIn(bsa.FLOOR_HOLDER_FEATURE, status["parameters"]["dialogEvent"]["features"])
        self.assertEqual(status["to"], {"speakerUri": HUMAN_URI, "private": True})
        self.assertEqual(answer["to"], {"speakerUri": HUMAN_URI, "private": True})
        self.assertIn("answer: echo slowly", answer["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"])


if __name__ == "__main__":
    unittest.main()
