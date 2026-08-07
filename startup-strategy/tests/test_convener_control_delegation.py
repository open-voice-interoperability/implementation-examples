import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CONVENER_SERVICE = ROOT / "convener_service"
if str(CONVENER_SERVICE) not in sys.path:
    sys.path.insert(0, str(CONVENER_SERVICE))

import convener


def delegated_envelope(event_type, to=None, extra_event_fields=None):
    """Builds the envelope shape web-floor's floor_router._call_convener()
    sends: a floor-manager sender, and the delegated event carrying the
    roundHistory/roundTurnOrder marker that distinguishes a Phase-2+
    delegation from the OLD (still-live) raw gateway call shape."""
    event = {"eventType": event_type, "parameters": {"roundHistory": [], "roundTurnOrder": []}}
    if to is not None:
        event["to"] = to
    if extra_event_fields:
        event.update(extra_event_fields)
    return json.dumps({
        "openFloor": {
            "schema": {"version": "1.1", "url": "https://openvoicenetwork.org/schema"},
            "conversation": {"id": "conv-1", "conversants": [], "floorGranted": []},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager", "serviceUrl": "http://localhost:8090/"},
            "events": [event],
        }
    })


class TrivialEchoDelegationTests(unittest.TestCase):
    """Phase 2: control events delegated by the floor manager get echoed
    back as-is (no real decision logic yet -- that's Phase 3)."""

    def _run(self, event_type, to=None):
        response_json = convener.handle_envelope_json(delegated_envelope(event_type, to=to))
        return json.loads(response_json)

    def test_invite_is_echoed_back(self):
        to = {"speakerUri": "tag:market", "serviceUrl": "http://localhost:8200/"}
        result = self._run("invite", to=to)
        events = result["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "invite")

    def test_uninvite_is_echoed_back(self):
        to = {"speakerUri": "tag:market", "serviceUrl": "http://localhost:8200/"}
        result = self._run("uninvite", to=to)
        events = result["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "uninvite")

    def test_request_floor_is_echoed_back(self):
        to = {"speakerUri": "tag:market", "serviceUrl": "http://localhost:8200/"}
        result = self._run("requestFloor", to=to)
        events = result["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "requestFloor")

    def test_grant_floor_is_echoed_back(self):
        to = {"speakerUri": "tag:market", "serviceUrl": "http://localhost:8200/"}
        result = self._run("grantFloor", to=to)
        events = result["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "grantFloor")

    def test_revoke_floor_is_echoed_back(self):
        to = {"speakerUri": "tag:market", "serviceUrl": "http://localhost:8200/"}
        result = self._run("revokeFloor", to=to)
        events = result["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "revokeFloor")

    def test_delegated_utterance_gets_no_opinion_yet(self):
        # No roundQuestion means the floor manager never actually started a
        # round for this event (see test_convener_decisions.py for the real
        # decision logic once a roundQuestion is present).
        payload = delegated_envelope(
            "utterance",
            extra_event_fields={"parameters": {
                "roundHistory": [], "roundTurnOrder": [],
                "dialogEvent": {"speakerUri": "tag:human", "features": {"text": {"tokens": [{"value": "hello"}]}}},
            }},
        )
        response = json.loads(convener.handle_envelope_json(payload))
        self.assertEqual(response["openFloor"]["events"], [])


class OldPathUnaffectedTests(unittest.TestCase):
    """The pre-existing (still-live) gateway call shape has no roundHistory
    marker, so it must keep hitting the original handling untouched."""

    def test_plain_invite_without_marker_still_auto_accepts(self):
        payload = json.dumps({
            "openFloor": {
                "schema": {"version": "1.1", "url": "https://openvoicenetwork.org/schema"},
                "conversation": {"id": "conv-1"},
                "sender": {"speakerUri": "tag:web-floor,2026:gateway", "serviceUrl": "http://localhost:8090/"},
                "events": [{"eventType": "invite"}],
            }
        })
        response = json.loads(convener.handle_envelope_json(payload))
        events = response["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "acceptInvite")

    def test_plain_get_manifests_without_marker_still_publishes(self):
        payload = json.dumps({
            "openFloor": {
                "schema": {"version": "1.1", "url": "https://openvoicenetwork.org/schema"},
                "conversation": {"id": "conv-1"},
                "sender": {"speakerUri": "tag:web-floor,2026:gateway", "serviceUrl": "http://localhost:8090/"},
                "events": [{"eventType": "getManifests"}],
            }
        })
        response = json.loads(convener.handle_envelope_json(payload))
        events = response["openFloor"]["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["eventType"], "publishManifests")


if __name__ == "__main__":
    unittest.main()
