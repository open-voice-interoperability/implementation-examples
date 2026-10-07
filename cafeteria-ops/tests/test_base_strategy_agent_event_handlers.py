import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import llm_utils
from agents.base_strategy_agent import BaseStrategyAgent
from agents.menu_designer.menu_designer_agent import MenuDesignerAgent
from agents.nutrition_specialist.nutrition_agent import NutritionAgent
from openfloor.events import UtteranceEvent
from openfloor.dialog_event import DialogEvent, TextFeature, Token


class _EchoAgent(BaseStrategyAgent):
    AGENT_NAME = "Echo Test Agent"
    AGENT_PORT = 8399

    def process_utterance(self, user_text: str) -> str:
        return f"echo: {user_text}"


def _make_utterance_event(text: str, speaker_uri: str = "tag:probe,2026:user") -> UtteranceEvent:
    dialog = DialogEvent(
        speakerUri=speaker_uri,
        features={"text": TextFeature(tokens=[Token(value=text)])},
    )
    return UtteranceEvent(dialogEvent=dialog)


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


class _WidgetSpecialist(BaseStrategyAgent):
    """Its AGENT_NAME shares no words with its keyphrases -- the plain case."""

    AGENT_NAME = "Widget Specialist"
    AGENT_PORT = 8395
    AGENT_SYNOPSIS = "Assesses widgets"
    AGENT_KEYPHRASES = ["widget", "gadget"]

    def __init__(self):
        super().__init__()
        self.process_utterance_calls = []

    def process_utterance(self, user_text: str) -> str:
        self.process_utterance_calls.append(user_text)
        return f"widget analysis for: {user_text}"


class _ShoppingListSpecialist(BaseStrategyAgent):
    """AGENT_NAME ("Shopping List Specialist") itself contains the keyphrase
    "shopping list" -- the case that first broke the scope gate: a direct
    address would fast-path straight to "in scope" on its own name."""

    AGENT_NAME = "Shopping List Specialist"
    AGENT_PORT = 8394
    AGENT_SYNOPSIS = "Builds shopping lists"
    AGENT_KEYPHRASES = ["shopping list", "grocery list"]

    def __init__(self):
        super().__init__()
        self.process_utterance_calls = []

    def process_utterance(self, user_text: str) -> str:
        self.process_utterance_calls.append(user_text)
        return f"shopping list for: {user_text}"


class SelfAddressPrefixTests(unittest.TestCase):
    """_self_address_prefix_len decides whether the scope gate runs at all:
    non-zero only when the utterance opens by naming THIS agent."""

    def setUp(self):
        self.agent = _WidgetSpecialist()

    def test_bare_name_with_comma_is_a_self_address(self):
        self.assertGreater(self.agent._self_address_prefix_len("Widget Specialist, is this any good?"), 0)

    def test_ask_the_x_phrasing_is_a_self_address(self):
        self.assertGreater(self.agent._self_address_prefix_len("ask the Widget Specialist about pricing"), 0)

    def test_colon_and_case_insensitive(self):
        self.assertGreater(self.agent._self_address_prefix_len("widget specialist: status?"), 0)

    def test_prefix_length_covers_the_whole_address_clause(self):
        text = "Widget Specialist, rate this."
        self.assertEqual(text[self.agent._self_address_prefix_len(text):], "rate this.")

    def test_a_general_request_is_not_a_self_address(self):
        self.assertEqual(self.agent._self_address_prefix_len("plan five days of cafeteria lunches"), 0)

    def test_another_agents_name_is_not_a_self_address(self):
        self.assertEqual(self.agent._self_address_prefix_len("Nutrition Specialist, how many calories?"), 0)

    def test_name_mid_sentence_is_not_a_self_address(self):
        self.assertEqual(self.agent._self_address_prefix_len("the Widget Specialist should look at this"), 0)


