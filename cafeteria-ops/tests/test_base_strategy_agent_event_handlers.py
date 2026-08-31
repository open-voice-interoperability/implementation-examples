import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.base_strategy_agent import BaseStrategyAgent


class _EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Test Agent"
    AGENT_PORT = 8399

    def process_utterance(self, user_text: str) -> str:
        return f"echo: {user_text}"


class FloorResetOnLifecycleEventsTests(unittest.TestCase):
    """uninvite, bye, and yieldFloor all mean this agent no longer has floor
    rights -- each must reset _floor_granted and produce no reply event."""

    def setUp(self):
        self.agent = _EchoAgent()
        self.agent._floor_granted = True
        self.in_envelope = types.SimpleNamespace()
        self.out_envelope = types.SimpleNamespace(events=[])

    def test_uninvite_resets_floor_granted(self):
        self.agent.on_uninvite(None, self.in_envelope, self.out_envelope)

        self.assertFalse(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])

    def test_bye_resets_floor_granted(self):
        self.agent.on_bye(None, self.in_envelope, self.out_envelope)

        self.assertFalse(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])

    def test_yield_floor_resets_floor_granted(self):
        self.agent.on_yield_floor(None, self.in_envelope, self.out_envelope)

        self.assertFalse(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])


class InformationalNoOpEventsTests(unittest.TestCase):
    """acceptInvite/declineInvite/publishManifests are Pass-Through broadcasts
    about OTHER conversants' lifecycle -- log-only, no state change, no reply."""

    def setUp(self):
        self.agent = _EchoAgent()
        self.agent._floor_granted = True
        self.in_envelope = types.SimpleNamespace()
        self.out_envelope = types.SimpleNamespace(events=[])

    def test_accept_invite_is_a_no_op(self):
        self.agent.on_accept_invite(None, self.in_envelope, self.out_envelope)

        self.assertTrue(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])

    def test_decline_invite_is_a_no_op(self):
        self.agent.on_decline_invite(None, self.in_envelope, self.out_envelope)

        self.assertTrue(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])

    def test_publish_manifests_is_a_no_op(self):
        self.agent.on_publish_manifests(None, self.in_envelope, self.out_envelope)

        self.assertTrue(self.agent._floor_granted)
        self.assertEqual(self.out_envelope.events, [])


if __name__ == "__main__":
    unittest.main()
