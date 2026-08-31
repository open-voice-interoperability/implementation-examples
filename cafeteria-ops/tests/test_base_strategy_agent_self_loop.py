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
    AGENT_PORT = 8399

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
        event = _make_utterance_event("how many calories?", speaker_uri="tag:someone-else,2026:user")

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, ["how many calories?"])
        self.assertEqual(len(self.out_envelope.events), 1)

    def test_utterance_with_no_speaker_uri_is_processed_normally(self):
        # A missing speakerUri must not be treated as a self-match.
        event = _make_utterance_event("no speaker info here", speaker_uri="")

        self.agent.bot_on_utterance(event, self.in_envelope, self.out_envelope)

        self.assertEqual(self.agent.process_utterance_calls, ["no speaker info here"])
        self.assertEqual(len(self.out_envelope.events), 1)


class _ObservingAgent(BaseStrategyAgent):
    AGENT_NAME = "Observing Test Agent"
    AGENT_PORT = 8398

    def __init__(self):
        super().__init__()
        self.observed = []  # (conv_id, speaker_uri, text)

    def on_observed_utterance(self, conv_id, speaker_uri, text):
        self.observed.append((conv_id, speaker_uri, text))


class _RaisingObserverAgent(BaseStrategyAgent):
    AGENT_NAME = "Raising Observer Test Agent"
    AGENT_PORT = 8397

    def __init__(self):
        super().__init__()
        self.process_utterance_calls = []

    def on_observed_utterance(self, conv_id, speaker_uri, text):
        raise RuntimeError("boom")

    def process_utterance(self, user_text: str) -> str:
        self.process_utterance_calls.append(user_text)
        return f"echo: {user_text}"


class ObservedUtteranceHookTests(unittest.TestCase):
    def setUp(self):
        self.out_envelope = types.SimpleNamespace(events=[])

    def _envelope_for_conv(self, conv_id):
        conversation = types.SimpleNamespace(id=conv_id)
        return types.SimpleNamespace(conversation=conversation)

    def test_fires_even_without_the_floor(self):
        agent = _ObservingAgent()
        agent._floor_granted = False  # deliberately NOT granted
        event = _make_utterance_event("Day 1: Chicken salad.", speaker_uri="http://127.0.0.1:8301/")

        agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(agent.observed, [("conv-1", "http://127.0.0.1:8301/", "Day 1: Chicken salad.")])
        # No floor -- must still not have replied.
        self.assertEqual(self.out_envelope.events, [])

    def test_does_not_fire_for_the_agents_own_utterance(self):
        agent = _ObservingAgent()
        agent._floor_granted = True
        event = _make_utterance_event("hello", speaker_uri=agent.speakerUri)

        agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(agent.observed, [])

    def test_missing_conversation_id_is_empty_string_not_a_crash(self):
        agent = _ObservingAgent()
        agent._floor_granted = False
        event = _make_utterance_event("hi", speaker_uri="http://127.0.0.1:8301/")
        bare_envelope = types.SimpleNamespace()  # no .conversation at all

        agent.bot_on_utterance(event, bare_envelope, self.out_envelope)

        self.assertEqual(agent.observed, [("", "http://127.0.0.1:8301/", "hi")])

    def test_a_raising_hook_does_not_block_the_floor_gated_reply(self):
        agent = _RaisingObserverAgent()
        agent._floor_granted = True
        event = _make_utterance_event("how many calories?", speaker_uri="http://127.0.0.1:8301/")

        agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(agent.process_utterance_calls, ["how many calories?"])
        self.assertEqual(len(self.out_envelope.events), 1)