class AloneOnFloorTests(unittest.TestCase):
    """_is_alone_on_floor reads conversation.conversants off the incoming
    envelope, ignoring this agent's own entry."""

    def setUp(self):
        self.agent = _WidgetSpecialist()

    def _envelope(self, conversants):
        return types.SimpleNamespace(conversation=types.SimpleNamespace(id="c1", conversants=conversants))

    def _other(self, uri):
        return types.SimpleNamespace(identification=types.SimpleNamespace(speakerUri=uri, serviceUrl=uri))

    def _me(self):
        return types.SimpleNamespace(
            identification=types.SimpleNamespace(speakerUri=self.agent.speakerUri, serviceUrl=self.agent.serviceUrl)
        )

    def test_no_conversation_section_reads_as_alone(self):
        self.assertTrue(self.agent._is_alone_on_floor(types.SimpleNamespace()))

    def test_empty_roster_reads_as_alone(self):
        self.assertTrue(self.agent._is_alone_on_floor(self._envelope([])))

    def test_roster_of_just_self_reads_as_alone(self):
        self.assertTrue(self.agent._is_alone_on_floor(self._envelope([self._me()])))

    def test_another_conversant_present_is_not_alone(self):
        self.assertFalse(self.agent._is_alone_on_floor(self._envelope([self._me(), self._other("http://127.0.0.1:8302/")])))

    def test_dict_shaped_identification_is_understood(self):
        env = self._envelope([{"identification": {"speakerUri": "http://127.0.0.1:8302/", "serviceUrl": "http://127.0.0.1:8302/"}}])
        self.assertFalse(self.agent._is_alone_on_floor(env))


class ScopeGateTests(unittest.TestCase):
    """The scope gate fires for an utterance that is directly addressed to
    this agent OR is a cold first-turn question with no conversation
    context; an out-of-domain one then gets a decline (alone) or silence
    (others present). A request the agent already has conversation context
    for (a mid-round convener forward) is never gated."""

    def setUp(self):
        self.out_envelope = types.SimpleNamespace(events=[])

    def _envelope(self, conversants=None):
        conversation = types.SimpleNamespace(id="conv-1", conversants=conversants or [])
        return types.SimpleNamespace(conversation=conversation)

    def _roster_with_another_agent(self):
        return [types.SimpleNamespace(identification=types.SimpleNamespace(
            speakerUri="http://127.0.0.1:8302/", serviceUrl="http://127.0.0.1:8302/"))]

    def _reply_text(self, agent):
        if not self.out_envelope.events:
            return None
        return agent._extract_utterance_text(self.out_envelope.events[0])

    def test_direct_address_out_of_scope_alone_declines(self):
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("Widget Specialist, how many calories are in a burrito?")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_called_once()
        self.assertEqual(agent.process_utterance_calls, [])
        self.assertIn("outside what I handle as the Widget Specialist", self._reply_text(agent))

    def test_direct_address_out_of_scope_with_others_present_stays_silent(self):
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("Widget Specialist, how many calories are in a burrito?")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO"):
            agent.bot_on_utterance(event, self._envelope(self._roster_with_another_agent()), self.out_envelope)

        self.assertEqual(agent.process_utterance_calls, [])
        self.assertEqual(self.out_envelope.events, [])

    def test_direct_address_in_scope_is_answered(self):
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("Widget Specialist, what's the burrito situation?")

        with mock.patch.object(llm_utils, "chat_sync", return_value="YES"):
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        self.assertEqual(agent.process_utterance_calls, ["Widget Specialist, what's the burrito situation?"])
        self.assertIn("widget analysis for:", self._reply_text(agent))

    def test_cold_out_of_domain_question_without_a_name_prefix_is_still_gated(self):
        # e.g. "find a supplier for fresh basil" sent straight to the
        # Nutrition Specialist -- no address prefix, no context, wrong agent.
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("find a supplier for fresh basil")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_called_once()
        self.assertEqual(agent.process_utterance_calls, [])
        self.assertIn("outside what I handle as the Widget Specialist", self._reply_text(agent))

    def test_request_is_not_gated_once_the_agent_has_conversation_context(self):
        # A mid-round convener forward: the agent has already observed
        # earlier turns, so even a broad request reaches process_utterance
        # untouched -- the classifier is not consulted.
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        agent._record_conversation_turn("conv-1", "http://127.0.0.1:8301/", "Day 1: Grilled salmon. Day 2: Beef tacos.")
        event = _make_utterance_event("plan five days of cafeteria lunches for about 100 people")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_not_called()
        self.assertEqual(agent.process_utterance_calls, ["plan five days of cafeteria lunches for about 100 people"])
        self.assertIn("widget analysis for:", self._reply_text(agent))

    def test_scope_gate_can_be_disabled(self):
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        agent._enforce_scope_gate = False
        event = _make_utterance_event("Widget Specialist, how many calories are in a burrito?")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_not_called()
        self.assertEqual(agent.process_utterance_calls, ["Widget Specialist, how many calories are in a burrito?"])

    def test_keyphrase_match_does_not_fast_path_past_an_other_domain_signal(self):
        # "menu"/"dishes" are Widget-agnostic here; give the widget agent a
        # keyphrase that a nutrition question happens to contain, and make
        # sure the hard other-domain term ("sodium") still forces the
        # classifier rather than fast-pathing to in-scope.
        class _MenuishAgent(_WidgetSpecialist):
            AGENT_NAME = "Menuish Specialist"
            AGENT_KEYPHRASES = ["menu", "dish", "dishes"]

        agent = _MenuishAgent()
        agent._floor_granted = True
        event = _make_utterance_event("Flag any dishes on this week's menu over 1,000 mg of sodium.")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_called_once()
        self.assertEqual(agent.process_utterance_calls, [])
        self.assertIn("outside what I handle as the Menuish Specialist", self._reply_text(agent))

    def test_agent_name_that_echoes_a_keyphrase_is_still_gated(self):
        # "Shopping List Specialist, ..." must not fast-path to in-scope on
        # its own name -- the address clause is stripped before the keyphrase
        # scan, so the out-of-scope question still reaches the classifier.
        agent = _ShoppingListSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("Shopping List Specialist, give a full nutrition breakdown for mac and cheese.")

        with mock.patch.object(llm_utils, "chat_sync", return_value="NO") as chat:
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        chat.assert_called_once()
        self.assertEqual(agent.process_utterance_calls, [])
        self.assertIn("outside what I handle as the Shopping List Specialist", self._reply_text(agent))

    def test_classifier_failure_fails_open(self):
        # chat_sync never raises -- it returns an error string. That must not
        # read as "NO", so a broken classifier still lets the agent answer.
        agent = _WidgetSpecialist()
        agent._floor_granted = True
        event = _make_utterance_event("Widget Specialist, how is the burrito?")

        with mock.patch.object(llm_utils, "chat_sync", return_value="[LLM call failed: boom]"):
            agent.bot_on_utterance(event, self._envelope(), self.out_envelope)

        self.assertEqual(agent.process_utterance_calls, ["Widget Specialist, how is the burrito?"])


