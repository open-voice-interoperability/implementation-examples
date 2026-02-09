#!/usr/bin/env python3
"""
OpenFloor Gemini Agent

Event handling for a Gemini-backed OpenFloor agent. Utterance processing is
delegated to utterance_handler.py for text-only logic.
"""

import json
import logging
import os

from openfloor.agent import BotAgent
from openfloor.envelope import Envelope, Parameters
from openfloor.events import (
    UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
    ContextEvent
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature

import envelope_handler
import utterance_handler

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
        self.on_context += self._handle_context

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
            if hasattr(event, "parameters"):
                params = event.parameters
                if hasattr(params, "dialogEvent"):
                    dialog_event = params.dialogEvent
                elif isinstance(params, dict) and "dialogEvent" in params:
                    dialog_event = params["dialogEvent"]
                else:
                    dialog_event = params

                if hasattr(dialog_event, "features"):
                    features = dialog_event.features
                elif isinstance(dialog_event, dict) and "features" in dialog_event:
                    features = dialog_event["features"]
                else:
                    return ""

                if isinstance(features, dict) and "text" in features:
                    text_feature = features["text"]
                    if hasattr(text_feature, "tokens"):
                        return " ".join(
                            str(token.value) for token in text_feature.tokens if hasattr(token, "value")
                        )
                    if isinstance(text_feature, dict) and "tokens" in text_feature:
                        return " ".join(
                            str(t.get("value", "")) for t in text_feature["tokens"] if "value" in t
                        )

                if hasattr(features, "__iter__"):
                    for feature in features:
                        if hasattr(feature, "mimeType") and "text" in feature.mimeType:
                            if hasattr(feature, "tokens"):
                                return " ".join(
                                    str(token.value) for token in feature.tokens if hasattr(token, "value")
                                )

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

    def _handle_context(self, event: ContextEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
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
