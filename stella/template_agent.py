#!/usr/bin/env python3
"""
OpenFloor Compliant Agent Template (Stella)
"""

import json
import logging
import os
from typing import Any, Callable, Dict, List
from urllib.parse import urlparse

from openfloor.envelope import Envelope, Parameters, Conversation, Sender
from openfloor.events import (
    Event, UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, Feature, TextFeature, Token

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

    def _is_addressed_to_me(self, event: Any) -> bool:
        def normalize_uri(value: Any) -> str:
            if value is None:
                return ""
            normalized = str(value).strip()
            if normalized.startswith("agent:"):
                normalized = normalized[len("agent:"):]
            return normalized.rstrip("/").lower()

        to_value = getattr(event, "to", None)
        if to_value is None and isinstance(event, dict):
            to_value = event.get("to")
        if to_value is None:
            return True

        my_speaker = normalize_uri(self.speakerUri)
        my_service = normalize_uri(self.serviceUrl)

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

            target_speaker = normalize_uri(to_speaker)
            target_service = normalize_uri(to_service)

            if target_speaker and target_speaker == my_speaker:
                return True

            if target_service and my_service:
                if target_service == my_service:
                    return True

                try:
                    parsed_target = urlparse(target_service)
                    parsed_me = urlparse(my_service)
                    if (
                        parsed_target.hostname
                        and parsed_me.hostname
                        and parsed_target.hostname == parsed_me.hostname
                        and (parsed_target.port or 80) == (parsed_me.port or 80)
                    ):
                        return True
                except Exception:
                    continue

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
        context_handler = getattr(self, "on_context", None)
        if context_handler is not None:
            context_handler += self._handle_context

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        self._handle_utterance(event, in_envelope, out_envelope)

    def _append_text_utterance(self, out_envelope: Envelope, message: str) -> None:
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[message])},
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def _handle_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        if not self.grantedFloor and self.joinedFloor:
            logger.debug("[UTTERANCE] Floor not granted, ignoring utterance")
            return

        try:
            user_text = self._extract_text_from_utterance_event(event)
            incoming_speaker_uri = (self._extract_speaker_uri_from_utterance_event(event) or "").strip().lower()
            self_speaker_uri = str(self._manifest.identification.speakerUri or "").strip().lower()
            if incoming_speaker_uri and self_speaker_uri and incoming_speaker_uri == self_speaker_uri:
                logger.debug("[UTTERANCE] Ignoring self-originated utterance")
                return
            if not user_text:
                logger.warning("[UTTERANCE] No text found in utterance event")
                self._append_text_utterance(
                    out_envelope,
                    "I couldn't read that message. Please try sending it again.",
                )
                return

            response_text = utterance_handler.process_utterance(
                user_text,
                agent_name=self._manifest.identification.conversationalName,
            )
            if not response_text:
                logger.warning("[UTTERANCE] No response generated for text: %s", user_text)
                self._append_text_utterance(
                    out_envelope,
                    "I couldn't generate a response for that request.",
                )
                return

            responding_to_name = self._resolve_utterance_speaker_name(event, in_envelope)
            response_prefix = f"{responding_to_name}: " if responding_to_name else ""

            if self._is_html_response(response_text):
                html_feature = Feature(
                    mimeType="text/html",
                    tokens=[Token(value=response_text)],
                )
                text_feature = TextFeature(values=[f"{response_prefix}{self._build_html_summary(user_text)}"])
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
                    features={"text": TextFeature(values=[f"{response_prefix}{response_text}"])},
                )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
        except Exception:
            logger.exception("[UTTERANCE] Error processing utterance")
            self._append_text_utterance(
                out_envelope,
                "I'm sorry, I encountered an error processing your message.",
            )

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
            if hasattr(event, "dialogEvent"):
                dialog_event = getattr(event, "dialogEvent", None)
            elif isinstance(event, dict) and "dialogEvent" in event:
                dialog_event = event.get("dialogEvent")

            params = None
            if dialog_event is None:
                if hasattr(event, "parameters"):
                    params = event.parameters
                elif isinstance(event, dict):
                    params = event.get("parameters")

            if dialog_event is None and hasattr(params, "dialogEvent"):
                dialog_event = params.dialogEvent
            elif dialog_event is None and hasattr(params, "__contains__") and hasattr(params, "get") and "dialogEvent" in params:
                dialog_event = params.get("dialogEvent")
            elif dialog_event is None and isinstance(params, dict) and "dialogEvent" in params:
                dialog_event = params["dialogEvent"]
            elif dialog_event is None:
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

                text = _extract_from_text_feature(text_feature)
                if text:
                    return text

            elif hasattr(features, "__iter__"):
                for feature in features:
                    text = _extract_from_text_feature(feature)
                    if text:
                        return text

            return ""
        except Exception:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""

    def _extract_speaker_uri_from_utterance_event(self, event: UtteranceEvent) -> str:
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

            if hasattr(dialog_event, "speakerUri"):
                return getattr(dialog_event, "speakerUri", "") or ""
            if isinstance(dialog_event, dict):
                return dialog_event.get("speakerUri", "") or ""
            return ""
        except Exception:
            return ""

    def _resolve_utterance_speaker_name(self, event: UtteranceEvent, in_envelope: Envelope) -> str:
        speaker_uri = self._extract_speaker_uri_from_utterance_event(event)
        if not speaker_uri:
            return ""
        if "assistantclientconvener" in str(speaker_uri).strip().lower():
            return ""

        conversation = getattr(in_envelope, "conversation", None)
        conversants = getattr(conversation, "conversants", []) if conversation else []

        for conversant in conversants or []:
            identification = getattr(conversant, "identification", None)
            if identification is None and isinstance(conversant, dict):
                identification = conversant.get("identification", {})

            if identification is None:
                continue

            if isinstance(identification, dict):
                conversant_speaker = identification.get("speakerUri")
                conversational_name = identification.get("conversationalName")
            else:
                conversant_speaker = getattr(identification, "speakerUri", None)
                conversational_name = getattr(identification, "conversationalName", None)

            if conversant_speaker and str(conversant_speaker).strip().lower() == str(speaker_uri).strip().lower():
                return conversational_name or speaker_uri

        return speaker_uri

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
            features={"text": TextFeature(values=[farewell])},
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
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

    def _handle_context(self, event: Event, in_envelope: Envelope, out_envelope: Envelope) -> None:
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
    _service_host = os.environ.get('SERVICE_HOST', '').strip()
    _raw_speaker_uri = ident_data.get("speakerUri", ident_data.get("serviceEndpoint", "http://localhost:8767"))
    _raw_service_url = ident_data.get("serviceUrl", ident_data.get("serviceEndpoint", "http://localhost:8767"))
    if _service_host:
        _raw_speaker_uri = _raw_speaker_uri.replace('localhost', _service_host).replace('127.0.0.1', _service_host)
        _raw_service_url = _raw_service_url.replace('localhost', _service_host).replace('127.0.0.1', _service_host)
    identification = Identification(
        speakerUri=_raw_speaker_uri,
        serviceUrl=_raw_service_url,
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