class CrossDomainKeyphraseRegistryRealAgentsTests(unittest.TestCase):
    """Real Menu Designer / Nutrition Specialist regression coverage: a
    question phrased around "a menu" but actually asking for a nutrition
    breakdown (or vice versa) must resolve correctly WITHOUT ever calling
    the LLM classifier -- confirmed live that the classifier itself is
    unreliable on exactly this ambiguous overlap (it says NO for the
    Nutrition Specialist on a "menu"-framed nutrition question no matter how
    the classifier prompt is worded). AGENT_KEYPHRASES_BY_PORT's
    cross-domain check must settle these from each agent's own already-
    curated keyphrases alone."""

    def test_nutrition_question_framed_around_menu_is_declined_by_menu_designer(self):
        # Menu Designer's (tightened) keyphrases don't match this text at
        # all, so it genuinely asks the classifier rather than fast-pathing
        # -- unlike Nutrition's own direction below, the classifier IS
        # reliable this way round, confirmed live.
        agent = MenuDesignerAgent()
        agent._floor_granted = True
        for text in [
            "Is Friday's menu balanced across protein, carbs, and vegetables?",
            "Flag any dishes on this week's menu that are over 1,000 mg of sodium.",
        ]:
            out_envelope = types.SimpleNamespace(events=[])
            event = _make_utterance_event(text)
            with mock.patch.object(llm_utils, "chat_sync", return_value="NO"):
                agent.bot_on_utterance(event, types.SimpleNamespace(), out_envelope)
            reply = agent._extract_utterance_text(out_envelope.events[0]) if out_envelope.events else ""
            self.assertIn("outside what I handle as the Menu Designer", reply, text)

    def test_same_questions_are_answered_by_nutrition_without_calling_the_classifier(self):
        agent = NutritionAgent()
        agent._floor_granted = True
        for text in [
            "Is Friday's menu balanced across protein, carbs, and vegetables?",
            "Flag any dishes on this week's menu that are over 1,000 mg of sodium.",
        ]:
            out_envelope = types.SimpleNamespace(events=[])
            event = _make_utterance_event(text)
            with mock.patch.object(NutritionAgent, "process_utterance", return_value="ok") as process, \
                 mock.patch.object(llm_utils, "chat_sync") as chat:
                agent.bot_on_utterance(event, types.SimpleNamespace(), out_envelope)
            chat.assert_not_called()
            process.assert_called_once_with(text)


if __name__ == "__main__":
    unittest.main()