class LimitWordsTests(unittest.TestCase):
    """_limit_words must preserve the original line breaks between entries
    (e.g. one line per day/dish/ingredient, as several agent prompts in
    this project ask for) rather than collapsing everything with a plain
    `" ".join(...)` -- confirmed live that the old implementation silently
    destroyed multi-line formatting even when well under budget."""

    def test_empty_text_is_empty(self):
        self.assertEqual(BaseStrategyAgent._limit_words("", 50), "")

    def test_under_budget_preserves_line_breaks(self):
        text = "Day 1: Chicken curry.\nDay 2: Lentil soup.\nDay 3: Beef stew."
        result = BaseStrategyAgent._limit_words(text, 50)
        self.assertEqual(result, text)

    def test_under_budget_single_block_has_no_line_breaks(self):
        text = "This is a single-paragraph response with no day labels at all."
        result = BaseStrategyAgent._limit_words(text, 50)
        self.assertEqual(result, text)
        self.assertNotIn("\n", result)

    def test_normalizes_extra_whitespace_within_a_line(self):
        text = "Day 1:   Chicken   curry.\nDay 2: Lentil soup."
        result = BaseStrategyAgent._limit_words(text, 50)
        self.assertEqual(result, "Day 1: Chicken curry.\nDay 2: Lentil soup.")

    def test_truncation_keeps_earlier_full_lines_and_cuts_a_later_one(self):
        text = "Day 1: Chicken curry with rice and vegetables.\nDay 2: Lentil soup with crusty bread and a side salad."
        # Budget covers all of line 1 (7 words) plus a couple words into line 2.
        result = BaseStrategyAgent._limit_words(text, 9)
        lines = result.split("\n")
        self.assertEqual(lines[0], "Day 1: Chicken curry with rice and vegetables.")
        self.assertTrue(lines[1].startswith("Day 2: Lentil soup"))
        # The cut line must still end on a full sentence, not mid-word.
        self.assertTrue(lines[1].rstrip().endswith("."))

    def test_truncation_drops_lines_entirely_past_the_cut(self):
        text = "Day 1: Chicken curry.\nDay 2: Lentil soup.\nDay 3: Beef stew with potatoes and gravy."
        result = BaseStrategyAgent._limit_words(text, 6)
        lines = result.split("\n")
        self.assertEqual(lines, ["Day 1: Chicken curry.", "Day 2: Lentil soup."])

    def test_blank_lines_are_dropped(self):
        text = "Day 1: Chicken curry.\n\nDay 2: Lentil soup."
        result = BaseStrategyAgent._limit_words(text, 50)
        self.assertEqual(result, "Day 1: Chicken curry.\nDay 2: Lentil soup.")


class StripMarkdownTests(unittest.TestCase):
    """Every agent's SYSTEM_PROMPT asks for plain text, but the model
    doesn't reliably comply even when the instruction is worded more
    strongly (confirmed live: numbered lists with bold headers still
    appeared) -- this is a deterministic cleanup pass, not a prompt fix."""

    def test_empty_text_is_unchanged(self):
        self.assertEqual(BaseStrategyAgent._strip_markdown(""), "")

    def test_plain_text_is_unchanged(self):
        text = "Day 1: Chicken curry.\nDay 2: Lentil soup."
        self.assertEqual(BaseStrategyAgent._strip_markdown(text), text)

    def test_strips_double_asterisk_bold(self):
        text = "**Chicken Breast**: shelf life is short."
        self.assertEqual(BaseStrategyAgent._strip_markdown(text), "Chicken Breast: shelf life is short.")

    def test_strips_double_underscore_bold(self):
        text = "__Chicken Breast__: shelf life is short."
        self.assertEqual(BaseStrategyAgent._strip_markdown(text), "Chicken Breast: shelf life is short.")

    def test_strips_numbered_list_markers(self):
        text = "1. Chicken Breast: use within 2 days.\n2. Romaine Lettuce: use within 5 days."
        result = BaseStrategyAgent._strip_markdown(text)
        self.assertEqual(result, "Chicken Breast: use within 2 days.\nRomaine Lettuce: use within 5 days.")

    def test_strips_numbered_list_with_parenthesis_marker(self):
        text = "1) Chicken Breast: use within 2 days."
        self.assertEqual(BaseStrategyAgent._strip_markdown(text), "Chicken Breast: use within 2 days.")

    def test_strips_bullet_markers(self):
        text = "- Chicken Breast: use within 2 days.\n* Romaine Lettuce: use within 5 days.\n• Canned tomatoes: shelf-stable."
        result = BaseStrategyAgent._strip_markdown(text)
        self.assertEqual(
            result,
            "Chicken Breast: use within 2 days.\nRomaine Lettuce: use within 5 days.\nCanned tomatoes: shelf-stable.",
        )

    def test_strips_markdown_headers(self):
        text = "## Par Levels\nChicken breast: 5 days' worth."
        result = BaseStrategyAgent._strip_markdown(text)
        self.assertEqual(result, "Par Levels\nChicken breast: 5 days' worth.")

    def test_combined_numbered_and_bold_header(self):
        text = "1. **Chicken Breast**: shelf life is short.\n2. **Romaine Lettuce**: shelf life is short."
        result = BaseStrategyAgent._strip_markdown(text)
        self.assertEqual(
            result,
            "Chicken Breast: shelf life is short.\nRomaine Lettuce: shelf life is short.",
        )

    def test_does_not_strip_a_leading_negative_number(self):
        # The list-marker regex requires whitespace right after the "-",
        # so "-5 degrees" (no space between "-" and "5") must survive even
        # at the start of a line.
        text = "-5 degrees is the recommended freezer temperature."
        self.assertEqual(BaseStrategyAgent._strip_markdown(text), text)


