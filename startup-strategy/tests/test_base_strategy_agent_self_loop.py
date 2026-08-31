import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.base_strategy_agent import BaseStrategyAgent
from openfloor.events import UtteranceEvent
from openfloor.dialog_event import DialogEvent, TextFeature, Token


class _EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Test Agent"
    AGENT_PORT = 8299

    def __init__(self):
        super().__init__()
        self.process_utterance_calls = []

    def process_utterance(self, user_text: str) -> str:
        self.process_utterance_calls.append(user_text)
        return f"echo: {user_text}"


def _make_utterance_event(text: str, speaker_uri: str) -> UtteranceEvent:
    dialog = DialogEvent(
        speakerUri=speaker_uri,
        features={"text": TextFeature(tokens=[Token(value=text)])},
    )
    return UtteranceEvent(dialogEvent=dialog)


class SelfLoopGuardTests(unittest.TestCase):
    def setUp(self):
        self.agent = _EchoAgent()
        self.agent._floor_granted = True  # bypass floor gate to isolate the self-loop guard
        self.in_envelope = types.SimpleNamespace()
        self.out_envelope = types.SimpleNamespace(events=[])

    def test_utterance_from_self_is_ignored(self):
        event = _make_utterance_event("hello", speaker_uri=self.agent.speakerUri)

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, [])
        self.assertEqual(self.out_envelope.events, [])

    def test_utterance_from_self_is_ignored_case_and_slash_insensitive(self):
        # _normalize_endpoint_id lowercases and strips trailing slash, so a
        # relayed/rebroadcast copy with a slightly different URI form must
        # still be recognized as this agent's own speakerUri.
        loud_uri = self.agent.speakerUri.upper() + "/"
        event = _make_utterance_event("hello", speaker_uri=loud_uri)

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, [])
        self.assertEqual(self.out_envelope.events, [])

    def test_utterance_from_someone_else_is_processed_normally(self):
        event = _make_utterance_event("what's the market size?", speaker_uri="tag:someone-else,2025:user")

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, ["what's the market size?"])
        self.assertEqual(len(self.out_envelope.events), 1)

    def test_utterance_with_no_speaker_uri_is_processed_normally(self):
        # A missing speakerUri must not be treated as a self-match.
        event = _make_utterance_event("no speaker info here", speaker_uri="")

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, ["no speaker info here"])
        self.assertEqual(len(self.out_envelope.events), 1)


if __name__ == "__main__":
    unittest.main()
