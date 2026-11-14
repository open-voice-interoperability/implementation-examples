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

HUMAN_URI = "openFloor://localhost:8090/StartupStrategyClient"
OTHER_AGENT = "http://127.0.0.1:8200/"
CONVENER = "http://127.0.0.1:8199/"


class EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Specialist"
    AGENT_PORT = 8299
    AGENT_SYNOPSIS = "echoes"

    def process_utterance(self, user_text):
        return "answer: " + user_text


class AnswerOnGrantTests(unittest.TestCase):
    """The question is broadcast once; the convener's later grantFloor, sent
    on its own, is the agent's cue to answer the question it already heard
    (see BaseStrategyAgent._handle_grant_floor)."""

    def setUp(self):
        self.agent = EchoAgent()
        self.me = {"speakerUri": self.agent.speakerUri, "serviceUrl": self.agent.serviceUrl}

    def _send(self, events):
        # The floor manager lists every invited agent; the person isn't one.
        roster = [{"identification": {"speakerUri": url, "serviceUrl": url, "conversationalName": "",
                                      "organization": "", "synopsis": ""}}
                  for url in (self.agent.serviceUrl, OTHER_AGENT, CONVENER)]
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "conv-grant", "conversants": roster},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": events,
        }}
        return json.loads(self.agent.handle_json_envelope(json.dumps(envelope)))["openFloor"].get("events") or []

    @staticmethod
    def _utterance(text, speaker=HUMAN_URI):
        return {"eventType": "utterance", "parameters": {"dialogEvent": {
            "speakerUri": speaker, "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": text}]}}}}}

    def _grant(self):
        return {"eventType": "grantFloor", "to": self.me}

    @staticmethod
    def _texts(events):
        return [e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                for e in events if e.get("eventType") == "utterance"]

    def test_a_question_heard_without_the_floor_is_answered_when_granted(self):
        self.assertEqual(self._send([self._utterance("plan the week")]), [])  # no floor yet: quiet
        self.assertEqual(self._texts(self._send([self._grant()])), ["answer: plan the week"])

    def test_it_is_answered_only_once(self):
        self._send([self._utterance("plan the week")])
        self._send([self._grant()])
        self._send([{"eventType": "revokeFloor", "to": self.me}])
        self.assertEqual(self._send([self._grant()]), [])

    def test_a_grant_with_a_question_answers_that_question_only(self):
        self._send([self._utterance("plan the week")])
        replies = self._send([self._grant(), self._utterance("just the costs, please", speaker=CONVENER)])
        self.assertEqual(self._texts(replies), ["answer: just the costs, please"])
        self._send([{"eventType": "revokeFloor", "to": self.me}])
        self.assertEqual(self._send([self._grant()]), [])  # the older one isn't left over

    def test_another_agents_reply_is_not_an_open_question(self):
        self._send([self._utterance("TAM is $2B", speaker=OTHER_AGENT)])
        self.assertEqual(self._send([self._grant()]), [])

    def test_a_newer_question_replaces_the_older_one(self):
        self._send([self._utterance("plan the week")])
        self._send([self._utterance("actually, plan just Monday")])
        self.assertEqual(self._texts(self._send([self._grant()])), ["answer: actually, plan just Monday"])

    def test_a_stale_question_is_not_answered(self):
        self._send([self._utterance("plan the week")])
        with patch.object(bsa.time, "time", return_value=time.time() + EchoAgent._OPEN_QUESTION_TTL_S + 1):
            self.assertEqual(self._send([self._grant()]), [])

    def test_while_holding_the_floor_another_agents_message_is_not_answered(self):
        # e.g. a peer's reply broadcast during this agent's turn: context,
        # not a new question -- answering it gave duplicate replies live (cafeteria-ops).
        self._send([self._grant()])
        self.assertEqual(self._send([self._utterance("Market size is small", speaker=OTHER_AGENT)]), [])
        history = [text for _, text in self.agent._conversation_histories["conv-grant"]]
        self.assertIn("Market size is small", history)  # still heard

    def test_while_holding_the_floor_the_person_and_the_convener_are_answered(self):
        self._send([self._grant()])
        self.assertEqual(self._texts(self._send([self._utterance("plan the week")])), ["answer: plan the week"])
        self.assertEqual(self._texts(self._send([self._utterance("costs too", speaker=CONVENER)])), ["answer: costs too"])

    def test_without_a_convener_agents_may_answer_each_other(self):
        def send_without_convener(events):
            roster = [{"identification": {"speakerUri": url, "serviceUrl": url, "conversationalName": "",
                                          "organization": "", "synopsis": ""}}
                      for url in (self.agent.serviceUrl, OTHER_AGENT)]
            envelope = {"openFloor": {"schema": {"version": "1.1"},
                                      "conversation": {"id": "conv-free", "conversants": roster},
                                      "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"}, "events": events}}
            return json.loads(self.agent.handle_json_envelope(json.dumps(envelope)))["openFloor"].get("events") or []

        send_without_convener([self._grant()])
        self.assertEqual(self._texts(send_without_convener([self._utterance("TAM is $2B", speaker=OTHER_AGENT)])),
                         ["answer: TAM is $2B"])

    def test_the_question_is_in_the_history_once(self):
        self._send([self._utterance("plan the week")])
        self._send([self._grant()])
        history = self.agent._conversation_histories["conv-grant"]
        self.assertEqual([text for _, text in history].count("plan the week"), 1)


if __name__ == "__main__":
    unittest.main()
