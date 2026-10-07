#!/usr/bin/env python3
"""
Base Strategy Agent — OpenFloor Template-Based Implementation

All specialist agents inherit from StrategyBotAgent,
which extends BotAgent (from the OpenFloor template) with Flask integration
and domain-specific processing.

Separation of concerns:
- BotAgent: OpenFloor event routing and lifecycle
- StrategyBotAgent: Domain-agnostic utterance processing + Flask
- Specialist agents: Domain-specific logic via process_utterance()
"""

import base64
import io
import json
import logging
import os
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from html import escape
from typing import Any, Callable, Dict, List

from flask import Flask, request, Response, jsonify
from PIL import Image, ImageDraw, ImageFont

# Make shared modules importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# OpenFloor imports
from openfloor.envelope import Envelope, Parameters, Conversation, Sender
from openfloor.events import (
    UtteranceEvent, InviteEvent, GetManifestsEvent, PublishManifestsEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, Feature, TextFeature, Token

import llm_utils

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

# --- floor-holder / "what I'm working on" progress ---------------------------
#
# A specialist's real work (LLM + MCP lookups) can take 15-45s. Rather than
# leave the user staring at a silent "Working" lamp, the agent can race the
# work against a short deadline: if it finishes fast, the answer comes
# straight back (one round trip, unchanged); if not, the agent returns a
# "floor holder" utterance ("checking the nutrition levels") NOW and the
# gateway re-requests the finished answer with a resume event. The work keeps
# running the whole time -- nothing is recomputed.
#
# OPT-IN: this only works when the gateway (floor_router.py) AND the browser
# client are also updated -- an old gateway forwards the floor-holder as if
# it were the answer. So it defaults OFF; set FLOOR_HOLDER=1 on the agent
# processes once the whole stack has been refreshed.
_FLOOR_HOLDER_ENABLED = os.getenv("FLOOR_HOLDER", "0").strip().lower() in {"1", "true", "yes", "on"}
try:
    _RACE_DEADLINE_S = max(0.2, float(os.getenv("FLOOR_HOLDER_DEADLINE", "1.5")))
except ValueError:
    _RACE_DEADLINE_S = 1.5
# Ceiling for how long the resume request waits for the (already running)
# work to finish. Kept near the gateway's own delivery timeout so a genuinely
# hung process_utterance() can't pin the agent's request thread for minutes.
try:
    _RESUME_RESULT_TIMEOUT_S = max(30.0, float(os.getenv("FLOOR_HOLDER_RESUME_TIMEOUT", "180")))
except ValueError:
    _RESUME_RESULT_TIMEOUT_S = 180.0
_RACE_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="floorrace")

# Feature keys carried on the dialogEvent (features are extensible per the
# OFP dialog-event spec). FLOOR_HOLDER_FEATURE marks an utterance as a
# transient status, not the answer; RESUME_FEATURE marks the gateway's
# follow-up request asking the agent to hand back the finished answer.
FLOOR_HOLDER_FEATURE = "floorHolder"
RESUME_FEATURE = "resumeAfterFloorHolder"

# Port -> display name for this project's own agents, used only to make the
# shared conversation-history transcript (see StrategyBotAgent's
# _record_conversation_turn/_conversation_history_text below) readable --
# a name rather than "http://127.0.0.1:<port>/" in each recorded turn.
# Defined per project in agents/agent_labels.py and hand-kept in sync with
# convener_service/convener.py's AGENTS dict, the same "kept in sync by
# hand" tradeoff as every other cross-agent port reference in these
# projects -- there is no shared package between a convener and the agents
# it addresses.
from agents.agent_labels import AGENT_LABELS_BY_PORT, AGENT_KEYPHRASES_BY_PORT


# Used by StrategyBotAgent._is_in_scope() -- a lightweight YES/NO classifier
# call for the (comparatively rare) utterance that misses every one of an
# agent's own AGENT_KEYPHRASES. Deliberately told to ignore direct address
# ("Shopping List Specialist, ...") since a human or the convener naming this
# agent by name doesn't make an off-topic question this agent's job to answer.
_SCOPE_SYSTEM_PROMPT_TEMPLATE = """You are a strict scope classifier for one specialist agent in a multi-agent \
cafeteria operations system. Decide whether the user's message is something \
THIS specialist should attempt to answer, or whether it clearly belongs to a \
different specialist's area of expertise.

Specialist: {agent_name}
What it does: {synopsis}. {capability_detail}

The message may be directly addressed to this specialist by name -- ignore \
that. Judge only whether the actual content of the request is this \
specialist's domain.

Respond with ONLY one word: YES if this specialist should attempt to answer, \
or NO if the request is clearly about a different domain.
"""


# =============================================================================
# EVENT HOOK PATTERN (from OpenFloor template)
# =============================================================================

class _EventHook:
    """Event hook for registering multiple handlers.

    Mimics a C#-style multicast delegate: use ``+=`` to subscribe a callable
    and ``-=`` to unsubscribe. Calling the hook invokes every registered
    handler in order, so several independent listeners can react to the same
    OpenFloor event.
    """
    def __init__(self):
        # Ordered list of subscribed callbacks; invoked left-to-right.
        self._handlers: List[Callable[..., None]] = []

    def __iadd__(self, handler: Callable[..., None]):
        # Support: hook += handler
        self._handlers.append(handler)
        return self

    def __isub__(self, handler: Callable[..., None]):
        # Support: hook -= handler  (removes every matching reference)
        self._handlers = [existing for existing in self._handlers if existing != handler]
        return self

    def __call__(self, *args, **kwargs):
        # Iterate over a copy so a handler may safely subscribe/unsubscribe
        # while the hook is firing.
        for handler in list(self._handlers):
            handler(*args, **kwargs)


# =============================================================================
# BOT AGENT BASE CLASS (adapted from OpenFloor template)
# =============================================================================

