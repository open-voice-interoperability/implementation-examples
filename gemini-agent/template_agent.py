#!/usr/bin/env python3
"""
OpenFloor Gemini Agent

Event handling for a Gemini-backed OpenFloor agent. Utterance processing is
delegated to utterance_handler.py for text-only logic.
"""

import json
import logging
import os
from typing import Any, Callable, Dict, List

from openfloor.envelope import Envelope, Parameters, Conversation, Sender
from openfloor.events import (
    Event, UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature

import envelope_handler
import utterance_handler


class _EventHook:
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


class BotAgent:
    def __init__(self, manifest: Manifest):
        self._manifest = manifest
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
        conversation_id = getattr(getattr(in_envelope, "conversation", None), "id", None)
        out_envelope = Envelope(
            conversation=Conversation(id=conversation_id),
            sender=Sender(speakerUri=self.speakerUri, serviceUrl=self.serviceUrl),
        )
        self.on_envelope(in_envelope, out_envelope)
        return out_envelope

    @staticmethod
    def _normalize_endpoint_id(value: Any) -> str:
        if value is None:
            return ""
        normalized = str(value).strip().lower()
        if normalized.startswith("agent:"):
            normalized = normalized[6:]
        return normalized.rstrip("/")

    def _is_addressed_to_me(self, event: Any) -> bool:
        to_value = getattr(event, "to", None)
        if to_value is None:
            return True

        if isinstance(to_value, dict):
            to_speaker = to_value.get("speakerUri")
            to_service = to_value.get("serviceUrl")
        else:
            to_speaker = getattr(to_value, "speakerUri", None)
            to_service = getattr(to_value, "serviceUrl", None)

        to_speaker_normalized = self._normalize_endpoint_id(to_speaker)
        to_service_normalized = self._normalize_endpoint_id(to_service)
        my_speaker_normalized = self._normalize_endpoint_id(self.speakerUri)
        my_service_normalized = self._normalize_endpoint_id(self.serviceUrl)

        if to_speaker_normalized and to_speaker_normalized == my_speaker_normalized:
            return True
        if to_service_normalized and to_service_normalized == my_service_normalized:
            return True
        return False

    def bot_on_envelope(self, in_envelope: Envelope, out_envelope: Envelope) -> None:
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
        return

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": []
            }))
        )

logger = logging.getLogger(__name__)


