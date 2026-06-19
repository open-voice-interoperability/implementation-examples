#!/usr/bin/env python3
"""
Base Strategy Agent — OpenFloor Template-Based Implementation

All startup-strategy specialist agents inherit from StrategyBotAgent,
which extends BotAgent (from the OpenFloor template) with Flask integration
and strategy-specific processing.

Separation of concerns:
- BotAgent: OpenFloor event routing and lifecycle
- StrategyBotAgent: Strategy-specific utterance processing + Flask
- Specialist agents: Domain-specific logic via process_utterance()
"""

import json
import logging
import os
import re
import sys
import uuid
from typing import Any, Callable, Dict, List

from flask import Flask, request, Response, jsonify

# Make shared modules importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# OpenFloor imports
from openfloor.envelope import Envelope, Parameters, Conversation, Sender, Schema, To
from openfloor.events import (
    Event, UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature, Token

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


# =============================================================================
# EVENT HOOK PATTERN (from OpenFloor template)
# =============================================================================

class _EventHook:
    """Event hook for registering multiple handlers."""
    def __init__(self):
        self._handlers: List[Callable[..., None]] = []

    def __iadd__(self, handler: Callable[..., None]):
        self._handlers.append(handler)
        return self

    def __isub__(self, handler: Callable[..., None]):
        self._handlers = [existing for existing in self._handlers if existing != handler]
        return self

    def __call__(self, *args, **kwargs):
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
        self._manifest = manifest
        
        # Event hooks for all OpenFloor event types
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

        # Wire default handlers
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
        conversation_id = getattr(getattr(in_envelope, "conversation", None), "id", None)
        out_envelope = Envelope(
            conversation=Conversation(id=conversation_id),
            sender=Sender(speakerUri=self.speakerUri, serviceUrl=self.serviceUrl),
        )
        self.on_envelope(in_envelope, out_envelope)
        return out_envelope

    @staticmethod
    def _normalize_endpoint_id(value: Any) -> str:
        """Normalize an endpoint ID for comparison."""
        if value is None:
            return ""
        normalized = str(value).strip().lower()
        if normalized.startswith("agent:"):
            normalized = normalized[6:]
        return normalized.rstrip("/")

    def _is_addressed_to_me(self, event: Any) -> bool:
        """Check if event is addressed to this agent."""
        to_value = getattr(event, "to", None)
        if to_value is None and isinstance(event, dict):
            to_value = event.get("to")
        if to_value is None:
            return True

        my_speaker_normalized = self._normalize_endpoint_id(self.speakerUri)
        my_service_normalized = self._normalize_endpoint_id(self.serviceUrl)

        recipients = to_value if isinstance(to_value, (list, tuple, set)) else [to_value]
        if not recipients:
            return True

        for recipient in recipients:
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

            if to_speaker_normalized and to_speaker_normalized == my_speaker_normalized:
                return True
            if to_service_normalized and to_service_normalized == my_service_normalized:
                return True

        return False

    def bot_on_envelope(self, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default envelope handler - routes events to appropriate hooks."""
        for event in getattr(in_envelope, "events", []) or []:
            if not self._is_addressed_to_me(event):
                continue
            event_type = getattr(event, "eventType", None)
            if not event_type and isinstance(event, dict):
                event_type = event.get("eventType")
            handler = self._event_type_to_handler.get(event_type)
            if handler is not None:
                handler(event, in_envelope, out_envelope)

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Override in subclasses."""
        pass

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default getManifests handler - publish agent manifest."""
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": []
            }))
        )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

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
            speakerUri=identification_data.get("speakerUri", identification_data.get("serviceUrl", "http://localhost:8200/")),
            serviceUrl=identification_data.get("serviceUrl", "http://localhost:8200/"),
            organization=identification_data.get("organization", "Open Voice Network"),
            role=identification_data.get("role", "assistant"),
            synopsis=identification_data.get("synopsis", "A startup strategy analysis agent"),
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
    Strategy-specific BotAgent using OpenFloor template pattern.
    Subclasses override AGENT_* attributes and process_utterance().
    """

    # Override these in subclasses
    AGENT_NAME: str = "StrategyAgent"
    AGENT_PORT: int = 8200
    AGENT_SYNOPSIS: str = "A startup strategy analysis agent"
    AGENT_KEYPHRASES: list = ["startup", "strategy", "analysis"]
    AGENT_CAPABILITY_DETAIL: str = "Processes startup strategy inputs and returns a text analysis."
    MAX_RESPONSE_WORDS: int = 50

    def __init__(self):
        # Load or build manifest
        manifest = self._load_manifest()
        super().__init__(manifest)

        # Floor state: respond by default, stop only after explicit revokeFloor.
        self._floor_granted = True
        
        # Backwards compatibility
        self.manifest = manifest
        
        # Register strategy-specific handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register event handlers for strategy agents."""
        # Utterance is already wired in __init__; we override bot_on_utterance instead
        self.on_invite += self._handle_invite
        self.on_grant_floor += self._handle_grant_floor
        self.on_revoke_floor += self._handle_revoke_floor
        # Add other handlers as needed

    def _handle_grant_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Allow subsequent utterance responses after a grantFloor event."""
        self._floor_granted = True
        logger.info("[FLOOR] grantFloor received; responses enabled")

    def _handle_revoke_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Block utterance responses until the next grantFloor event."""
        self._floor_granted = False
        logger.info("[FLOOR] revokeFloor received; responses disabled until grantFloor")

    def _load_manifest(self) -> Manifest:
        """Load manifest from config or build default."""
        module = sys.modules.get(self.__class__.__module__)
        module_file = getattr(module, "__file__", "")
        module_dir = os.path.dirname(os.path.abspath(module_file)) if module_file else ""
        config_path = os.path.join(module_dir, "agent_config.json") if module_dir else ""

        if config_path and os.path.exists(config_path):
            manifest = load_manifest_from_config(config_path)
        else:
            manifest = self._default_manifest()

        # Override with environment variables
        override_service_url = os.getenv("SERVICE_URL", "").strip()
        override_speaker_uri = os.getenv("SPEAKER_URI", "").strip()
        if override_service_url:
            manifest.identification.serviceUrl = override_service_url
        if override_speaker_uri:
            manifest.identification.speakerUri = override_speaker_uri
        return manifest

    def _default_manifest(self) -> Manifest:
        """Build default manifest."""
        service_url = os.getenv("SERVICE_URL", f"http://localhost:{self.AGENT_PORT}/")
        speaker_uri = os.getenv("SPEAKER_URI", f"tag:startup-strategy,2025:{self.AGENT_NAME.lower().replace(' ', '-')}")
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

    @staticmethod
    def _limit_words(text: str, max_words: int = 50) -> str:
        """Limit response to max words."""
        if not text:
            return ""
        words = re.findall(r"\S+", text.strip())
        if len(words) <= max_words:
            return " ".join(words)
        return " ".join(words[:max_words])

    def process_utterance(self, user_text: str) -> str:
        """Override in subclasses to implement domain logic."""
        return f"[{self.AGENT_NAME}] received: {user_text}"

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle utterance events using OpenFloor template pattern."""
        try:
            if not self._floor_granted:
                logger.info("[UTTERANCE] Ignored because floor is revoked")
                return

            # Extract text from event
            user_text = self._extract_utterance_text(event)
            if not user_text:
                logger.debug("[UTTERANCE] No text found")
                return

            logger.info("[UTTERANCE] Processing: %s", user_text[:100])

            # Call domain-specific logic
            response_text = self.process_utterance(user_text)
            response_text = self._limit_words(response_text, self.MAX_RESPONSE_WORDS)

            if not response_text:
                logger.debug("[UTTERANCE] No response generated")
                return

            logger.info("[UTTERANCE] Response: %s", response_text[:100])

            # Build OpenFloor response
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(tokens=[Token(value=response_text)])}
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

        except Exception as e:
            logger.exception("[UTTERANCE] Error processing utterance")
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(tokens=[Token(value="Error processing message")])}
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _extract_utterance_text(self, event: UtteranceEvent) -> str:
        """Extract text from UtteranceEvent."""
        def _get_attr(obj, key, default=None):
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

        dialog = getattr(event, "dialogEvent", None)
        if dialog is None:
            params = getattr(event, "parameters", None)
            if params is not None:
                dialog = getattr(params, "dialogEvent", None)
                if dialog is None and hasattr(params, "get"):
                    dialog = params.get("dialogEvent")

        if not dialog:
            return ""

        features = _get_attr(dialog, "features", {}) or {}
        text_feature = _get_attr(features, "text")
        if not text_feature:
            return ""

        tokens = _get_attr(text_feature, "tokens", []) or []
        return " ".join(
            (_get_attr(t, "value", "") if not isinstance(t, str) else t)
            for t in tokens
        ).strip()

    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Default invite handler - accept invitations."""
        from openfloor.events import AcceptInviteEvent
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
            logger.exception("[HANDLE] Error processing envelope")
            error_response = {
                "openFloor": {
                    "schema": {"version": "1.1", "url": "https://openvoicenetwork.org/schema"},
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
# BACKWARDS COMPATIBILITY ALIAS
# =============================================================================

# For existing specialist agents: alias old class name
BaseStrategyAgent = StrategyBotAgent


# =============================================================================
# KEPT FOR BACKWARDS COMPATIBILITY
# =============================================================================

def _field(obj, key: str, default=None):
    """Deprecated - kept for reference only."""
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


def _parse_incoming_envelope(json_payload: str):
    """Deprecated - kept for reference only."""
    first_error = None
    try:
        return Envelope.from_json(json_payload, as_payload=True)
    except Exception as e:
        first_error = e

    try:
        return Envelope.from_json(json_payload)
    except Exception as e:
        raise ValueError(f"{first_error}; fallback parse failed: {e}")


# =============================================================================
# DEPRECATED CLASS (kept for reference)
# =============================================================================

class BaseStrategyAgent_DEPRECATED:
    """
    DEPRECATED: Use StrategyBotAgent instead.
    This class is kept for reference and will be removed in a future version.
    """

    # Override these in subclasses
    AGENT_NAME: str = "StrategyAgent"
    AGENT_PORT: int = 8200
    AGENT_SYNOPSIS: str = "A startup strategy analysis agent"
    AGENT_KEYPHRASES: list = ["startup", "strategy", "analysis"]
    AGENT_CAPABILITY_DETAIL: str = "Processes startup strategy inputs and returns a text analysis."
    MAX_RESPONSE_WORDS: int = 50

    @staticmethod
    def _limit_words(text: str, max_words: int = 50) -> str:
        if not text:
            return ""
        words = re.findall(r"\S+", text.strip())
        if len(words) <= max_words:
            return " ".join(words)
        return " ".join(words[:max_words])

    def _default_manifest(self) -> Manifest:
        service_url = os.getenv("SERVICE_URL", f"http://localhost:{self.AGENT_PORT}/")
        speaker_uri = os.getenv("SPEAKER_URI", f"tag:startup-strategy,2025:{self.AGENT_NAME.lower().replace(' ', '-')}")
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

    def _load_manifest(self) -> Manifest:
        module = sys.modules.get(self.__class__.__module__)
        module_file = getattr(module, "__file__", "")
        module_dir = os.path.dirname(os.path.abspath(module_file)) if module_file else ""
        config_path = os.path.join(module_dir, "agent_config.json") if module_dir else ""

        manifest = load_manifest_from_config(config_path) if config_path and os.path.exists(config_path) else self._default_manifest()

        override_service_url = os.getenv("SERVICE_URL", "").strip()
        override_speaker_uri = os.getenv("SPEAKER_URI", "").strip()
        if override_service_url:
            manifest.identification.serviceUrl = override_service_url
        if override_speaker_uri:
            manifest.identification.speakerUri = override_speaker_uri
        return manifest

    def __init__(self):
        self.conversation_context: dict = {}
        self.manifest = self._load_manifest()

    def process_utterance(self, user_text: str) -> str:
        """Override this in subclasses."""
        return f"[{self.AGENT_NAME}] received: {user_text}"

    def handle_envelope(self, json_payload: str) -> str:
        try:
            in_envelope = _parse_incoming_envelope(json_payload)
        except Exception as e:
            return json.dumps({"error": f"Invalid envelope: {e}"})

        conv_id = getattr(getattr(in_envelope, "conversation", None), "id", None)
        out_envelope = Envelope(
            conversation=Conversation(id=conv_id),
            sender=Sender(
                speakerUri=self.manifest.identification.speakerUri,
                serviceUrl=self.manifest.identification.serviceUrl,
            ),
            schema=Schema(version="1.1", url="https://openvoicenetwork.org/schema"),
            events=[],
        )

        events = getattr(in_envelope, "events", []) or []
        for event in events:
            event_type = getattr(event, "eventType", None)

            if event_type == "getManifests":
                pub = PublishManifestsEvent()
                pub.manifests = [self.manifest]
                out_envelope.events = [pub]
                break

            elif event_type == "invite":
                from openfloor.events import AcceptInviteEvent
                accept = AcceptInviteEvent()
                out_envelope.events = [accept]
                break

            elif event_type == "utterance":
                dialog = getattr(event, "dialogEvent", None)
                if dialog is None:
                    params = getattr(event, "parameters", None)
                    if params is not None:
                        dialog = getattr(params, "dialogEvent", None)
                        if dialog is None and hasattr(params, "get"):
                            dialog = params.get("dialogEvent")
                user_text = ""
                if dialog:
                    features = _field(dialog, "features", {}) or {}
                    text_feature = _field(features, "text")
                    if text_feature:
                        tokens = _field(text_feature, "tokens", []) or []
                        user_text = " ".join(
                            (_field(t, "value", "") if not isinstance(t, str) else t)
                            for t in tokens
                        )

                response_text = self._limit_words(
                    self.process_utterance(user_text),
                    self.MAX_RESPONSE_WORDS,
                )

                de = DialogEvent(speakerUri=self.manifest.identification.speakerUri)
                tf = TextFeature()
                tf.tokens = [Token(value=response_text)]
                de.features = {"text": tf}
                utt = UtteranceEvent(dialogEvent=de)
                out_envelope.events = [utt]
                break

        if not getattr(out_envelope, "events", None):
            out_envelope.events = []

        return out_envelope.to_json(as_payload=True)


# =============================================================================
# FLASK APP FACTORY
# =============================================================================

def make_flask_app(agent: "StrategyBotAgent") -> Flask:
    """Create Flask app for strategy agent."""
    app = Flask(__name__)

    @app.route("/", methods=["POST"])
    @app.route(f"/{agent.AGENT_NAME.lower().replace(' ', '-')}/", methods=["POST"])
    def handle():
        payload = request.get_data(as_text=True)
        if not payload:
            return Response('{"error":"empty body"}', status=400, mimetype="application/json")
        
        # Support both old and new method names
        if hasattr(agent, 'handle_json_envelope'):
            result = agent.handle_json_envelope(payload)
        else:
            result = agent.handle_envelope(payload)
        return Response(result, status=200, mimetype="application/json")

    @app.route("/manifest", methods=["POST"])
    def manifest():
        return jsonify(agent._manifest.__json__())

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok", "agent": agent.AGENT_NAME}

    return app
