#!/usr/bin/env python3
"""
OpenFloor Compliant Agent Template (Stella)
"""

import json
import logging
import os

from openfloor.agent import BotAgent
from openfloor.envelope import Envelope, Parameters
from openfloor.events import (
    UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent,
    ContextEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, Feature, TextFeature, Token

import envelope_handler
import utterance_handler

logger = logging.getLogger(__name__)


class TemplateAgent(BotAgent):
    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None
        self._register_handlers()

    def _register_handlers(self):
        self.on_invite += self._handle_invite
        self.on_uninvite += self._handle_uninvite
        self.on_decline_invite += self._handle_decline_invite
        self.on_bye += self._handle_bye
        self.on_publish_manifests += self._handle_publish_manifests
        self.on_grant_floor += self._handle_grant_floor
        self.on_revoke_floor += self._handle_revoke_floor
        self.on_context += self._handle_context

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        self._handle_utterance(event, in_envelope, out_envelope)

    def _handle_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        if not self.grantedFloor and self.joinedFloor:
            logger.debug("[UTTERANCE] Floor not granted, ignoring utterance")
            return

        try:
            user_text = self._extract_text_from_utterance_event(event)
            if not user_text:
                logger.debug("[UTTERANCE] No text found in utterance event")
                return

            response_text = utterance_handler.process_utterance(
                user_text,
                agent_name=self._manifest.identification.conversationalName,
            )
            if not response_text:
                logger.debug("[UTTERANCE] No response generated")
                return

            if self._is_html_response(response_text):
                html_feature = Feature(
                    mimeType="text/html",
                    tokens=[Token(value=response_text)],
                )
                text_feature = TextFeature(values=[self._build_html_summary(user_text)])
                dialog = DialogEvent(
                    speakerUri=self._manifest.identification.speakerUri,
                    features={
                        "text": text_feature,
                        "html": html_feature,
                    },
                )
            else:
                dialog = DialogEvent(
                    speakerUri=self._manifest.identification.speakerUri,
                    features={"text": TextFeature(values=[response_text])},
                )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
        except Exception:
            logger.exception("[UTTERANCE] Error processing utterance")
            error_msg = "I'm sorry, I encountered an error processing your message."
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(values=[error_msg])},
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _extract_text_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
            params = None
            if hasattr(event, "parameters"):
                params = event.parameters
            elif isinstance(event, dict):
                params = event.get("parameters")

            dialog_event = None
            if hasattr(params, "dialogEvent"):
                dialog_event = params.dialogEvent
            elif hasattr(params, "__contains__") and hasattr(params, "get") and "dialogEvent" in params:
                dialog_event = params.get("dialogEvent")
            elif isinstance(params, dict) and "dialogEvent" in params:
                dialog_event = params["dialogEvent"]
            elif isinstance(event, dict) and "dialogEvent" in event:
                dialog_event = event["dialogEvent"]
            else:
                dialog_event = params

            if hasattr(dialog_event, "features"):
                features = dialog_event.features
            elif isinstance(dialog_event, dict) and "features" in dialog_event:
                features = dialog_event["features"]
            else:
                return ""

            if isinstance(features, dict):
                text_feature = features.get("text")
                if text_feature is None:
                    return ""

                if hasattr(text_feature, "tokens"):
                    tokens = text_feature.tokens
                    text_parts = []
                    for token in tokens:
                        if hasattr(token, "value"):
                            text_parts.append(str(token.value))
                        elif isinstance(token, dict) and "value" in token:
                            text_parts.append(str(token["value"]))
                    return " ".join(text_parts)
                if isinstance(text_feature, dict):
                    if "tokens" in text_feature:
                        tokens = text_feature["tokens"]
                        text_parts = [str(t.get("value", "")) for t in tokens if "value" in t]
                        return " ".join(text_parts)
                    if "values" in text_feature:
                        values = text_feature["values"]
                        return " ".join(str(v) for v in values)

            elif hasattr(features, "__iter__"):
                for feature in features:
                    if hasattr(feature, "mimeType") and "text" in feature.mimeType:
                        if hasattr(feature, "tokens"):
                            tokens = feature.tokens
                            text_parts = [str(token.value) for token in tokens if hasattr(token, "value")]
                            return " ".join(text_parts)

            return ""
        except Exception:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""

    def _is_html_response(self, text: str) -> bool:
        if not text:
            return False
        stripped = text.lstrip().lower()
        return stripped.startswith("<!doctype html") or stripped.startswith("<html")

    def _build_html_summary(self, user_text: str) -> str:
        summary = user_text.strip()
        if summary:
            return f"Here is the information you requested about {summary}."
        return "Here is the information you requested."

    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[INVITE] Received invitation to conversation: %s", in_envelope.conversation.id)
        self.joinedFloor = False
        for evt in in_envelope.events:
            if hasattr(evt, "eventType") and evt.eventType == "joinFloor":
                self.joinedFloor = True
                break
        self.currentConversation = in_envelope.conversation.id
        agent_name = self._manifest.identification.conversationalName
        if self.joinedFloor:
            greeting = f"Hi, I'm {agent_name}. I've joined the floor and I'm ready to help!"
        else:
            greeting = f"Hi, I'm {agent_name}. How can I help you today?"
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[greeting])},
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _handle_uninvite(self, event: UninviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[UNINVITE] Received uninvite from conversation: %s", in_envelope.conversation.id)
        agent_name = self._manifest.identification.conversationalName
        farewell = f"Goodbye! {agent_name} is leaving the conversation."
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features=[TextFeature.from_text(farewell)],
        )
        utterance_event = UtteranceEvent.create(dialog)
        out_envelope.events.append(utterance_event)
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

    def _handle_decline_invite(self, event: DeclineInviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[DECLINE_INVITE] Agent declined invitation in conversation: %s", in_envelope.conversation.id)
        if hasattr(event, "parameters") and event.parameters:
            logger.debug("[DECLINE_INVITE] Details: %s", event.parameters)

    def _handle_bye(self, event: ByeEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[BYE] Conversation ending: %s", in_envelope.conversation.id)
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope):
        logger.info("[GET_MANIFESTS] Manifest requested, publishing capabilities")
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": [],
            }))
        )

    def _handle_publish_manifests(self, event: PublishManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[PUBLISH_MANIFESTS] Received manifests from other agents")
        if hasattr(event, "parameters") and hasattr(event.parameters, "manifests"):
            manifests = event.parameters.manifests
            for manifest in manifests:
                agent_name = manifest.identification.conversationalName if hasattr(manifest, "identification") else "Unknown"
                logger.debug("[PUBLISH_MANIFESTS] - %s", agent_name)

    def _handle_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[GRANT_FLOOR] Floor granted in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = True

    def _handle_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[REVOKE_FLOOR] Floor revoked in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = False

    def _handle_context(self, event: ContextEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[CONTEXT] Context received in conversation: %s", in_envelope.conversation.id)
        if hasattr(event, "parameters") and event.parameters:
            logger.debug("[CONTEXT] Context data: %s", event.parameters)


def load_manifest_from_config(config_path: str = "assistant_config.json") -> Manifest:
    script_dir = os.path.dirname(__file__)
    full_path = os.path.join(script_dir, config_path)

    with open(full_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    manifest_data = config.get("manifest", {})

    ident_data = manifest_data.get("identification", {})
    identification = Identification(
        speakerUri=ident_data.get("speakerUri", ident_data.get("serviceEndpoint", "http://localhost:8767")),
        serviceUrl=ident_data.get("serviceUrl", ident_data.get("serviceEndpoint", "http://localhost:8767")),
        conversationalName=ident_data.get("conversationalName", "Stella"),
        organization=ident_data.get("organization", "BeaconForge"),
        role=ident_data.get("role", "assistant"),
        synopsis=ident_data.get("synopsis", "Space assistant"),
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

    return Manifest(
        identification=identification,
        capabilities=[capabilities],
    )


if __name__ == "__main__":
    manifest = load_manifest_from_config()
    agent = TemplateAgent(manifest)
    print("Stella TemplateAgent initialized:", agent)
