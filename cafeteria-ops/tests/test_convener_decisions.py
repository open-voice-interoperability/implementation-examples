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

import convener


def conversant_record(agent_key, floor_granted=False):
    """Flat {speakerUri, serviceUrl, floorGranted} shape -- what
    _conversant_records() already produces, and what
    _decide_for_human_utterance/_decide_for_specialist_reply take
    directly."""
    info = convener.AGENTS[agent_key]
    return {"speakerUri": f"tag:{agent_key}", "serviceUrl": info["url"], "floorGranted": floor_granted}


def wrapped_conversant(agent_key):
    """The raw conversation.conversants wire shape (identification-wrapped)
    that _conversant_records() itself parses -- for tests that go through
    _decide_delegated_utterance, which calls _conversant_records internally."""
    record = conversant_record(agent_key)
    return {"identification": record}


ALL_RECORDS = [conversant_record(k) for k in convener.FULL_ANALYSIS_SEQUENCE]
ALL_WRAPPED_RECORDS = [wrapped_conversant(k) for k in convener.FULL_ANALYSIS_SEQUENCE]

# A non-specialist agent the user added from the Planner page.
GUEST_RECORD = {"speakerUri": "http://localhost:8767", "serviceUrl": "http://localhost:8767/", "floorGranted": True}