class TextToHtmlListTests(unittest.TestCase):
    """Several agent prompts already ask for one item per line (one day,
    one dish, one ingredient) in the plain-text "text" feature -- this
    converts that same convention into a real HTML list for the "html"
    feature shown in the browser's Analysis report popup."""

    def test_empty_text_is_empty(self):
        self.assertEqual(BaseStrategyAgent._text_to_html_list(""), "")

    def test_single_line_text_is_not_listified(self):
        # A single-item response is plain prose, not a list -- forcing it
        # into one <li> would be misleading rather than helpful.
        text = "Grilled chicken Caesar salad with garlic bread."
        self.assertEqual(BaseStrategyAgent._text_to_html_list(text), "")

    def test_multi_line_text_becomes_a_real_list(self):
        text = "Day 1: Chicken curry.\nDay 2: Lentil soup."
        result = BaseStrategyAgent._text_to_html_list(text)

        self.assertEqual(result, "<ul><li>Day 1: Chicken curry.</li><li>Day 2: Lentil soup.</li></ul>")

    def test_blank_lines_do_not_count_toward_the_two_line_minimum(self):
        text = "Grilled chicken Caesar salad with garlic bread.\n\n"
        self.assertEqual(BaseStrategyAgent._text_to_html_list(text), "")

    def test_blank_lines_between_items_are_skipped(self):
        text = "Day 1: Chicken curry.\n\nDay 2: Lentil soup."
        result = BaseStrategyAgent._text_to_html_list(text)

        self.assertEqual(result, "<ul><li>Day 1: Chicken curry.</li><li>Day 2: Lentil soup.</li></ul>")

    def test_html_special_characters_are_escaped(self):
        text = "Day 1: Chicken & rice.\nDay 2: <script>alert(1)</script>."
        result = BaseStrategyAgent._text_to_html_list(text)

        self.assertNotIn("<script>", result)
        self.assertIn("&amp;", result)
        self.assertIn("&lt;script&gt;", result)

    def test_leading_numbered_list_markers_are_stripped(self):
        # Confirmed live: despite the "no numbered lists" instruction,
        # the model sometimes adds "1. ", "2. " markers anyway -- doubly
        # redundant once real <li> bullets are already doing that job.
        text = "1. Sirloin Steak: no data available.\n2. Broccoli: no data available."
        result = BaseStrategyAgent._text_to_html_list(text)

        self.assertEqual(
            result,
            "<ul><li>Sirloin Steak: no data available.</li><li>Broccoli: no data available.</li></ul>",
        )

    def test_bold_markdown_is_stripped(self):
        text = "**Sirloin Steak**: no data available.\n**Broccoli**: no data available."
        result = BaseStrategyAgent._text_to_html_list(text)

        self.assertNotIn("**", result)
        self.assertIn("<li>Sirloin Steak: no data available.</li>", result)


