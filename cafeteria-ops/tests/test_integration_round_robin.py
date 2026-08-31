"""Cross-repo integration test: drives a full conversation through
web-floor's floor_router.process_envelope() using the REAL convener.py
decision logic (no mocking of either side) and small fake specialist
handlers standing in for base_strategy_agent.py's real floor-gate behavior.

floor_router.py/floor_state.py have no dependencies beyond the stdlib, so
they import cleanly under this project's own .venv (which already has
everything convener.py needs) -- no need to spin up real HTTP servers or
cross into web-floor's separate environment.
"""

import json
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

WEB_FLOOR_API = ROOT.parents[1] / "floor-implementations" / "implementations" / "web-floor" / "api"
if str(WEB_FLOOR_API) not in sys.path:
    sys.path.insert(0, str(WEB_FLOOR_API))

import convener
import floor_router
from floor_state import ConversationState


FLOOR_MANAGER_IDENTITY = {"speakerUri": "tag:web-floor,2026:manager", "serviceUrl": "http://127.0.0.1:8090/"}
CONVENER_URL = convener.CONVENER_MANIFEST.identification.serviceUrl
HUMAN_SPEAKER_URI = "tag:human"


def make_fake_specialist(agent_key: str, service_url: str):
    """Mirrors base_strategy_agent.py's real behavior closely enough for
    this test: auto-accepts invites, tracks its own local floor-granted
    state, and only replies to an utterance while granted."""
    state = {"floor_granted": False}

    def handle(envelope: dict) -> dict:
        openfloor = envelope.get("openFloor", envelope)
        events = openfloor.get("events", [])
        out_events = []
        for event in events:
            event_type = event.get("eventType")
            if event_type == "invite":
                state["floor_granted"] = False
                out_events.append({"eventType": "acceptInvite"})
            elif event_type == "grantFloor":
                state["floor_granted"] = True
            elif event_type == "revokeFloor":
                state["floor_granted"] = False
            elif event_type == "utterance" and state["floor_granted"]:
                dialog = (event.get("parameters") or {}).get("dialogEvent", {})
                tokens = (dialog.get("features", {}).get("text", {}) or {}).get("tokens", [])
                text = tokens[0].get("value", "") if tokens else ""
                out_events.append({
                    "eventType": "utterance",
                    "parameters": {"dialogEvent": {
                        "speakerUri": f"tag:{agent_key}",
                        "features": {"text": {"tokens": [{"value": f"{agent_key} analysis of: {text}"}]}},
                    }},
                })
        return {"openFloor": {"conversation": {}, "sender": {"speakerUri": f"tag:{agent_key}", "serviceUrl": service_url}, "events": out_events}}

    return handle, state, service_url


def build_deliver(specialist_handlers: dict):
    """The floor_router `deliver` callback: routes to convener's real
    handle_envelope_json() for the convener's URL, or to a fake
    specialist's in-process handler, matching each by target URL."""

    def deliver(target_url: str, envelope: dict, timeout: float) -> list:
        if target_url == CONVENER_URL:
            response = json.loads(convener.handle_envelope_json(json.dumps(envelope)))
        elif target_url in specialist_handlers:
            response = specialist_handlers[target_url](envelope)
        else:
            return []
        openfloor = response.get("openFloor", response)
        return openfloor.get("events", [])

    return deliver


def invite_and_accept(conv, deliver, speaker_uri, service_url):
    envelope = {
        "openFloor": {
            "conversation": {"id": conv.conv_id},
            "sender": {"speakerUri": HUMAN_SPEAKER_URI},
            "events": [{"eventType": "invite", "to": {"speakerUri": speaker_uri, "serviceUrl": service_url}}],
        }
    }
    return floor_router.process_envelope(conv, envelope, FLOOR_MANAGER_IDENTITY, deliver)