class DecideForHumanUtteranceTests(unittest.TestCase):
    def test_invite_only_returns_invite_events_for_not_yet_invited(self):
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, [])

        self.assertEqual(len(events), len(convener.FULL_ANALYSIS_SEQUENCE))
        self.assertTrue(all(isinstance(e, convener.InviteEvent) for e in events))

    def test_invite_only_skips_already_invited(self):
        already_invited = [conversant_record("nutrition")]
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, already_invited)

        self.assertEqual(len(events), len(convener.FULL_ANALYSIS_SEQUENCE) - 1)

    def test_invite_only_when_everyone_already_invited_returns_status_text(self):
        with patch.object(convener, "classify_utterance", return_value={"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}):
            events = convener._decide_for_human_utterance("invite your specialists", "", 50, ALL_RECORDS)

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.UtteranceEvent)

    def test_invite_only_with_team_scope_invites_only_that_team(self):
        classification = {"action": "invite_only", "addressed_agent_key": None, "agent_keys": convener.SUPPLY_CHAIN_AGENTS}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("invite the supply chain team", "", 50, [])

        self.assertEqual(len(events), len(convener.SUPPLY_CHAIN_AGENTS))
        self.assertTrue(all(isinstance(e, convener.InviteEvent) for e in events))
        invited_urls = {e.to.serviceUrl for e in events}
        self.assertEqual(invited_urls, {convener.AGENTS[k]["url"] for k in convener.SUPPLY_CHAIN_AGENTS})

    def test_ask_specific_agent_grants_the_one_addressed_without_repeating_the_question(self):
        # Every agent already heard the user's own (public) question; the
        # grant alone is the addressed agent's cue to answer it.
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("procurement specialist, what about pricing?", "", 50, ALL_RECORDS)

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["procurement"]["url"])

    def test_ask_specific_agent_revokes_every_other_currently_granted_agent(self):
        # Regression test: a stale grant left over from an earlier
        # full-sweep/round-robin turn (or floor_router.py's own <=2-agent
        # free-cross-talk exception) must not let an unaddressed agent
        # reply just because it still holds the floor when the broadcast
        # question reaches it.
        records = [
            conversant_record("nutrition", floor_granted=True),
            conversant_record("procurement", floor_granted=True),
            conversant_record("shopping_list", floor_granted=False),
        ]
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("procurement specialist, what about pricing?", "", 50, records)

        revoke_events = [e for e in events if isinstance(e, convener.RevokeFloorEvent)]
        self.assertEqual(len(revoke_events), 1)
        self.assertEqual(revoke_events[0].to.serviceUrl, convener.AGENTS["nutrition"]["url"])
        # The addressed agent itself is granted, never revoked, even
        # though it was already in the granted list.
        grant_events = [e for e in events if isinstance(e, convener.GrantFloorEvent)]
        self.assertEqual(len(grant_events), 1)
        self.assertEqual(grant_events[0].to.serviceUrl, convener.AGENTS["procurement"]["url"])
        # Revokes happen before the addressed agent is granted.
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertIsInstance(events[-1], convener.GrantFloorEvent)

    def test_ask_specific_agent_with_nobody_else_granted_issues_no_revokes(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "procurement", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("procurement specialist, what about pricing?", "", 50, ALL_RECORDS)

        self.assertFalse(any(isinstance(e, convener.RevokeFloorEvent) for e in events))

    def test_round_robin_grants_only_the_first_agent(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement", "shopping_list"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("evaluate this menu", "round_robin", 50, ALL_RECORDS)

        # Just the grant: the first agent answers the question it already heard.
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["nutrition"]["url"])

    def test_round_robin_revokes_a_stale_specialist_grant_but_not_guests(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement"]}
        records = [conversant_record(k, floor_granted=(k == "inventory")) for k in convener.FULL_ANALYSIS_SEQUENCE]
        records.append(dict(GUEST_RECORD))  # granted, e.g. still answering the request
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("evaluate this menu", "round_robin", 50, records)

        revoked = [e.to.serviceUrl for e in events if isinstance(e, convener.RevokeFloorEvent)]
        self.assertEqual(revoked, [convener.AGENTS["inventory"]["url"]])
        self.assertIsInstance(events[-1], convener.GrantFloorEvent)
        self.assertEqual(events[-1].to.serviceUrl, convener.AGENTS["nutrition"]["url"])

    def test_full_sweep_grants_everyone_without_repeating_the_question(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement", "shopping_list"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_human_utterance("evaluate this menu", "", 50, ALL_RECORDS)

        grant_events = [e for e in events if isinstance(e, convener.GrantFloorEvent)]
        utterance_events = [e for e in events if isinstance(e, convener.UtteranceEvent)]
        self.assertEqual(len(grant_events), 3)
        self.assertEqual({e.to.serviceUrl for e in grant_events}, {convener.AGENTS[k]["url"] for k in ("nutrition", "procurement", "shopping_list")})
        self.assertEqual(utterance_events, [])  # each answers the question it already heard

    def test_max_words_appends_instruction_to_question_text(self):
        # Used when the convener relays a private question in the user's voice.
        text = convener._question_text("how many calories?", 125)
        self.assertIn("Write approximately 125 words", text)
        self.assertIn("address EVERY one of them", text)

    def test_handle_envelope_json_uses_openfloor_1_1_0_schema_version(self):
        dialog = convener.DialogEvent(speakerUri="tag:user")
        text_feature = convener.TextFeature()
        text_feature.tokens = [convener.Token(value="hello")]
        dialog.features = {"text": text_feature}

        envelope = convener.Envelope(
            conversation=convener.Conversation(id="conv:spec-check"),
            sender=convener.Sender(speakerUri="tag:user", serviceUrl="https://example.test/user"),
            schema=convener.Schema(version="1.1.0", url="https://openvoicenetwork.org/schema"),
            events=[convener.UtteranceEvent(dialogEvent=dialog)],
        )

        payload = envelope.to_json(as_payload=True)
        response = json.loads(convener.handle_envelope_json(payload))

        self.assertEqual(response["openFloor"]["schema"]["version"], "1.1.0")

    def test_default_max_words_does_not_append_instruction(self):
        text = convener._question_text("how many calories?", convener.MAX_RESPONSE_WORDS)
        self.assertNotIn("[Write approximately", text)


class DecideForSpecialistReplyTests(unittest.TestCase):
    def test_round_robin_advances_to_next_agent(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement", "shopping_list"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "round_robin", "evaluate this menu", 50, ["tag:nutrition"], ALL_RECORDS
            )

        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")
        self.assertIsInstance(events[1], convener.GrantFloorEvent)
        self.assertEqual(events[1].to.serviceUrl, convener.AGENTS["procurement"]["url"])
        self.assertEqual(len(events), 2)  # no repeat of the question -- procurement already heard it

    def test_round_robin_advance_revokes_the_speaker_once_and_any_stale_grant(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement"]}
        records = [conversant_record(k, floor_granted=k in ("nutrition", "inventory")) for k in convener.FULL_ANALYSIS_SEQUENCE]
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "round_robin", "evaluate this menu", 50, ["tag:nutrition"], records
            )

        revoked = [e.to.speakerUri for e in events if isinstance(e, convener.RevokeFloorEvent)]
        self.assertEqual(revoked, ["tag:nutrition", "tag:inventory"])

    def test_round_robin_sequence_complete_only_revokes(self):
        classification = {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": ["nutrition", "procurement"]}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:procurement", "round_robin", "evaluate this menu", 50, ["tag:nutrition", "tag:procurement"], ALL_RECORDS
            )

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:procurement")

    def test_full_sweep_always_revokes_only_the_speaker(self):
        # floor_router.py itself now closes a specialist's own floor
        # synchronously, right before broadcasting its reply, whenever more
        # than 2 non-convener conversants are registered -- this courtesy
        # copy always arrives strictly AFTER that already happened, so for
        # that case this is a harmless, idempotent echo: revoke just the
        # speaker, nothing more. round_turn_order is irrelevant to this
        # decision now.
        with patch.object(convener, "classify_utterance") as mocked_classify:
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "", "evaluate this menu", 50, [], ALL_RECORDS
            )

        mocked_classify.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")

    def test_full_sweep_with_two_specialists_still_revokes_the_speaker(self):
        # With exactly 2 specialists, floor_router.py deliberately skips its
        # own auto-revoke so the pair can exchange one round of replies --
        # but this decision must still unconditionally revoke the speaker
        # once it's asked: it's the only remaining backstop against the two
        # of them broadcasting to each other forever (each replies to any
        # utterance while granted -- confirmed via a real hang when this
        # was special-cased away too).
        two_records = [conversant_record("nutrition"), conversant_record("procurement")]
        with patch.object(convener, "classify_utterance") as mocked_classify:
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "", "evaluate this menu", 50, [], two_records
            )

        mocked_classify.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")

    def test_missing_question_text_only_revokes_the_speaker(self):
        with patch.object(convener, "classify_utterance") as mocked_classify:
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "round_robin", "", 50, [], ALL_RECORDS
            )

        mocked_classify.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")

    def test_directly_addressed_agents_reply_does_not_advance_to_another_agent(self):
        # Regression test: ask_specific_agent's own agent_keys is always
        # [], which previously fell back to the full invited roster here,
        # asking every OTHER invited agent the SAME direct-address
        # question the addressed agent had just answered.
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "nutrition", "agent_keys": []}
        with patch.object(convener, "classify_utterance", return_value=classification):
            events = convener._decide_for_specialist_reply(
                "tag:nutrition", "round_robin", "Nutrition Specialist, how many calories in rice?", 50, ["tag:nutrition"], ALL_RECORDS
            )

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")