class TextToHtmlIntroAndListTests(unittest.TestCase):
    """Inventory and Menu Optimization normally reply with one holistic
    paragraph, but on the occasions the model instead opens with a
    framing sentence before itemized specifics, that opening line must
    stay plain intro text, not get swept into the same bullet list as the
    specifics below it (confirmed live it was landing as just one more
    <li>, indistinguishable from the real items)."""

    def test_empty_text_is_empty(self):
        self.assertEqual(BaseStrategyAgent._text_to_html_intro_and_list(""), "")

    def test_single_line_text_is_not_listified(self):
        text = "Basil spoils fast; keep a tight par level."
        self.assertEqual(BaseStrategyAgent._text_to_html_intro_and_list(text), "")

    def test_first_line_becomes_a_plain_intro_paragraph(self):
        text = "Here is the stock assessment for this week's menu:\nChicken breast: par level 40lb, reorder every 2 days.\nBasil: par level 2lb, reorder daily."
        result = BaseStrategyAgent._text_to_html_intro_and_list(text)

        self.assertEqual(
            result,
            "<p>Here is the stock assessment for this week&#x27;s menu:</p>"
            "<ul><li>Chicken breast: par level 40lb, reorder every 2 days.</li>"
            "<li>Basil: par level 2lb, reorder daily.</li></ul>",
        )

    def test_exactly_two_lines_splits_intro_from_the_single_item(self):
        text = "Overall stock risk is low.\nBasil: par level 2lb, reorder daily."
        result = BaseStrategyAgent._text_to_html_intro_and_list(text)

        self.assertEqual(
            result,
            "<p>Overall stock risk is low.</p><ul><li>Basil: par level 2lb, reorder daily.</li></ul>",
        )

    def test_html_special_characters_are_escaped(self):
        text = "Stock & cost overview:\nMac & cheese: <urgent> reorder."
        result = BaseStrategyAgent._text_to_html_intro_and_list(text)

        self.assertIn("Stock &amp; cost overview:", result)
        self.assertIn("Mac &amp; cheese: &lt;urgent&gt; reorder.", result)

    def test_markdown_is_stripped_from_both_intro_and_items(self):
        text = "**Overview:**\n1. Basil: reorder daily."
        result = BaseStrategyAgent._text_to_html_intro_and_list(text)

        self.assertNotIn("**", result)
        self.assertIn("<p>Overview:</p>", result)
        self.assertIn("<li>Basil: reorder daily.</li>", result)


class _HistoryCapturingAgent(BaseStrategyAgent):
    AGENT_NAME = "History Test Agent"
    AGENT_PORT = 8396

    def __init__(self):
        super().__init__()
        self.captured_history = []

    def process_utterance(self, user_text: str) -> str:
        self.captured_history.append(self._current_history_text)
        return f"reply to: {user_text}"