class BotAgent:
    """
    Base class for OpenFloor agents using the template pattern.
    Provides event routing, manifest publishing, and lifecycle management.
    """

    def __init__(self, manifest: Manifest):
        # The manifest describes this agent's identity (speakerUri/serviceUrl)
        # and capabilities; it is published in response to getManifests.
        self._manifest = manifest

        # One hook per OpenFloor event type. Subclasses subscribe their own
        # handlers to these hooks instead of overriding a giant dispatch method.
        self.on_envelope = _EventHook()
        self.on_utterance = _EventHook()
        self.on_invite = _EventHook()
        self.on_uninvite = _EventHook()
        self.on_accept_invite = _EventHook()
        self.on_decline_invite = _EventHook()
        self.on_bye = _EventHook()
        self.on_get_manifests = _EventHook()
        self.on_publish_manifests = _EventHook()
        self.on_request_floor = _EventHook()
        self.on_grant_floor = _EventHook()
        self.on_revoke_floor = _EventHook()
        self.on_yield_floor = _EventHook()

        # Maps an incoming event's eventType string to the matching hook so
        # bot_on_envelope() can route each event without a long if/elif chain.
        self._event_type_to_handler: Dict[str, _EventHook] = {
            "invite": self.on_invite,
            "utterance": self.on_utterance,
            "uninvite": self.on_uninvite,
            "acceptInvite": self.on_accept_invite,
            "declineInvite": self.on_decline_invite,
            "bye": self.on_bye,
            "getManifests": self.on_get_manifests,
            "publishManifests": self.on_publish_manifests,
            "requestFloor": self.on_request_floor,
            "grantFloor": self.on_grant_floor,
            "revokeFloor": self.on_revoke_floor,
            "yieldFloor": self.on_yield_floor,
        }

        # Wire the built-in default handlers. Subclasses add more via +=.
        self.on_envelope += self.bot_on_envelope
        self.on_utterance += self.bot_on_utterance
        self.on_get_manifests += self.bot_on_get_manifests

    @property
    def speakerUri(self) -> str:
        return self._manifest.identification.speakerUri

    @property
    def serviceUrl(self) -> str:
        return self._manifest.identification.serviceUrl

    def process_envelope(self, in_envelope: Envelope) -> Envelope:
        """Process incoming envelope and return response envelope."""
        # Reply on the same conversation so the floor can correlate turns.
        conversation_id = getattr(getattr(in_envelope, "conversation", None), "id", None)
        out_envelope = Envelope(
            conversation=Conversation(id=conversation_id),
            sender=Sender(speakerUri=self.speakerUri, serviceUrl=self.serviceUrl),
        )
        # Firing on_envelope runs bot_on_envelope, which fans each event out
        # to its type-specific hook and appends any responses to out_envelope.
        self.on_envelope(in_envelope, out_envelope)
        return out_envelope

    @staticmethod
    def _normalize_endpoint_id(value: Any) -> str:
        """Normalize an endpoint ID for comparison.

        Strips an optional ``agent:`` prefix, lower-cases, and drops a trailing
        slash so that, e.g., ``Agent:http://Host/`` and ``http://host`` compare
        as equal when matching recipients.
        """
        if value is None:
            return ""
        normalized = str(value).strip().lower()
        if normalized.startswith("agent:"):
            normalized = normalized[6:]
        return normalized.rstrip("/")

    def _is_addressed_to_me(self, event: Any) -> bool:
        """Check if event is addressed to this agent.

        An event with no ``to`` field is treated as a broadcast (addressed to
        everyone). Otherwise it matches when any recipient's speakerUri or
        serviceUrl equals this agent's own, after normalization.
        """
        to_value = getattr(event, "to", None)
        if to_value is None and isinstance(event, dict):
            to_value = event.get("to")
        # No explicit recipient => broadcast => everyone processes it.
        if to_value is None:
            return True

        my_speaker_normalized = self._normalize_endpoint_id(self.speakerUri)
        my_service_normalized = self._normalize_endpoint_id(self.serviceUrl)

        # 'to' may be a single recipient or a list; normalize to a list.
        recipients = to_value if isinstance(to_value, (list, tuple, set)) else [to_value]
        if not recipients:
            return True

        for recipient in recipients:
            # A recipient can be a dict, a bare URI string, or an object.
            if isinstance(recipient, dict):
                to_speaker = recipient.get("speakerUri")
                to_service = recipient.get("serviceUrl")
            elif isinstance(recipient, str):
                to_speaker = recipient
                to_service = recipient
            else:
                to_speaker = getattr(recipient, "speakerUri", None)
                to_service = getattr(recipient, "serviceUrl", None)

            to_speaker_normalized = self._normalize_endpoint_id(to_speaker)
            to_service_normalized = self._normalize_endpoint_id(to_service)

            # Match on either identity field.
            if to_speaker_normalized and to_speaker_normalized == my_speaker_normalized:
                return True
            if to_service_normalized and to_service_normalized == my_service_normalized:
                return True

        return False

    def bot_on_envelope(self, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default envelope handler - routes events to appropriate hooks."""
        for event in getattr(in_envelope, "events", []) or []:
            # Skip events meant for other agents on the floor.
            if not self._is_addressed_to_me(event):
                continue
            # Look up the eventType (attribute on objects, key on dicts)...
            event_type = getattr(event, "eventType", None)
            if not event_type and isinstance(event, dict):
                event_type = event.get("eventType")
            # ...and dispatch to the matching hook if one is registered.
            handler = self._event_type_to_handler.get(event_type)
            if handler is not None:
                handler(event, in_envelope, out_envelope)

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Override in subclasses."""
        pass

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default getManifests handler - publish agent manifest."""
        # Advertise this agent under servicingManifests; we discover no others.
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": []
            }))
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _chart_font(scale: int, size: int) -> "ImageFont.FreeTypeFont":
    # load_default(size=...) is Pillow's bundled, portable scalable font --
    # no dependency on any particular OS having a given font file installed.
    # It has no bold weight, which is deliberate: every label (including the
    # chart title) renders at the same plain weight.
    return ImageFont.load_default(size=size * scale)


def render_bar_chart_png(
    title: str,
    rows: list[tuple[str, int, str, str]],
    *,
    width: int = 400,
    row_h: int = 40,
    top: int = 32,
    label_x: int = 115,
    bar_x: int = 120,
    bar_h: int = 22,
    value_x: int | None = None,
    alt: str = "chart",
) -> str:
    """Render a horizontal bar chart as a base64 PNG <img> tag.

    Draws directly with Pillow instead of building SVG markup: Word's
    HTML-paste pipeline doesn't reliably support SVG data URIs, so an
    embedded chart built that way can fail to render and get replaced with a
    bold broken-image placeholder. A plain PNG pastes as an ordinary picture
    in every consumer (the chat UI, the popup report, and Word), and drawing
    every label at the same plain weight avoids reintroducing bold text.

    rows is (label, bar_width_px, display_text, color) -- callers compute
    bar_width_px themselves (e.g. value / max_value * max_bar_width) since
    the normalization differs per chart. color is any Pillow-recognized
    color string (e.g. "#2196F3"). value_x, if given, draws every display
    text at that fixed x instead of immediately after its own bar.
    """
    if not rows:
        return ""

    height = top + row_h * len(rows) + 8
    scale = 2  # render at 2x and downscale for crisper text/edges
    img = Image.new("RGB", (width * scale, height * scale), "#f8f9fa")
    draw = ImageDraw.Draw(img)
    title_font = _chart_font(scale, 14)
    label_font = _chart_font(scale, 11)

    title_box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((width * scale - (title_box[2] - title_box[0])) / 2, 9 * scale),
        title, font=title_font, fill="#222222",
    )

    for i, (label, bar_w, display, color) in enumerate(rows):
        row_top = (top + i * row_h) * scale
        bar_top = row_top + (row_h * scale - bar_h * scale) // 2
        text_y = bar_top + (bar_h * scale - 11 * scale) // 2

        label_box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (label_x * scale - (label_box[2] - label_box[0]), text_y),
            label, font=label_font, fill="#333333",
        )

        bar_w_px = max(2, bar_w) * scale
        draw.rounded_rectangle(
            [bar_x * scale, bar_top, bar_x * scale + bar_w_px, bar_top + bar_h * scale],
            radius=3 * scale, fill=color,
        )

        value_pos_x = (value_x * scale) if value_x is not None else (bar_x * scale + bar_w_px + 6 * scale)
        draw.text((value_pos_x, text_y), display, font=label_font, fill="#333333")

    img = img.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f'<img src="data:image/png;base64,{encoded}" alt="{alt}">'


def _build_supported_layers(config_value):
    if isinstance(config_value, list):
        return SupportedLayers(input=config_value, output=config_value)
    if isinstance(config_value, dict):
        input_layers = config_value.get("input", ["text"])
        output_layers = config_value.get("output", input_layers)
        return SupportedLayers(input=input_layers, output=output_layers)
    return SupportedLayers(input=["text"], output=["text"])


def load_manifest_from_config(config_path: str) -> Manifest:
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    manifest_data = config.get("manifest", {})
    identification_data = manifest_data.get("identification", {})
    capabilities_data = manifest_data.get("capabilities", {})
    if isinstance(capabilities_data, dict):
        capabilities_data = [capabilities_data]

    capabilities = []
    for capability_data in capabilities_data:
        capabilities.append(
            Capability(
                keyphrases=capability_data.get("keyphrases", []),
                languages=capability_data.get("languages", ["en-us"]),
                descriptions=capability_data.get("descriptions", []),
                supportedLayers=_build_supported_layers(capability_data.get("supportedLayers", ["text"])),
            )
        )

    return Manifest(
        identification=Identification(
            conversationalName=identification_data.get("conversationalName", "StrategyAgent"),
            speakerUri=identification_data.get("speakerUri", identification_data.get("serviceUrl", "http://127.0.0.1:8000/")),
            serviceUrl=identification_data.get("serviceUrl", "http://127.0.0.1:8000/"),
            organization=identification_data.get("organization", "Open Voice Network"),
            role=identification_data.get("role", "assistant"),
            synopsis=identification_data.get("synopsis", "A specialist analysis agent"),
            department=identification_data.get("department"),
            openFloorRoles=identification_data.get("openFloorRoles"),
        ),
        capabilities=capabilities,
    )


# =============================================================================
# STRATEGY BOT AGENT (OpenFloor template-based)
# =============================================================================

class StrategyBotAgent(BotAgent):
    """
    Domain-agnostic BotAgent using OpenFloor template pattern.
    Subclasses override AGENT_* attributes and process_utterance().
    """

    # Override these in subclasses
    AGENT_NAME: str = "StrategyAgent"
    AGENT_PORT: int = 8000
    AGENT_SYNOPSIS: str = "A specialist analysis agent"
    AGENT_KEYPHRASES: list = ["analysis"]
    AGENT_CAPABILITY_DETAIL: str = "Processes inputs and returns a text analysis."
    MAX_RESPONSE_WORDS: int = 50
    # Short present-tense phrase shown to the user while this agent works, if
    # the real answer doesn't come back within the race deadline (see
    # _FLOOR_HOLDER_ENABLED). Override per agent; override working_label()
    # instead for something derived from the request.
    WORKING_LABEL: str = "working on your request"

    def __init__(self):
        # Load or build manifest
        manifest = self._load_manifest()
        super().__init__(manifest)

        # Floor state: invitation does not imply permission to speak.
        # Specialists should only answer after an explicit grantFloor.
        self._floor_granted = False
        # When the gate is enabled (default), utterances received while the
        # floor is revoked are silently ignored. Set ENFORCE_FLOOR_GATE=0 to
        # allow answering direct utterances without a grantFloor first.
        self._enforce_floor_gate = os.getenv("ENFORCE_FLOOR_GATE", "1").strip().lower() in {"1", "true", "yes", "on"}

        # Domain scope gate: an agent addressed directly (convener force-route,
        # or a human/test client naming it) can still receive an utterance
        # that has nothing to do with its expertise -- confirmed live,
        # addressing the Shopping List Specialist with a nutrition question
        # produced a fabricated shopping list instead of a decline. See
        # _is_in_scope(). Set ENFORCE_SCOPE_GATE=0 to disable, e.g. while
        # tuning a new agent's AGENT_KEYPHRASES against real phrasing.
        self._enforce_scope_gate = os.getenv("ENFORCE_SCOPE_GATE", "1").strip().lower() in {"1", "true", "yes", "on"}

        # Effective word budget for the current utterance. Defaults to the class
        # cap but is overridden per-request when the caller (e.g. the convener,
        # driven by the UI slider) supplies a maxWords feature. Subclasses may
        # read this in process_utterance() to size their LLM prompt.
        self._current_max_words = self.MAX_RESPONSE_WORDS

        # Conversation id of the utterance currently being handled -- set
        # right before on_observed_utterance()/process_utterance() run, so a
        # subclass can scope anything it remembers (see on_observed_utterance)
        # to the right conversation instead of leaking across them.
        self._current_conv_id = ""

        # Full-conversation transcript, per conv_id, recorded automatically
        # for EVERY agent (not just ones that opted in with their own
        # on_observed_utterance override) -- see _record_conversation_turn/
        # _conversation_history_text. Set right before process_utterance()
        # runs (self._current_history_text) so any subclass can fold the
        # whole prior conversation into its prompt, not just the one prior
        # utterance a bespoke on_observed_utterance override happened to
        # watch for.
        self._conversation_histories: dict[str, list[tuple[str, str]]] = {}
        self._current_history_text = ""

        # Floor-holder race state: conv_id -> (Future, user_text, max_words)
        # for a request whose work is still running after the race deadline,
        # waiting for the gateway's resume request to collect it. One slot per
        # conversation; the gateway serializes a conversation's round.
        self._pending_futures: dict[str, tuple] = {}
        self._pending_lock = threading.Lock()

        # Backwards compatibility
        self.manifest = manifest

        # Register strategy-specific handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register event handlers for strategy agents."""
        # Utterance is already wired in __init__; we override bot_on_utterance instead
        # Track floor grants/revocations so bot_on_utterance knows whether it
        # is currently allowed to respond.
        self.on_invite += self._handle_invite
        self.on_grant_floor += self._handle_grant_floor
        self.on_revoke_floor += self._handle_revoke_floor
        self.on_uninvite += self._handle_uninvite
        self.on_bye += self._handle_bye
        self.on_yield_floor += self._handle_yield_floor
        self.on_accept_invite += self._handle_accept_invite
        self.on_decline_invite += self._handle_decline_invite
        self.on_publish_manifests += self._handle_publish_manifests
        # requestFloor: no handler -- no code path has a specialist proactively
        # request the floor; meaningful only floor-manager/convener-side.

    def _handle_grant_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Allow subsequent utterance responses after a grantFloor event."""
        self._floor_granted = True
        logger.info("[FLOOR] grantFloor received; responses enabled")

    def _handle_revoke_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Block utterance responses until the next grantFloor event."""
        self._floor_granted = False
        logger.info("[FLOOR] revokeFloor received; responses disabled until grantFloor")

    def _handle_uninvite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Being removed from the conversation implies no floor rights. No reply."""
        self._floor_granted = False
        logger.info("[FLOOR] uninvite received; responses disabled")

    def _handle_bye(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """A conversant is leaving. No reply -- reset our own floor state to be safe."""
        self._floor_granted = False
        logger.info("[FLOOR] bye received; responses disabled")

    def _handle_yield_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Symmetry with grant/revoke; unused by this project's floor manager
        today, but correct if a convener ever sends it directly."""
        self._floor_granted = False
        logger.info("[FLOOR] yieldFloor received; responses disabled")

    def _handle_accept_invite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Pass-Through broadcast about another conversant's invite lifecycle --
        no reason for a specialist to react beyond noting it in the log."""
        logger.info("[FLOOR] acceptInvite observed from another conversant")

    def _handle_decline_invite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Same as acceptInvite: informational only."""
        logger.info("[FLOOR] declineInvite observed from another conversant")

    def _handle_publish_manifests(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """A conversant's manifest broadcast; informational only."""
        logger.info("[FLOOR] publishManifests observed from another conversant")

    def _load_manifest(self) -> Manifest:
        """Load manifest from config or build default."""
        # Look for an agent_config.json sitting next to the specialist's module.
        module = sys.modules.get(self.__class__.__module__)
        module_file = getattr(module, "__file__", "")
        module_dir = os.path.dirname(os.path.abspath(module_file)) if module_file else ""
        config_path = os.path.join(module_dir, "agent_config.json") if module_dir else ""

        if config_path and os.path.exists(config_path):
            manifest = load_manifest_from_config(config_path)
        else:
            # No config file: fall back to attribute-driven defaults.
            manifest = self._default_manifest()

        # Environment variables win over both config and defaults so the same
        # image can be deployed behind different URLs without code changes.
        override_service_url = os.getenv("SERVICE_URL", "").strip()
        override_speaker_uri = os.getenv("SPEAKER_URI", "").strip()
        if override_service_url:
            manifest.identification.serviceUrl = override_service_url
        if override_speaker_uri:
            manifest.identification.speakerUri = override_speaker_uri
        return manifest

    def _default_manifest(self) -> Manifest:
        """Build default manifest."""
        service_url = os.getenv("SERVICE_URL", f"http://127.0.0.1:{self.AGENT_PORT}/")
        speaker_uri = os.getenv("SPEAKER_URI", f"tag:cafeteria-ops,2026:{self.AGENT_NAME.lower().replace(' ', '-')}")
        return Manifest(
            identification=Identification(
                conversationalName=self.AGENT_NAME,
                speakerUri=speaker_uri,
                serviceUrl=service_url,
                organization="Open Voice Network",
                role="assistant",
                synopsis=self.AGENT_SYNOPSIS,
                openFloorRoles={"information": True},
            ),
            capabilities=[Capability(
                keyphrases=self.AGENT_KEYPHRASES,
                languages=["en-us"],
                descriptions=[self.AGENT_SYNOPSIS, self.AGENT_CAPABILITY_DETAIL],
                supportedLayers=SupportedLayers(input=["text"], output=["text"]),
            )],
        )

    _BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
    _ALT_BOLD_PATTERN = re.compile(r"__(.+?)__")
    _HEADER_MARKER = re.compile(r"^[ \t]*#{1,6}[ \t]+")
    _LEADING_LIST_MARKER = re.compile(r"^[ \t]*(?:\d+[.)]|[-*•])[ \t]+")

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Best-effort removal of markdown formatting the model adds despite
        every agent's SYSTEM_PROMPT explicitly asking for plain text --
        confirmed live that the instruction alone ("no markdown, bold, or
        bullets") is not reliably followed even when worded more strongly
        (numbered lists with bold headers still appeared), so this is a
        deterministic cleanup pass rather than relying purely on the
        prompt, matching the project's existing approach of backing a soft
        instruction with real arithmetic/logic wherever it kept failing."""
        if not text:
            return text
        text = BaseStrategyAgent._BOLD_PATTERN.sub(r"\1", text)
        text = BaseStrategyAgent._ALT_BOLD_PATTERN.sub(r"\1", text)
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            line = BaseStrategyAgent._HEADER_MARKER.sub("", line)
            line = BaseStrategyAgent._LEADING_LIST_MARKER.sub("", line)
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    @staticmethod
    def _text_to_html_list(text: str) -> str:
        """Convert a plain-text response where each line is already one
        item (one day, one dish, one ingredient -- the "put each X on its
        own line" convention several agent prompts in this project use
        for the "text" feature) into a real HTML unordered list, for the
        "html" feature shown in the browser's Analysis report popup.
        Returns "" for text with fewer than two lines -- a single-item
        response is plain prose, not a list, and forcing it into one
        <li> would be misleading rather than helpful.

        Runs _strip_markdown first -- confirmed live that without this, a
        numbered-list marker the model added despite the "no numbered
        lists" instruction (e.g. "1. Sirloin Steak: ...") survived into
        each <li>, which is doubly redundant once real <li> bullets are
        already doing that job. bot_on_utterance only ever ran
        _strip_markdown on the "text" feature's own pipeline, never on
        "html" -- calling it here, not at each call site, fixes every
        agent's whole-menu/multi-item response in one place."""
        text = BaseStrategyAgent._strip_markdown(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) < 2:
            return ""
        items = "".join(f"<li>{escape(line)}</li>" for line in lines)
        return f"<ul>{items}</ul>"

    @staticmethod
    def _text_to_html_intro_and_list(text: str) -> str:
        """Like _text_to_html_list, but treats the FIRST line as an
        introductory sentence (rendered as a plain <p>, not bulleted) and
        every line after it as a real list item -- for agents (Inventory,
        Menu Optimization) whose response is normally one holistic
        paragraph but occasionally breaks into an opening framing sentence
        followed by itemized specifics; confirmed live that opening
        sentence was landing as just one more <li>, indistinguishable from
        the specifics below it, even though it isn't one more item of the
        same kind. Same "don't bullet a synthesis line" principle as
        nutrition_agent.py's whole-menu closing note, mirrored at the
        START of the response instead of the end. Returns "" for text with
        fewer than two lines, same convention as _text_to_html_list."""
        text = BaseStrategyAgent._strip_markdown(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) < 2:
            return ""
        intro, *rest = lines
        items = "".join(f"<li>{escape(line)}</li>" for line in rest)
        return f"<p>{escape(intro)}</p><ul>{items}</ul>"

    @staticmethod
    def _limit_words(text: str, max_words: int = 50) -> str:
        """Limit response to max words, extending to the end of the current
        sentence. Preserves the original line breaks between entries (e.g.
        one line per day/dish/ingredient, as several agent prompts in this
        project ask for) instead of collapsing everything to a single
        space-joined blob -- confirmed live that a plain `" ".join(...)`
        over the whole text was silently destroying that formatting even
        when the response was well under budget and no truncation was
        actually needed."""
        if not text:
            return ""
        lines = [ln for ln in text.strip("\n").split("\n")]
        _sentence_end = re.compile(r'[.!?]["\')]*$')

        def _words(line: str) -> list[str]:
            return re.findall(r"\S+", line)

        total_words = sum(len(_words(ln)) for ln in lines)
        if total_words <= max_words:
            return "\n".join(" ".join(_words(ln)) for ln in lines if _words(ln))

        result_lines = []
        words_used = 0
        for line in lines:
            line_words = _words(line)
            if not line_words:
                continue
            if words_used >= max_words:
                break
            remaining = max_words - words_used
            if len(line_words) <= remaining:
                result_lines.append(" ".join(line_words))
                words_used += len(line_words)
                continue
            # This line needs to be cut -- take `remaining` words, then
            # extend to the end of the current sentence (scoped to this one
            # line/entry) just like the old single-block behavior did for
            # the whole text.
            kept = line_words[:remaining]
            if not _sentence_end.search(kept[-1]):
                for word in line_words[remaining:]:
                    kept.append(word)
                    if _sentence_end.search(word):
                        break
            result_lines.append(" ".join(kept))
            break
        return "\n".join(result_lines)

    def process_utterance(self, user_text: str) -> "str | dict":
        """Override in subclasses to implement domain logic.

        May return either a plain string or a dict of the form
        {"text": str, "html": str} when the agent also produces a chart/visual.
        """
        return f"[{self.AGENT_NAME}] received: {user_text}"

    def on_observed_utterance(self, conv_id: str, speaker_uri: str, text: str) -> None:
        """Called for EVERY utterance this agent is shown -- including ones
        it won't reply to itself, because it doesn't currently hold the
        floor. Pass-Through delivery broadcasts a specialist's reply to
        every other registered conversant (see floor_router.py), so an
        agent invited alongside another specialist genuinely does see that
        specialist's answers as they happen, not just its own turns.

        Every observed utterance is ALSO recorded automatically into a
        full per-conversation transcript regardless of whether this hook
        is overridden (see _record_conversation_turn/
        _conversation_history_text, read back via
        self._current_history_text in process_utterance()) -- so every
        agent gets the whole prior conversation with zero setup. Override
        this hook only when a subclass wants something MORE targeted than
        the full transcript -- e.g. Procurement pulling out just Recipe &
        Portion's structured recipe data by watching for its specific
        speaker_uri, rather than re-deriving that from free-text history
        every time. No-op by default. Any exception raised here is caught
        and logged by the caller -- it must never block this agent's own
        floor-gated reply."""
        pass

    # How many recent turns to keep per conversation in
    # _conversation_histories. Bounds prompt size/cost on a long-running
    # conversation rather than growing the transcript without limit; 40
    # comfortably covers a full round-robin sweep (one human request plus
    # every specialist's reply) several times over.
    _MAX_HISTORY_TURNS = 40

    def _speaker_label(self, speaker_uri: str) -> str:
        """A readable label for a conversation-history entry: the known
        agent's display name if speaker_uri resolves to one of this
        project's own agents (matched by port, since every agent here uses
        serviceUrl == speakerUri == "http://127.0.0.1:<port>/"), else
        "User" -- the only other kind of speaker in this system is the
        human operating the browser client, whose speakerUri is
        client-chosen and not one of the fixed agent ports."""
        match = re.search(r":(\d{4,5})/?", speaker_uri or "")
        if match:
            label = AGENT_LABELS_BY_PORT.get(int(match.group(1)))
            if label:
                return label
        return "User"

    def _record_conversation_turn(self, conv_id: str, speaker_uri: str, text: str, label: str | None = None) -> None:
        """Append one turn to this conversation's transcript, trimmed to
        the most recent _MAX_HISTORY_TURNS. Called automatically for every
        utterance this agent observes (see bot_on_utterance) and for its
        own reply -- unlike on_observed_utterance, this always runs and
        needs no subclass override, so every agent gets the full prior
        conversation without having to opt in individually.

        label: explicit override for the recorded speaker label, used when
        recording this agent's own reply (self.AGENT_NAME is always known
        directly, more robust than round-tripping through _speaker_label's
        port-matching on this agent's own speakerUri)."""
        if not conv_id or not text:
            return
        history = self._conversation_histories.setdefault(conv_id, [])
        history.append((label or self._speaker_label(speaker_uri), text))
        if len(history) > self._MAX_HISTORY_TURNS:
            del history[: len(history) - self._MAX_HISTORY_TURNS]

    def _conversation_history_text(self, conv_id: str) -> str:
        """The recorded transcript for one conversation as "Speaker: text"
        lines in chronological order, or "" if nothing has been recorded
        yet (e.g. this is the first utterance in the conversation) --
        ready to drop directly into a prompt. Available to any subclass's
        process_utterance() via self._current_history_text, which is set
        to this same value right before process_utterance() is called."""
        history = self._conversation_histories.get(conv_id) or []
        return "\n".join(f"{label}: {text}" for label, text in history)

    def _history_block(self) -> str:
        """self._current_history_text wrapped as a ready-to-prepend prompt
        section (header + trailing blank line), or "" when there is no
        prior conversation yet (e.g. this is the first utterance) -- so a
        subclass can unconditionally prepend this to its user_message
        without its own empty-history special-casing."""
        if not self._current_history_text:
            return ""
        return f"Prior conversation so far:\n{self._current_history_text}\n\n"

    # Separate from any domain LLM call's own budget -- this is a single
    # YES/NO judgment, not a generation task, so it stays cheap even when the
    # domain call itself runs long.
    _SCOPE_CHECK_TIMEOUT = 12

    # Leading direct address this agent recognises as "you specifically",
    # e.g. "Shopping List Specialist, ..." or "ask the Nutrition Specialist
    # about ...". Mirrors convener_service/convener.py's own
    # detect_addressed_agent start-of-string matching: an explicit address
    # verb ("ask the X ...") needs no trailing punctuation, but a bare
    # leading name does (so a sentence like "Widget Specialist recommends
    # the burrito" isn't mistaken for someone addressing this agent).
    _SELF_ADDRESS_RE_TMPL = (
        r"^\s*(?:"
        r"(?:ask|tell|hey|attention|attn|@)\s+(?:the\s+)?{name}\b[\s,:.!?]*"
        r"|{name}\s*[,:.!?]+\s*"
        r")"
    )

    def _self_address_prefix_len(self, user_text: str) -> int:
        """Length of a leading "<this agent>, " style address on user_text,
        or 0 if the utterance doesn't open by naming this agent."""
        match = re.match(
            self._SELF_ADDRESS_RE_TMPL.format(name=re.escape(self.AGENT_NAME)),
            user_text,
            re.IGNORECASE,
        )
        return match.end() if match else 0

    def _is_in_scope(self, user_text: str) -> bool:
        """Best-effort check that ``user_text`` is actually this agent's domain.

        Called from bot_on_utterance's scope gate, which fires for an
        utterance that directly addresses this agent by name OR is a cold
        first-turn question with no conversation context yet -- a mid-round
        convener forward always carries context (the Menu Designer's
        proposed menu, earlier replies), which is what lets a specialist
        answer a broad "plan five days of lunches" from the menu already on
        the floor without ever reaching this check.

        Fast path: any of AGENT_KEYPHRASES appearing in the text (after the
        "<name>, " address is stripped -- AGENT_NAME itself can echo a
        keyphrase, e.g. "shopping list") is treated as in-scope with no LLM
        call -- UNLESS the text ALSO contains another agent's own keyphrase
        (see AGENT_KEYPHRASES_BY_PORT in agent_labels.py), which is a strong
        "wrong specialist" signal the fast-path must not paper over: e.g.
        "is Friday's menu balanced across protein and carbs" matches the
        Menu Designer's "menu" but also Nutrition's "protein"/"carbs" --
        reusing every agent's own already-curated keyphrase list here (kept
        in sync the same hand-maintained way as AGENT_LABELS_BY_PORT) means
        this stays accurate as those lists evolve, instead of a second,
        separately-maintained "other domains' terms" list silently drifting
        out of date. Only text that misses every keyphrase (or trips that
        other-domain check) pays for an LLM classification call, and
        llm_utils' own chat_sync fails soft (returns an error string, never
        raises) on any timeout/outage -- that string won't start with "NO",
        so a broken classifier fails OPEN. Answering an ambiguous request
        beats going silent because the classifier hiccuped.
        """
        scan_text = user_text[self._self_address_prefix_len(user_text):]
        text_lower = scan_text.lower()
        if any(phrase.lower() in text_lower for phrase in self.AGENT_KEYPHRASES):
            own_keyphrases = {k.lower() for k in self.AGENT_KEYPHRASES}
            other_domain_signal = any(
                phrase.lower() in text_lower
                for port, keyphrases in AGENT_KEYPHRASES_BY_PORT.items()
                if port != self.AGENT_PORT
                for phrase in keyphrases
                if phrase.lower() not in own_keyphrases
            )
            if not other_domain_signal:
                return True

        prompt = _SCOPE_SYSTEM_PROMPT_TEMPLATE.format(
            agent_name=self.AGENT_NAME,
            synopsis=self.AGENT_SYNOPSIS,
            capability_detail=self.AGENT_CAPABILITY_DETAIL,
        )
        # A single YES/NO judgment that fails open. Runs on the lookup tier,
        # not the tiny classifier tier -- confirmed live that llama3.2:1b
        # answers "YES" for a nutrition question addressed to the Menu
        # Designer, where qwen2.5:7b correctly answers "NO".
        verdict = llm_utils.chat_sync(
            prompt, user_text,
            temperature=0,
            timeout=self._SCOPE_CHECK_TIMEOUT,
            ollama_model=llm_utils.LOOKUP_OLLAMA_MODEL,
            openai_model=llm_utils.LOOKUP_LLM_MODEL,
        )
        # Robust to a model that pads the answer: strip leading
        # quotes/markdown/space, then test the first token for "no".
        cleaned = re.sub(r"^[\s\"'`*_.\-]+", "", verdict or "")
        first_token = cleaned.split(None, 1)[0].upper() if cleaned.split() else ""
        return not first_token.startswith("NO")

    def _is_alone_on_floor(self, in_envelope: Envelope) -> bool:
        """True when no OTHER conversant is known to be on this floor.

        Used to decide what an out-of-scope utterance (see _is_in_scope)
        gets back: a decline message when this agent is the only one here
        (there's nobody else to answer it, and silence would look
        indistinguishable from a hang), or no reply at all when other
        conversants are present (one of them presumably can, and every
        specialist chiming in "not my department" would just be floor
        noise on top of whichever one actually answers).

        Reads conversation.conversants off the incoming envelope --
        web-floor's floor_router.py populates this for every agent-facing
        delivery (see _conversants_payload there); a caller that never
        supplies a roster (e.g. the GUI test harness pointed at a single
        agent directly) leaves it empty, which reads as "alone" -- the
        useful default for that kind of isolated, direct test.
        """
        conversants = getattr(getattr(in_envelope, "conversation", None), "conversants", None) or []
        my_speaker = self._normalize_endpoint_id(self.speakerUri)
        my_service = self._normalize_endpoint_id(self.serviceUrl)
        for conversant in conversants:
            identification = self._get_attr(conversant, "identification")
            speaker = self._normalize_endpoint_id(self._get_attr(identification, "speakerUri"))
            service = self._normalize_endpoint_id(self._get_attr(identification, "serviceUrl"))
            is_self = (speaker and speaker == my_speaker) or (service and service == my_service)
            if not is_self:
                return False
        return True

    def _extract_max_words(self, event: UtteranceEvent) -> int:
        """Read an optional ``maxWords`` feature from the utterance.

        The convener forwards the UI slider value as a maxWords feature so the
        specialist can size both its LLM prompt and its truncation. Falls back
        to the class default and clamps to a sane range.
        """
        dialog = self._get_dialog_event(event)
        if not dialog:
            return self.MAX_RESPONSE_WORDS

        features = self._get_attr(dialog, "features")
        if not features:
            return self.MAX_RESPONSE_WORDS

        mw_feature = self._get_attr(features, "maxWords")
        if not mw_feature:
            return self.MAX_RESPONSE_WORDS

        tokens = self._get_attr(mw_feature, "tokens") or []
        if not tokens:
            return self.MAX_RESPONSE_WORDS

        first = tokens[0]
        raw = first if isinstance(first, str) else self._get_attr(first, "value")
        try:
            return max(25, min(1000, int(str(raw).strip())))
        except (ValueError, TypeError):
            return self.MAX_RESPONSE_WORDS

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle utterance events using OpenFloor template pattern."""
        try:
            # Gateway "resume" follow-up after we returned a floor-holder:
            # hand back the answer whose work has been running since the
            # first request. Short-circuits every other step (no re-record,
            # no re-gate -- this is the same logical turn).
            resume_conv_id = self._resume_conv_id(event)
            if resume_conv_id is not None:
                self._finish_pending(resume_conv_id, event, out_envelope)
                return

            # Self-loop guard: never process an utterance this agent itself
            # spoke. _is_addressed_to_me() only checks the `to` recipient --
            # a `to`-less (broadcast) event addressed to nobody in particular
            # passes that check for everyone, including the original speaker,
            # so a client-side rebroadcast (or any other echo) of this
            # agent's own reply would otherwise be answered as a fresh
            # question. Checked by identity by design, independent of
            # whatever upstream mechanism produced the echo.
            speaker_uri = self._get_event_speaker_uri(event)
            if speaker_uri and self._normalize_endpoint_id(speaker_uri) == self._normalize_endpoint_id(self.speakerUri):
                logger.info("[UTTERANCE] Ignored: speaker is this agent itself (self-loop guard)")
                return

            conv_id = ""
            try:
                conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
            except Exception:
                pass
            self._current_conv_id = conv_id

            # Let a subclass observe this utterance regardless of whether
            # it's about to be answered (below) -- e.g. remembering another
            # specialist's broadcast reply to fold into a later prompt. Must
            # never break the floor-gated reply path even if it raises.
            observed_text = self._extract_utterance_text(event)

            # Snapshot the transcript recorded so far -- everything that
            # happened UP TO this utterance, not including it (the
            # utterance itself is passed separately as user_text below) --
            # so process_utterance() sees the full prior conversation via
            # self._current_history_text regardless of whether this
            # specific agent has any bespoke on_observed_utterance override.
            self._current_history_text = self._conversation_history_text(conv_id)

            if observed_text:
                self._record_conversation_turn(conv_id, speaker_uri or "", observed_text)
                try:
                    self.on_observed_utterance(conv_id, speaker_uri or "", observed_text)
                except Exception:
                    logger.exception("[UTTERANCE] on_observed_utterance hook raised")

            # Floor gate: only respond when we currently hold the floor, unless
            # the gate has been explicitly disabled for direct/testing use.
            if not self._floor_granted and self._enforce_floor_gate:
                logger.info("[UTTERANCE] Ignored because floor is revoked (strict floor gate enabled)")
                return
            if not self._floor_granted and not self._enforce_floor_gate:
                logger.info("[UTTERANCE] Floor is revoked, but strict floor gate is disabled; processing direct utterance")

            # Extract text from event
            user_text = self._extract_utterance_text(event)
            if not user_text:
                logger.debug("[UTTERANCE] No text found")
                return

            # Honor a per-request word budget (from the convener/UI slider) for
            # both prompt sizing (subclasses read self._current_max_words) and
            # the final truncation below.
            self._current_max_words = self._extract_max_words(event)

            logger.info("[UTTERANCE] Processing: %s", user_text[:100])

            # Scope gate. Fires when the utterance either (a) directly
            # addresses this agent by name ("Shopping List Specialist, ...")
            # or (b) is a COLD first-turn question with no conversation
            # context yet. A mid-round forward from the convener always
            # carries prior context (the Menu Designer's proposed menu,
            # earlier specialists' replies) -- that's what lets a specialist
            # answer a broad "plan five days of lunches" from the menu
            # already on the floor -- so it is never gated. A bare question
            # with no context, on the other hand, is exactly the "wrong
            # agent" case: e.g. "find a supplier for fresh basil" sent to
            # the Nutrition Specialist.
            has_context = bool((self._current_history_text or "").strip())
            gate = self._enforce_scope_gate and (
                self._self_address_prefix_len(user_text) > 0 or not has_context
            )
            if gate and not self._is_in_scope(user_text):
                if not self._is_alone_on_floor(in_envelope):
                    logger.info(
                        "[SCOPE] Utterance outside %s's expertise; other conversants "
                        "are on the floor, staying silent", self.AGENT_NAME,
                    )
                    return
                logger.info("[SCOPE] Utterance outside %s's expertise; declining instead of answering", self.AGENT_NAME)
                result = (
                    f"That's outside what I handle as the {self.AGENT_NAME} ({self.AGENT_SYNOPSIS}). "
                    "Please direct that to the specialist for this topic instead."
                )
            elif _FLOOR_HOLDER_ENABLED:
                # Race the real work against a short deadline. Fast -> answer
                # now (one round trip, unchanged). Slow -> return a
                # floor-holder status and let the gateway re-request with a
                # resume event; the work keeps running, nothing recomputed.
                future = _RACE_POOL.submit(
                    self._run_processing, user_text,
                    self._current_max_words, self._current_history_text, conv_id,
                )
                try:
                    result = future.result(timeout=_RACE_DEADLINE_S)
                except FuturesTimeout:
                    if future.done():
                        # process_utterance() itself finished right then --
                        # take its value (or let its exception propagate to
                        # the generic handler below), don't treat as a
                        # deadline miss.
                        result = future.result()
                    else:
                        with self._pending_lock:
                            self._pending_futures[conv_id] = (future, user_text, self._current_max_words)
                        self._append_floor_holder(out_envelope, user_text)
                        logger.info(
                            "[FLOOR-HOLDER] %s: work still running after %.1fs; sent status, awaiting resume",
                            self.AGENT_NAME, _RACE_DEADLINE_S,
                        )
                        return
            else:
                # Call domain-specific logic
                result = self.process_utterance(user_text)

            self._emit_answer(result, out_envelope)

        except Exception as e:
            # Never crash the request loop: reply with a generic error utterance.
            logger.exception("[UTTERANCE] Error processing utterance")
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(tokens=[Token(value="Error processing message")])}
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    # -------------------------------------------------------------------------
    # Floor-holder / progress helpers
    # -------------------------------------------------------------------------

    def working_label(self, user_text: str) -> str:
        """A short present-tense phrase shown to the user while this agent
        works, used only if the real answer doesn't come back within the
        race deadline. Default is the class WORKING_LABEL; override for
        something derived from the request (e.g. a day count)."""
        return getattr(self, "WORKING_LABEL", "working on your request")

    def _resume_conv_id(self, event) -> "str | None":
        """The conv_id (possibly "") when `event` is the gateway's resume
        follow-up after a floor-holder, else None."""
        dialog = self._get_dialog_event(event)
        features = self._get_attr(dialog, "features", {}) or {}
        marker = self._get_attr(features, RESUME_FEATURE)
        if marker is None:
            return None
        tokens = self._get_attr(marker, "tokens", []) or []
        for tok in tokens:
            val = tok if isinstance(tok, str) else self._get_attr(tok, "value", "")
            if val:
                return str(val)
        return ""

    def _run_processing(self, user_text: str, max_words: int, history_text: str, conv_id: str):
        """Body of the raced work: restore the request-scoped context a
        subclass's process_utterance() reads off self, then run it. The
        gateway serializes a conversation's round, so nothing else mutates
        these between here and the resume."""
        self._current_max_words = max_words
        self._current_history_text = history_text
        self._current_conv_id = conv_id
        return self.process_utterance(user_text)

    def _append_floor_holder(self, out_envelope: Envelope, user_text: str) -> None:
        """Append a transient status utterance ("checking the nutrition
        levels") flagged so the gateway/client treat it as progress, not the
        answer, and the gateway re-requests with a resume event."""
        try:
            label = self.working_label(user_text) or self.WORKING_LABEL
        except Exception:
            label = self.WORKING_LABEL
        features = {
            "text": TextFeature(tokens=[Token(value=label)]),
            FLOOR_HOLDER_FEATURE: TextFeature(tokens=[Token(value="true")]),
        }
        out_envelope.events.append(UtteranceEvent(
            dialogEvent=DialogEvent(speakerUri=self._manifest.identification.speakerUri, features=features)
        ))

    def _finish_pending(self, conv_id: str, event, out_envelope: Envelope) -> None:
        """Resume handling: hand back the answer whose work started on the
        first request. Recomputes synchronously only if the Future is gone
        (e.g. the agent process restarted between the two requests)."""
        with self._pending_lock:
            entry = self._pending_futures.pop(conv_id, None)
        if entry is not None:
            future, _user_text, max_words = entry
            self._current_conv_id = conv_id
            self._current_max_words = max_words
            try:
                result = future.result(timeout=_RESUME_RESULT_TIMEOUT_S)
            except Exception:
                logger.exception("[FLOOR-HOLDER] raced work failed on resume")
                result = "Error processing message"
        else:
            logger.warning("[FLOOR-HOLDER] no pending work for conv %s on resume; recomputing", conv_id)
            self._current_conv_id = conv_id
            user_text = self._extract_utterance_text(event)
            if not user_text:
                return
            try:
                result = self.process_utterance(user_text)
            except Exception:
                logger.exception("[FLOOR-HOLDER] recompute on resume failed")
                result = "Error processing message"
        self._emit_answer(result, out_envelope)

    def _emit_answer(self, result, out_envelope: Envelope) -> None:
        """Turn a process_utterance() return (str or {"text","html"}) into
        this agent's reply UtteranceEvent -- markdown strip, word budget, and
        recording the turn. Shared by the fast path and by resume."""
        if isinstance(result, dict):
            response_text = self._limit_words(self._strip_markdown(result.get("text", "")), self._current_max_words)
            html_content = (result.get("html") or "").strip()
        else:
            response_text = self._limit_words(self._strip_markdown(str(result)), self._current_max_words)
            html_content = ""

        if not response_text:
            logger.debug("[UTTERANCE] No response generated")
            return

        logger.info("[UTTERANCE] Response: %s", response_text[:100])

        # Record this agent's own reply into the same transcript (the
        # self-loop guard means it never observes its own broadcast the
        # normal way).
        self._record_conversation_turn(self._current_conv_id, self.speakerUri, response_text, label=self.AGENT_NAME)

        features: dict = {"text": TextFeature(tokens=[Token(value=response_text)])}
        if html_content:
            features["html"] = Feature(mimeType="text/html", tokens=[Token(value=html_content)])
        out_envelope.events.append(UtteranceEvent(
            dialogEvent=DialogEvent(speakerUri=self._manifest.identification.speakerUri, features=features)
        ))

    @staticmethod
    def _get_attr(obj, key, default=None):
        """Accessor that works whether obj is a dict, dict-like object, or
        plain attribute object."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        if hasattr(obj, "get"):
            try:
                return obj.get(key, default)
            except Exception:
                pass
        return getattr(obj, key, default)

    def _get_dialog_event(self, event: UtteranceEvent):
        """Extract the dialogEvent from an UtteranceEvent, whether nested as a
        direct attribute or under parameters."""
        dialog = getattr(event, "dialogEvent", None)
        if dialog is None:
            params = getattr(event, "parameters", None)
            if params is not None:
                dialog = getattr(params, "dialogEvent", None)
                if dialog is None and hasattr(params, "get"):
                    dialog = params.get("dialogEvent")
        return dialog

    def _get_event_speaker_uri(self, event: UtteranceEvent) -> str:
        """The speakerUri on an incoming utterance's dialogEvent, i.e. who
        actually said it (may differ from the envelope's own sender when a
        message has been relayed/rebroadcast)."""
        dialog = self._get_dialog_event(event)
        return (self._get_attr(dialog, "speakerUri", "") or "").strip()

    def _extract_utterance_text(self, event: UtteranceEvent) -> str:
        """Extract text from UtteranceEvent."""
        dialog = self._get_dialog_event(event)
        if not dialog:
            return ""

        features = self._get_attr(dialog, "features", {}) or {}
        text_feature = self._get_attr(features, "text")
        if not text_feature:
            return ""

        # Concatenate all token values into the final utterance string.
        tokens = self._get_attr(text_feature, "tokens", []) or []
        return " ".join(
            (self._get_attr(t, "value", "") if not isinstance(t, str) else t)
            for t in tokens
        ).strip()

    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default invite handler - accept invitations."""
        from openfloor.events import AcceptInviteEvent
        # Accepting an invite does NOT grant the floor; reset the gate so we
        # stay silent until an explicit grantFloor arrives.
        self._floor_granted = False
        out_envelope.events.append(AcceptInviteEvent())

    def handle_json_envelope(self, json_payload: str) -> str:
        """
        Handle incoming OpenFloor JSON envelope.
        Parse → Process → Serialize response.
        """
        try:
            in_envelope = Envelope.from_json(json_payload, as_payload=True)
            out_envelope = self.process_envelope(in_envelope)

            # Ensure events list exists
            if not hasattr(out_envelope, "events") or out_envelope.events is None:
                out_envelope.events = []

            return out_envelope.to_json(as_payload=True)
        except Exception as e:
            # On any parse/processing failure, return a well-formed but empty
            # envelope so the caller still receives valid OpenFloor JSON.
            logger.exception("[HANDLE] Error processing envelope")
            error_response = {
                "openFloor": {
                    "schema": {"version": "1.1.0", "url": "https://openvoicenetwork.org/schema"},
                    "conversation": {"id": str(uuid.uuid4())},
                    "sender": {
                        "speakerUri": self._manifest.identification.speakerUri,
                        "serviceUrl": self._manifest.identification.serviceUrl
                    },
                    "events": []
                }
            }
            return json.dumps(error_response)


# =============================================================================
# ALIAS
# =============================================================================

# Specialist agents import BaseStrategyAgent, matching the name used across
# this repo's other OFP example projects (e.g. startup-strategy).
BaseStrategyAgent = StrategyBotAgent


# =============================================================================
# FLASK APP FACTORY
# =============================================================================

def make_flask_app(agent: "StrategyBotAgent") -> Flask:
    """Create Flask app for strategy agent."""
    app = Flask(__name__)

    # Accept OpenFloor envelopes at both the root and a name-based path so the
    # agent works whether it is addressed as "/" or "/agent-name/".
    @app.route("/", methods=["POST"])
    @app.route(f"/{agent.AGENT_NAME.lower().replace(' ', '-')}/", methods=["POST"])
    def handle():
        payload = request.get_data(as_text=True)
        if not payload:
            return Response('{"error":"empty body"}', status=400, mimetype="application/json")

        result = agent.handle_json_envelope(payload)
        return Response(result, status=200, mimetype="application/json")

    @app.route("/manifest", methods=["POST"])
    def manifest():
        # REST convenience endpoint; OFP clients normally use getManifests instead.
        return jsonify(agent._manifest.__json__())

    @app.route("/health", methods=["GET"])
    def health():
        # Simple liveness probe used by the run scripts / load balancer.
        return {"status": "ok", "agent": agent.AGENT_NAME}

    return app