class ConversantRecordsTests(unittest.TestCase):
    """_conversant_records reads BOTH conversation.conversants (identity)
    and the separate conversation.floorGranted list of currently-granted
    speakerUris (see floor_router.py's delegate_to_convener, and OFP 1.1.1
    section 1.6's own definition of floorGranted as "an array of
    speakerURIs") into one flat per-conversant floorGranted bool -- needed
    so a direct address to one agent can revoke every other currently-
    granted agent. Uses speakerUri values distinct from serviceUrl (as
    conversant_record's "tag:<key>" convention does) so these tests would
    actually fail if floorGranted matching were keyed on serviceUrl
    instead, the way it used to be."""

    def test_marks_conversants_present_in_floor_granted_list(self):
        conversation = {
            "conversants": [wrapped_conversant("nutrition"), wrapped_conversant("procurement")],
            "floorGranted": ["tag:nutrition"],
        }
        records = convener._conversant_records(conversation)

        by_key = {r["speakerUri"]: r["floorGranted"] for r in records}
        self.assertTrue(by_key["tag:nutrition"])
        self.assertFalse(by_key["tag:procurement"])

    def test_missing_floor_granted_field_defaults_everyone_to_false(self):
        conversation = {"conversants": [wrapped_conversant("nutrition")]}
        records = convener._conversant_records(conversation)

        self.assertFalse(records[0]["floorGranted"])

    def test_floor_granted_match_is_case_and_slash_insensitive(self):
        conversation = {
            "conversants": [wrapped_conversant("nutrition")],
            "floorGranted": ["TAG:NUTRITION/"],
        }
        records = convener._conversant_records(conversation)

        self.assertTrue(records[0]["floorGranted"])