class GeminiAgent(BotAgent):
    """Gemini-backed OpenFloor agent with standard event handling."""

    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None
        self._register_handlers()

    def _register_handlers(self):
        # BotAgent already wires on_utterance to bot_on_utterance.
        self.on_invite += self._handle_invite
        self.on_uninvite += self._handle_uninvite
        self.on_decline_invite += self._handle_decline_invite
        self.on_bye += self._handle_bye
        self.on_publish_manifests += self._handle_publish_manifests
        self.on_grant_floor += self._handle_grant_floor
        self.on_revoke_floor += self._handle_revoke_floor
        self.on_yield_floor += self._handle_yield_floor
        context_handler = getattr(self, "on_context", None)
        if context_handler is not None:
            context_handler += self._handle_context

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Route utterances to the Gemini handler with floor checks."""
        self._handle_utterance(event, in_envelope, out_envelope)

    def _handle_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        if not self.grantedFloor and self.joinedFloor:
            logger.debug("[UTTERANCE] Floor not granted, ignoring")
            return

        try:
            user_text = self._extract_text_from_utterance_event(event)
            if not user_text:
                logger.debug("[UTTERANCE] No text found")
                return

            logger.debug("[UTTERANCE] Received: %s", user_text)

            response_text = utterance_handler.process_utterance(
                user_text,
                agent_name=self._manifest.identification.conversationalName,
            )

            if not response_text:
                logger.debug("[UTTERANCE] No response generated")
                return

            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(values=[response_text])},
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

        except Exception:
            logger.exception("[UTTERANCE] Error processing utterance")
            error_msg = "Sorry, I hit an error while processing that."
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(values=[error_msg])},
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _extract_text_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
            def _tokens_to_text(tokens) -> str:
                if not tokens:
                    return ""
                text_parts = []
                for token in tokens:
                    if hasattr(token, "value"):
                        value = getattr(token, "value", "")
                    elif isinstance(token, dict):
                        value = token.get("value", "")
                    else:
                        value = str(token)
                    if value is not None:
                        text_parts.append(str(value))
                return " ".join(part for part in text_parts if part).strip()

            def _values_to_text(values) -> str:
                if not values:
                    return ""
                text_parts = []
                for value in values:
                    if isinstance(value, dict):
                        value = value.get("value", "")
                    if value is not None:
                        text_parts.append(str(value))
                return " ".join(part for part in text_parts if part).strip()

            def _extract_from_text_feature(text_feature) -> str:
                if text_feature is None:
                    return ""

                if isinstance(text_feature, dict):
                    text = _values_to_text(text_feature.get("values"))
                    if text:
                        return text

                    text = _tokens_to_text(text_feature.get("tokens"))
                    if text:
                        return text

                    nested = text_feature.get("textFeature")
                    if nested is not None:
                        return _extract_from_text_feature(nested)

                else:
                    values_attr = getattr(text_feature, "values", None) if hasattr(text_feature, "values") else None
                    if values_attr is not None and not callable(values_attr):
                        text = _values_to_text(values_attr)
                        if text:
                            return text

                    tokens_attr = getattr(text_feature, "tokens", None) if hasattr(text_feature, "tokens") else None
                    if tokens_attr is not None and not callable(tokens_attr):
                        text = _tokens_to_text(tokens_attr)
                        if text:
                            return text

                    nested_attr = getattr(text_feature, "textFeature", None) if hasattr(text_feature, "textFeature") else None
                    if nested_attr is not None:
                        text = _extract_from_text_feature(nested_attr)
                        if text:
                            return text

                return ""

            dialog_event = None

            if hasattr(event, "dialogEvent") and event.dialogEvent is not None:
                dialog_event = event.dialogEvent
            elif hasattr(event, "parameters"):
                params = event.parameters
                if hasattr(params, "get"):
                    dialog_event = params.get("dialogEvent")
                elif isinstance(params, dict) and "dialogEvent" in params:
                    dialog_event = params["dialogEvent"]
                else:
                    dialog_event = params

            if dialog_event is None:
                return ""

            if hasattr(dialog_event, "features"):
                features = dialog_event.features
            elif hasattr(dialog_event, "get"):
                features = dialog_event.get("features")
            elif isinstance(dialog_event, dict) and "features" in dialog_event:
                features = dialog_event["features"]
            else:
                return ""

            if isinstance(features, dict) and "text" in features:
                text_feature = features["text"]
                text = _extract_from_text_feature(text_feature)
                if text:
                    return text

            if hasattr(features, "__iter__"):
                for feature in features:
                    text = _extract_from_text_feature(feature)
                    if text:
                        return text

            return ""
        except Exception:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""

    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[INVITE] Conversation: %s", in_envelope.conversation.id)

        self.joinedFloor = False
        for evt in in_envelope.events:
            if hasattr(evt, "eventType") and evt.eventType == "joinFloor":
                self.joinedFloor = True
                break

        self.currentConversation = in_envelope.conversation.id

        agent_name = self._manifest.identification.conversationalName
        if self.joinedFloor:
            greeting = f"Hi, I'm {agent_name}. I've joined the floor and I'm ready to help."
        else:
            greeting = f"Hi, I'm {agent_name}. How can I help you today?"

        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[greeting])},
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _handle_uninvite(self, event: UninviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[UNINVITE] Conversation: %s", in_envelope.conversation.id)

        agent_name = self._manifest.identification.conversationalName
        farewell = f"Goodbye from {agent_name}."

        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[farewell])},
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

    def _handle_decline_invite(self, event: DeclineInviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[DECLINE_INVITE] Conversation: %s", in_envelope.conversation.id)

    def _handle_bye(self, event: ByeEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[BYE] Conversation ending: %s", in_envelope.conversation.id)
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope):
        logger.info("[GET_MANIFESTS] Publishing manifest")
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": []
            }))
        )

    def _handle_publish_manifests(self, event: PublishManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[PUBLISH_MANIFESTS] Received manifests")

    def _handle_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[GRANT_FLOOR] Floor granted in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = True

    def _handle_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[REVOKE_FLOOR] Floor revoked in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = False

    def _handle_yield_floor(self, event: YieldFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[YIELD_FLOOR] Another agent yielded floor: %s", in_envelope.conversation.id)

    def _handle_context(self, event: Event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[CONTEXT] Context received in conversation: %s", in_envelope.conversation.id)


def load_manifest_from_config(config_path: str = "agent_config.json") -> Manifest:
    script_dir = os.path.dirname(__file__)
    full_path = os.path.join(script_dir, config_path)

    with open(full_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    manifest_data = config.get("manifest", {})
    ident_data = manifest_data.get("identification", {})
    identification = Identification(
        speakerUri=ident_data.get("speakerUri", ident_data.get("serviceEndpoint", "http://localhost:8769")),
        serviceUrl=ident_data.get("serviceUrl", ident_data.get("serviceEndpoint", "http://localhost:8769")),
        conversationalName=ident_data.get("conversationalName", "GeminiGeo"),
        organization=ident_data.get("organization", "OpenFloor"),
        role=ident_data.get("role", "geography assistant"),
        synopsis=ident_data.get("synopsis", "Conversational front end to the Gemini API"),
    )

    cap_data = manifest_data.get("capabilities", {})
    supported_layers_data = cap_data.get("supportedLayers", ["text"])
    if isinstance(supported_layers_data, list):
        supported_layers = SupportedLayers(input=supported_layers_data, output=supported_layers_data)
    else:
        supported_layers = SupportedLayers(**supported_layers_data) if isinstance(supported_layers_data, dict) else SupportedLayers()

    capabilities = Capability(
        keyphrases=cap_data.get("keyphrases", []),
        descriptions=cap_data.get("descriptions", []),
        languages=cap_data.get("languages", ["en-us"]),
        supportedLayers=supported_layers,
    )

    return Manifest(identification=identification, capabilities=[capabilities])


if __name__ == "__main__":
    print("OpenFloor Gemini Agent")
    print("=" * 50)
    manifest = load_manifest_from_config()
    print(f"Agent: {manifest.identification.conversationalName}")
    print(f"Service URL: {manifest.identification.serviceUrl}")
    print(f"Speaker URI: {manifest.identification.speakerUri}")

    agent = GeminiAgent(manifest)
    print("Agent initialized successfully.")
