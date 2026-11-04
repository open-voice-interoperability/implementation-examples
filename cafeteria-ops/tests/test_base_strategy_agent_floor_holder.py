import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agents.base_strategy_agent as bsa
from agents.base_strategy_agent import BaseStrategyAgent
from openfloor.events import UtteranceEvent
from openfloor.dialog_event import DialogEvent, TextFeature, Token


def _utterance(text, speaker_uri="tag:human"):
    return UtteranceEvent(dialogEvent=DialogEvent(
        speakerUri=speaker_uri,
        features={"text": TextFeature(tokens=[Token(value=text)])},
    ))


def _resume(conv_id, text, fm="tag:web-floor,2026:floor-manager"):
    return UtteranceEvent(dialogEvent=DialogEvent(
        speakerUri=fm,
        features={
            "text": TextFeature(tokens=[Token(value=text)]),
            bsa.RESUME_FEATURE: TextFeature(tokens=[Token(value=conv_id)]),
        },
    ))


class _SlowAgent(BaseStrategyAgent):
    AGENT_NAME = "Slow Test Agent"
    AGENT_PORT = 8398
    WORKING_LABEL = "crunching the numbers"

    def __init__(self):
        super().__init__()
        self._enforce_scope_gate = False   # these doubles don't exercise the scope gate
        self._floor_granted = True
        self.release = threading.Event()
        self.calls = 0

    def process_utterance(self, user_text: str) -> str:
        self.calls += 1
        self.release.wait(timeout=5)
        return f"done: {user_text}"


class FloorHolderRaceTests(unittest.TestCase):
    """A slow answer returns a transient floor-holder now and the finished
    answer on the gateway's resume request -- the work runs once."""

    def setUp(self):
        self._deadline = bsa._RACE_DEADLINE_S
        self._enabled = bsa._FLOOR_HOLDER_ENABLED
        bsa._RACE_DEADLINE_S = 0.05
        bsa._FLOOR_HOLDER_ENABLED = True

    def tearDown(self):
        bsa._RACE_DEADLINE_S = self._deadline
        bsa._FLOOR_HOLDER_ENABLED = self._enabled

    def test_slow_work_emits_a_floor_holder_then_the_answer_on_resume(self):
        agent = _SlowAgent()
        out = types.SimpleNamespace(events=[])
        agent.bot_on_utterance(_utterance("plan five days"), types.SimpleNamespace(), out)

        # Race deadline passed -> one transient floor-holder utterance.
        self.assertEqual(len(out.events), 1)
        feats = out.events[0].dialogEvent.features
        self.assertIn(bsa.FLOOR_HOLDER_FEATURE, feats)
        self.assertEqual(feats["text"].tokens[0].value, "crunching the numbers")
        self.assertEqual(agent.calls, 1)                 # work started
        self.assertIn("", agent._pending_futures)        # conv_id "" (bare envelope)

        # Resume: the finished answer, and the work is NOT re-run.
        agent.release.set()
        out2 = types.SimpleNamespace(events=[])
        agent.bot_on_utterance(_resume("", "plan five days"), types.SimpleNamespace(), out2)

        self.assertEqual(len(out2.events), 1)
        feats2 = out2.events[0].dialogEvent.features
        self.assertNotIn(bsa.FLOOR_HOLDER_FEATURE, feats2)
        self.assertEqual(feats2["text"].tokens[0].value, "done: plan five days")
        self.assertEqual(agent.calls, 1)
        self.assertEqual(agent._pending_futures, {})

    def test_fast_work_answers_in_one_shot_with_no_floor_holder(self):
        agent = _SlowAgent()
        agent.release.set()                              # process_utterance returns at once
        out = types.SimpleNamespace(events=[])
        agent.bot_on_utterance(_utterance("quick one"), types.SimpleNamespace(), out)

        self.assertEqual(len(out.events), 1)
        self.assertNotIn(bsa.FLOOR_HOLDER_FEATURE, out.events[0].dialogEvent.features)
        self.assertEqual(out.events[0].dialogEvent.features["text"].tokens[0].value, "done: quick one")
        self.assertEqual(agent._pending_futures, {})

    def test_resume_without_a_pending_future_recomputes(self):
        agent = _SlowAgent()
        agent.release.set()
        out = types.SimpleNamespace(events=[])
        agent.bot_on_utterance(_resume("conv-x", "recompute me"), types.SimpleNamespace(), out)

        self.assertEqual(agent.calls, 1)
        self.assertEqual(out.events[0].dialogEvent.features["text"].tokens[0].value, "done: recompute me")

    def test_feature_disabled_is_fully_synchronous(self):
        bsa._FLOOR_HOLDER_ENABLED = False
        agent = _SlowAgent()
        agent.release.set()
        out = types.SimpleNamespace(events=[])
        agent.bot_on_utterance(_utterance("sync path"), types.SimpleNamespace(), out)

        self.assertEqual(agent._pending_futures, {})
        self.assertEqual(out.events[0].dialogEvent.features["text"].tokens[0].value, "done: sync path")


class WorkingLabelTests(unittest.TestCase):
    def test_default_is_the_class_attr(self):
        agent = _SlowAgent()
        self.assertEqual(agent.working_label("anything"), "crunching the numbers")


if __name__ == "__main__":
    unittest.main()