class RevokeEventsForOtherGrantedAgentsTests(unittest.TestCase):
    def test_revokes_every_other_granted_agent(self):
        records = [
            conversant_record("nutrition", floor_granted=True),
            conversant_record("procurement", floor_granted=True),
            conversant_record("shopping_list", floor_granted=False),
        ]
        events = convener._revoke_events_for_other_granted_agents("procurement", records)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["nutrition"]["url"])

    def test_excluded_agent_is_never_revoked_even_if_granted(self):
        records = [conversant_record("procurement", floor_granted=True)]
        events = convener._revoke_events_for_other_granted_agents("procurement", records)

        self.assertEqual(events, [])

    def test_no_one_granted_returns_no_events(self):
        records = [conversant_record("nutrition", floor_granted=False)]
        events = convener._revoke_events_for_other_granted_agents("procurement", records)

        self.assertEqual(events, [])


class ClassifySpeakerTests(unittest.TestCase):
    def test_recognizes_a_known_specialist(self):
        self.assertEqual(convener._classify_speaker("tag:nutrition", ALL_RECORDS), "specialist")

    def test_treats_unknown_speaker_as_human(self):
        self.assertEqual(convener._classify_speaker("tag:some-human-client", ALL_RECORDS), "human")

    def test_non_specialist_conversant_is_a_guest(self):
        records = ALL_RECORDS + [GUEST_RECORD]
        self.assertEqual(convener._classify_speaker("http://localhost:8767", records), "guest")

    def test_guest_matched_by_service_url_too(self):
        records = ALL_RECORDS + [{"speakerUri": "tag:stella", "serviceUrl": "http://localhost:8767/", "floorGranted": False}]
        self.assertEqual(convener._classify_speaker("http://localhost:8767", records), "guest")


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
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "nutrition", "agent_keys": []}
        event = self._utterance_event("tag:human", "ignored -- roundQuestion wins", "how many calories?")
        with patch.object(convener, "classify_utterance", return_value=classification) as mocked:
            events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})

        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[0], "how many calories?")
        self.assertIsInstance(events[0], convener.GrantFloorEvent)

    def test_specialist_reply_routes_to_specialist_decision(self):
        # No round_turn_order given -> other specialists' original replies
        # may still be pending, so only the speaker is revoked here (see
        # DecideForSpecialistReplyTests for the full revoke-scope coverage).
        event = self._utterance_event("tag:nutrition", "About 450 kcal", "how many calories?", round_routing_mode="")
        events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})

        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")
        self.assertEqual(events[0].to.speakerUri, "tag:nutrition")

    def test_empty_round_question_yields_no_decision(self):
        event = self._utterance_event("tag:human", "hi", "")
        events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})
        self.assertEqual(events, [])

    def test_guest_agent_reply_does_not_restart_the_round(self):
        # Without the guest check this would be classified "human" and the
        # round's question re-routed to every specialist again.
        event = self._utterance_event("http://localhost:8767", "Here are some Jupiter images", "plan a lunch menu")
        conversation = {"conversants": ALL_WRAPPED_RECORDS + [{"identification": GUEST_RECORD}]}
        with patch.object(convener, "classify_utterance") as mocked:
            events = convener._decide_delegated_utterance(event, conversation)

        mocked.assert_not_called()
        # Its turn is over: the only decision is to close its floor.
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, "http://localhost:8767/")

    def test_guest_utterance_is_revoked_even_outside_a_round(self):
        event = self._utterance_event("http://localhost:8767", "Hi, I'm Stella", "")
        conversation = {"conversants": ALL_WRAPPED_RECORDS + [{"identification": GUEST_RECORD}]}
        events = convener._decide_delegated_utterance(event, conversation)
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)

    def test_human_question_addressed_to_a_guest_is_not_routed(self):
        event = self._utterance_event("tag:human", "show me jupiter", "show me jupiter")
        event.to = convener.To(serviceUrl="http://localhost:8767/", private=True)
        conversation = {"conversants": ALL_WRAPPED_RECORDS + [{"identification": GUEST_RECORD}]}
        with patch.object(convener, "classify_utterance") as mocked:
            events = convener._decide_delegated_utterance(event, conversation)

        self.assertEqual(events, [])
        mocked.assert_not_called()

    def test_private_question_to_a_specialist_is_relayed_privately_not_broadcast(self):
        event = self._utterance_event("tag:human", "ignored -- roundQuestion wins", "what's in the nutrition budget?")
        event.to = convener.To(serviceUrl=convener.AGENTS["nutrition"]["url"], private=True)
        with patch.object(convener, "classify_utterance") as mocked:
            events = convener._decide_delegated_utterance(event, {"conversants": ALL_WRAPPED_RECORDS})

        mocked.assert_not_called()  # the user already chose the recipient
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["nutrition"]["url"])
        relay = events[1]
        self.assertIsInstance(relay, convener.UtteranceEvent)
        self.assertTrue(relay.to.private)
        self.assertEqual(relay.to.serviceUrl, convener.AGENTS["nutrition"]["url"])
        # the user's own utterance, so the private answer goes back to the user
        self.assertEqual(relay.dialogEvent.speakerUri, "tag:human")

    def test_private_question_relay_works_through_handle_envelope_json(self):
        # The delegated copy arrives as plain JSON -- the relay must be
        # rebuilt as a proper dialog event, or openfloor rejects it.
        ident = lambda url, name: {"identification": {"speakerUri": url, "serviceUrl": url, "conversationalName": name,
                                                      "organization": "", "synopsis": ""}}
        nutrition = convener.AGENTS["nutrition"]["url"]
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "c", "conversants": [ident(nutrition, "Nutrition")], "floorGranted": []},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": [{"eventType": "utterance", "to": {"serviceUrl": nutrition, "private": True},
                        "parameters": {"dialogEvent": {"speakerUri": "tag:human", "features": {"text": {"tokens": [{"value": "Confidential"}]}}},
                                       "roundHistory": [], "roundTurnOrder": [], "roundQuestion": "Confidential",
                                       "roundRoutingMode": "", "roundMaxWords": 0}}],
        }}
        events = json.loads(convener.handle_envelope_json(json.dumps(envelope)))["openFloor"]["events"]
        self.assertEqual([e["eventType"] for e in events], ["grantFloor", "utterance"])
        relay = events[1]
        self.assertEqual(relay["to"]["serviceUrl"], nutrition)
        self.assertTrue(relay["to"]["private"])
        self.assertEqual(relay["parameters"]["dialogEvent"]["speakerUri"], "tag:human")
        self.assertEqual(relay["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"], "Confidential")

    def test_a_turn_is_just_the_grant(self):
        events = convener._turn_events("inventory", ALL_RECORDS)
        self.assertEqual([type(e) for e in events], [convener.GrantFloorEvent])
        self.assertEqual(events[0].to.serviceUrl, convener.AGENTS["inventory"]["url"])
        self.assertEqual(convener._turn_events("not-an-agent", ALL_RECORDS), [])

    def test_human_question_addressed_to_a_specialist_is_still_routed(self):
        classification = {"action": "ask_specific_agent", "addressed_agent_key": "nutrition", "agent_keys": []}
        event = self._utterance_event("tag:human", "calories?", "how many calories?")
        event.to = convener.To(serviceUrl=convener.AGENTS["nutrition"]["url"])
        conversation = {"conversants": ALL_WRAPPED_RECORDS + [{"identification": GUEST_RECORD}]}
        with patch.object(convener, "classify_utterance", return_value=classification) as mocked:
            events = convener._decide_delegated_utterance(event, conversation)

        mocked.assert_called_once()
        self.assertIsInstance(events[0], convener.GrantFloorEvent)


