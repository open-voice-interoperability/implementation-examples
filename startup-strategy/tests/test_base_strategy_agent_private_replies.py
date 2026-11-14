import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.base_strategy_agent import BaseStrategyAgent

HUMAN_URI = "openFloor://localhost:8090/StartupStrategyClient"


class EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Specialist"
    AGENT_PORT = 8299
    AGENT_SYNOPSIS = "echoes"

    def process_utterance(self, user_text):
        return "answer: " + user_text


class PrivateRepliesTests(unittest.TestCase):
    """OFP 1.1.1 section 2.1: private utterances get private responses."""

    def setUp(self):
        self.agent = EchoAgent()
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


if __name__ == "__main__":
    unittest.main()