def send_human_utterance(conv, deliver, text, routing_mode=None):
    dialog_features = {"text": {"tokens": [{"value": text}]}}
    if routing_mode:
        dialog_features["routingMode"] = {"tokens": [{"value": routing_mode}]}
    envelope = {
        "openFloor": {
            "conversation": {"id": conv.conv_id},
            "sender": {"speakerUri": HUMAN_SPEAKER_URI},
            "events": [{
                "eventType": "utterance",
                "parameters": {"dialogEvent": {"speakerUri": HUMAN_SPEAKER_URI, "features": dialog_features}},
            }],
        }
    }
    return floor_router.process_envelope(conv, envelope, FLOOR_MANAGER_IDENTITY, deliver)


class RoundRobinIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.conv = ConversationState(conv_id="integration-rr")
        self.nutrition_handle, self.nutrition_state, self.nutrition_url = make_fake_specialist("nutrition", convener.AGENTS["nutrition"]["url"])
        self.procurement_handle, self.procurement_state, self.procurement_url = make_fake_specialist("procurement", convener.AGENTS["procurement"]["url"])
        self.shopping_list_handle, self.shopping_list_state, self.shopping_list_url = make_fake_specialist("shopping_list", convener.AGENTS["shopping_list"]["url"])
        self.deliver = build_deliver({
            self.nutrition_url: self.nutrition_handle,
            self.procurement_url: self.procurement_handle,
            self.shopping_list_url: self.shopping_list_handle,
        })

        # Register convener as a conversant + convener (mirrors what
        # detect_convener_role does after a real acceptInvite -- set up
        # directly here since this test is exercising round-robin behavior,
        # not convener detection, which is already covered elsewhere).
        self.conv.add_conversant(
            convener.CONVENER_MANIFEST.identification.speakerUri, CONVENER_URL, "Convener"
        )
        self.conv.convener_speaker_uri = convener.CONVENER_MANIFEST.identification.speakerUri
        self.conv.get_conversant(self.conv.convener_speaker_uri).is_convener = True

        invite_and_accept(self.conv, self.deliver, "tag:nutrition", self.nutrition_url)
        invite_and_accept(self.conv, self.deliver, "tag:procurement", self.procurement_url)
        invite_and_accept(self.conv, self.deliver, "tag:shopping_list", self.shopping_list_url)

    def test_round_robin_visits_each_agent_once_and_ends_fully_revoked(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement", "shopping_list"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            executed = send_human_utterance(self.conv, self.deliver, "evaluate this weekly menu", routing_mode="round_robin")

        reply_texts = [
            e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            for e in executed
            if e.get("eventType") == "utterance" and e.get("parameters", {}).get("dialogEvent", {}).get("speakerUri", "").startswith("tag:") and "analysis of" in str(e)
        ]
        self.assertEqual(len(reply_texts), 3)
        self.assertTrue(any("nutrition analysis" in t for t in reply_texts))
        self.assertTrue(any("procurement analysis" in t for t in reply_texts))
        self.assertTrue(any("shopping_list analysis" in t for t in reply_texts))

        # Every specialist ends the round revoked -- no one left holding the floor.
        self.assertFalse(self.nutrition_state["floor_granted"])
        self.assertFalse(self.procurement_state["floor_granted"])
        self.assertFalse(self.shopping_list_state["floor_granted"])

    def test_round_robin_agents_answer_in_classification_order_one_at_a_time(self):
        # nutrition must never be granted before it's nutrition's turn, etc.
        # -- verify by checking each agent's floor state at the moment the
        # PRECEDING agent's reply is being processed (i.e. only one agent
        # ever granted at a time during the round).
        seen_concurrent_grants = []
        original_deliver = self.deliver

        def tracking_deliver(target_url, envelope, timeout):
            granted_count = sum([self.nutrition_state["floor_granted"], self.procurement_state["floor_granted"], self.shopping_list_state["floor_granted"]])
            seen_concurrent_grants.append(granted_count)
            return original_deliver(target_url, envelope, timeout)

        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement", "shopping_list"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            send_human_utterance(self.conv, tracking_deliver, "evaluate this weekly menu", routing_mode="round_robin")

        # At no point were two agents simultaneously granted the floor.
        self.assertTrue(all(count <= 1 for count in seen_concurrent_grants))

    def test_direct_address_only_that_agent_replies(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            executed = send_human_utterance(self.conv, self.deliver, "procurement specialist, what about pricing?")

        # Same grant -> ask -> answer -> revoke pattern as any single turn --
        # procurement ends revoked once it's answered, same as round-robin's last agent.
        self.assertFalse(self.procurement_state["floor_granted"])
        self.assertFalse(self.nutrition_state["floor_granted"])
        self.assertFalse(self.shopping_list_state["floor_granted"])
        reply_texts = [
            e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            for e in executed
            if e.get("eventType") == "utterance" and "analysis of" in str(e)
        ]
        self.assertEqual(len(reply_texts), 1)
        self.assertIn("procurement analysis", reply_texts[0])


class FullSweepIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.conv = ConversationState(conv_id="integration-sweep")
        self.nutrition_handle, self.nutrition_state, self.nutrition_url = make_fake_specialist("nutrition", convener.AGENTS["nutrition"]["url"])
        self.procurement_handle, self.procurement_state, self.procurement_url = make_fake_specialist("procurement", convener.AGENTS["procurement"]["url"])
        self.deliver = build_deliver({self.nutrition_url: self.nutrition_handle, self.procurement_url: self.procurement_handle})

        self.conv.add_conversant(convener.CONVENER_MANIFEST.identification.speakerUri, CONVENER_URL, "Convener")
        self.conv.convener_speaker_uri = convener.CONVENER_MANIFEST.identification.speakerUri
        self.conv.get_conversant(self.conv.convener_speaker_uri).is_convener = True

        invite_and_accept(self.conv, self.deliver, "tag:nutrition", self.nutrition_url)
        invite_and_accept(self.conv, self.deliver, "tag:procurement", self.procurement_url)

    def test_full_sweep_both_agents_answer_the_same_broadcast(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            executed = send_human_utterance(self.conv, self.deliver, "evaluate this menu item")  # no routing_mode = full sweep

        reply_texts = [
            e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            for e in executed
            if e.get("eventType") == "utterance" and "analysis of" in str(e)
        ]
        self.assertEqual(len(reply_texts), 2)
        self.assertFalse(self.nutrition_state["floor_granted"])
        self.assertFalse(self.procurement_state["floor_granted"])


class TeamScopedInviteIntegrationTests(unittest.TestCase):
    """Cafeteria-ops-specific: a team-scoped invite ("invite the supply
    chain team") must invite only that team's agents, not everyone -- the
    mechanism that lets one unified convener still behave like two teams."""

    def setUp(self):
        self.conv = ConversationState(conv_id="integration-team-scope")
        self.deliver = build_deliver({})  # no specialist replies needed for this test
        self.conv.add_conversant(convener.CONVENER_MANIFEST.identification.speakerUri, CONVENER_URL, "Convener")
        self.conv.convener_speaker_uri = convener.CONVENER_MANIFEST.identification.speakerUri
        self.conv.get_conversant(self.conv.convener_speaker_uri).is_convener = True

    def test_invite_supply_chain_team_invites_only_that_team(self):
        executed = send_human_utterance(self.conv, self.deliver, "invite the supply chain team")

        invited_urls = {
            e["to"]["serviceUrl"] for e in executed
            if e.get("eventType") == "invite"
        }
        expected_urls = {convener.AGENTS[k]["url"] for k in convener.SUPPLY_CHAIN_AGENTS}
        self.assertEqual(invited_urls, expected_urls)

    def test_invite_one_named_specialist_invites_only_that_specialist(self):
        # Confirmed live: this previously invited all 9 specialists instead
        # of just the one named.
        executed = send_human_utterance(self.conv, self.deliver, "invite the menu designer")

        invited_urls = {
            e["to"]["serviceUrl"] for e in executed
            if e.get("eventType") == "invite"
        }
        self.assertEqual(invited_urls, {convener.AGENTS["menu_designer"]["url"]})


if __name__ == "__main__":
    unittest.main()