class DecideFloorRequestTests(unittest.TestCase):
    """A delegated requestFloor is judged on its reason (OFP 1.1.1 section
    1.19: it "should receive a grantFloor or revokeFloor event in response")."""

    SENTINEL = {"speakerUri": "http://127.0.0.1:8307/", "serviceUrl": "http://127.0.0.1:8307/", "floorGranted": False}

    def _request(self, reason, to=True):
        kwargs = {"reason": reason}
        if to:
            kwargs["to"] = convener.To(speakerUri="http://127.0.0.1:8307/")
        from openfloor.events import RequestFloorEvent
        return RequestFloorEvent(**kwargs)

    def test_a_reported_issue_is_granted(self):
        events = convener._decide_floor_request(self._request("detected an issue: dishes contain severe allergens"), ALL_RECORDS + [self.SENTINEL])
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], convener.GrantFloorEvent)
        self.assertEqual(events[0].to.serviceUrl, "http://127.0.0.1:8307/")

    def test_issue_detected_token_is_granted_however_it_is_worded(self):
        events = convener._decide_floor_request(self._request("@issueDetected Tuesday's dish is unlabeled"), ALL_RECORDS + [self.SENTINEL])
        self.assertIsInstance(events[0], convener.GrantFloorEvent)

    def test_bare_token_with_no_description_is_declined(self):
        events = convener._decide_floor_request(self._request("@issueDetected"), ALL_RECORDS + [self.SENTINEL])
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)

    def test_a_reason_with_no_issue_is_declined(self):
        events = convener._decide_floor_request(self._request("more information to add"), ALL_RECORDS + [self.SENTINEL])
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)
        self.assertIn("declined", events[0].reason)

    def test_no_reason_is_declined(self):
        events = convener._decide_floor_request(self._request(""), ALL_RECORDS + [self.SENTINEL])
        self.assertIsInstance(events[0], convener.RevokeFloorEvent)

    def test_no_requester_means_no_decision(self):
        self.assertEqual(convener._decide_floor_request(self._request("detected an issue", to=False), ALL_RECORDS), [])

    def test_delegated_request_goes_through_handle_envelope_json(self):
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "c", "conversants": [{"identification": {
                "speakerUri": "http://127.0.0.1:8307/", "serviceUrl": "http://127.0.0.1:8307/",
                "conversationalName": "Allergy Sentinel", "organization": "", "synopsis": ""}}]},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": [{"eventType": "requestFloor", "to": {"speakerUri": "http://127.0.0.1:8307/"},
                        "reason": "@issueDetected allergen conflict", "parameters": {"roundHistory": []}}],
        }}
        out = json.loads(convener.handle_envelope_json(json.dumps(envelope)))
        events = out["openFloor"]["events"]
        self.assertEqual([e["eventType"] for e in events], ["grantFloor"])
        self.assertEqual(events[0]["to"]["serviceUrl"], "http://127.0.0.1:8307/")


if __name__ == "__main__":
    unittest.main()