class ConversationHistoryTests(unittest.TestCase):
    """Every agent automatically accumulates the full prior conversation
    per conv_id (see _record_conversation_turn/_conversation_history_text
    in base_strategy_agent.py), regardless of whether it has its own
    bespoke on_observed_utterance override -- this is what lets a
    subclass like Inventory ground its reasoning in the real menu/
    ingredients other specialists already discussed, not just the raw
    human request."""

    def setUp(self):
        self.out_envelope = types.SimpleNamespace(events=[])

    def _envelope_for_conv(self, conv_id):
        conversation = types.SimpleNamespace(id=conv_id)
        return types.SimpleNamespace(conversation=conversation)

    def test_speaker_label_resolves_a_known_agent_port(self):
        agent = _HistoryCapturingAgent()
        self.assertEqual(agent._speaker_label("http://127.0.0.1:8301/"), "Menu Designer")

    def test_speaker_label_falls_back_to_user_for_an_unknown_speaker(self):
        agent = _HistoryCapturingAgent()
        self.assertEqual(agent._speaker_label("tag:probe.local,2026:user"), "User")
        self.assertEqual(agent._speaker_label(""), "User")

    def test_first_utterance_in_a_conversation_has_no_prior_history(self):
        agent = _HistoryCapturingAgent()
        agent._floor_granted = True
        event = _make_utterance_event("Plan a menu", speaker_uri="tag:probe.local,2026:user")

        agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(agent.captured_history, [""])

    def test_second_turn_sees_the_first_turn_but_not_its_own_pending_utterance(self):
        agent = _HistoryCapturingAgent()
        agent._floor_granted = True
        first = _make_utterance_event("Plan a menu", speaker_uri="tag:probe.local,2026:user")
        agent.bot_on_utterance(first, self._envelope_for_conv("conv-1"), self.out_envelope)

        second = _make_utterance_event("Day 1: Chicken curry.", speaker_uri="http://127.0.0.1:8301/")
        agent.bot_on_utterance(second, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(
            agent.captured_history[1],
            "User: Plan a menu\nHistory Test Agent: reply to: Plan a menu",
        )

    def test_history_is_scoped_per_conversation(self):
        agent = _HistoryCapturingAgent()
        agent._floor_granted = True
        agent.bot_on_utterance(
            _make_utterance_event("hi conv1", speaker_uri="tag:u,2026:user"), self._envelope_for_conv("conv-1"), self.out_envelope
        )
        agent.bot_on_utterance(
            _make_utterance_event("hi conv2", speaker_uri="tag:u,2026:user"), self._envelope_for_conv("conv-2"), self.out_envelope
        )

        self.assertEqual(agent.captured_history[1], "")

    def test_history_is_recorded_even_when_this_agent_does_not_hold_the_floor(self):
        agent = _HistoryCapturingAgent()
        agent._floor_granted = False
        event = _make_utterance_event("Day 1: Chicken curry.", speaker_uri="http://127.0.0.1:8301/")

        agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        self.assertEqual(agent._conversation_history_text("conv-1"), "Menu Designer: Day 1: Chicken curry.")

    def test_history_is_trimmed_to_max_turns(self):
        agent = _HistoryCapturingAgent()
        agent._floor_granted = False
        for i in range(agent._MAX_HISTORY_TURNS + 5):
            event = _make_utterance_event(f"turn {i}", speaker_uri="http://127.0.0.1:8301/")
            agent.bot_on_utterance(event, self._envelope_for_conv("conv-1"), self.out_envelope)

        history = agent._conversation_histories["conv-1"]
        self.assertEqual(len(history), agent._MAX_HISTORY_TURNS)
        self.assertEqual(history[-1], ("Menu Designer", f"turn {agent._MAX_HISTORY_TURNS + 4}"))

    def test_record_conversation_turn_ignores_empty_conv_id_or_text(self):
        agent = _HistoryCapturingAgent()
        agent._record_conversation_turn("", "http://127.0.0.1:8301/", "hello")
        agent._record_conversation_turn("conv-1", "http://127.0.0.1:8301/", "")

        self.assertEqual(agent._conversation_histories, {})

    def test_record_conversation_turn_label_override_wins_over_speaker_uri(self):
        agent = _HistoryCapturingAgent()
        agent._record_conversation_turn("conv-1", "http://127.0.0.1:8301/", "hello", label="Custom Label")

        self.assertEqual(agent._conversation_histories["conv-1"], [("Custom Label", "hello")])


class HistoryBlockTests(unittest.TestCase):
    def test_empty_history_produces_an_empty_block(self):
        agent = _HistoryCapturingAgent()
        agent._current_history_text = ""

        self.assertEqual(agent._history_block(), "")

    def test_non_empty_history_is_wrapped_with_a_header(self):
        agent = _HistoryCapturingAgent()
        agent._current_history_text = "User: hi"

        self.assertEqual(agent._history_block(), "Prior conversation so far:\nUser: hi\n\n")


if __name__ == "__main__":
    unittest.main()
