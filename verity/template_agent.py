#!/usr/bin/env python3
"""
OpenFloor-compliant Verity agent based on the agent template.
"""

import json
import logging
import os
from typing import Any, Callable, Dict, List

from openfloor.envelope import Envelope, Parameters, To, Conversation, Sender
from openfloor.events import (
    Event, UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature

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


def _load_intent_concepts() -> dict:
    my_dir = os.path.dirname(__file__)
    json_file_path = os.path.join(my_dir, 'intentConcepts.json')
    with open(json_file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def search_intent(input_text: str):
    concepts_data = _load_intent_concepts()
    matched_intents = []
    input_text_lower = input_text.lower()

    for concept in concepts_data.get("concepts", []):
        matched_words = [word for word in concept.get("examples", []) if word in input_text_lower]
        if matched_words:
            matched_intents.append({"intent": concept.get("name"), "matched_words": matched_words})

    return matched_intents if matched_intents else None


class TemplateAgent(BotAgent):
    def __init__(self, manifest: Manifest):
        super().__init__(manifest)

        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

        self.is_sentinel = False
        self.invited_sentinel = False
        self.doing_invite = False
        self.decision = "factual"
        self.private = True
        self._conversational_name_cache = {}

        self.on_utterance._handlers = []
        self.on_utterance += self._handle_utterance

        self._register_handlers()
        if hasattr(self, '_event_type_to_handler'):
            self._event_type_to_handler["utterance"] = self._handle_utterance

    def _register_handlers(self):
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
        self._handle_utterance(event, in_envelope, out_envelope)

    def _handle_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[UTTERANCE] Handling utterance event")
        if in_envelope.conversation and in_envelope.conversation.id != self.currentConversation:
            has_invite = any(getattr(e, "eventType", None) == "invite" for e in in_envelope.events)
            if not has_invite:
                self.is_sentinel = False
                self.invited_sentinel = False
                self.doing_invite = False
            self.currentConversation = in_envelope.conversation.id

        try:
            self._cache_conversation_conversants(in_envelope)

            user_text = self._extract_text_from_utterance_event(event)
            incoming_speaker_uri = (self._extract_speaker_uri_from_utterance_event(event) or "").strip().lower()
            self_speaker_uri = str(self._manifest.identification.speakerUri or "").strip().lower()
            if incoming_speaker_uri and self_speaker_uri and incoming_speaker_uri == self_speaker_uri:
                logger.debug("[UTTERANCE] Ignoring self-originated utterance")
                return
            if not user_text:
                logger.debug("[UTTERANCE] No text found in utterance event")
                return

            logger.debug("[UTTERANCE] Received: %s", user_text)

            response_dict = utterance_handler.review_utterance(user_text)
            logger.info("generated %s.", response_dict)

            if response_dict.get("suppress"):
                logger.info("[UTTERANCE] Suppressing response due to conversant count")
                return

            sender_name = self._resolve_sender_conversational_name(event, in_envelope)
            request_prefix = "the request was to verify an utterance: "

            applicable = response_dict.get("applicable")
            self.decision = response_dict.get("decision", "factual")
            if applicable == "no":
                response_text = (
                    request_prefix
                    + '"'
                    + user_text
                    + '".'
                    + "\n\nHowever, this utterance is neither factual nor fictional. "
                    + response_dict.get("explanation", "")
                )
            else:
                response_text = (
                    request_prefix
                    + '"'
                    + user_text
                    + '".'
                    + "\n\nThe utterance is "
                    + self.decision
                    + " with a likelihood of being factual of "
                    + str(response_dict.get("factual_likelihood", "unknown"))
                    + ". "
                    + response_dict.get("explanation", "")
                )

            if sender_name:
                response_text = f"{sender_name}: {response_text}"

            should_reply = (not self.is_sentinel)
            if self.is_sentinel and applicable == "yes" and self.decision == "not factual":
                should_reply = True

            if should_reply:
                self._append_utterance(out_envelope, response_text, in_envelope)
            else:
                if self.is_sentinel and applicable == "no":
                    logger.info("[UTTERANCE] Sentinel active and factuality not applicable; no response sent")
                else:
                    logger.info("[UTTERANCE] Sentinel active and decision is factual; no response sent")
        except Exception:
            logger.exception("[UTTERANCE] Error processing utterance")
            error_text = "I had trouble evaluating that statement."
            self._append_utterance(out_envelope, error_text, in_envelope)

    def _resolve_sender_conversational_name(self, event: UtteranceEvent, in_envelope: Envelope) -> str:
        utterance_speaker_uri = self._extract_speaker_uri_from_utterance_event(event)
        if utterance_speaker_uri and "assistantclientconvener" in str(utterance_speaker_uri).strip().lower():
            return ""

        sender = getattr(in_envelope, "sender", None)
        if isinstance(sender, dict):
            sender_speaker_uri = sender.get("speakerUri")
            sender_service_url = sender.get("serviceUrl")
        else:
            sender_speaker_uri = getattr(sender, "speakerUri", None) if sender else None
            sender_service_url = getattr(sender, "serviceUrl", None) if sender else None

        if sender_speaker_uri and "assistantclientconvener" in str(sender_speaker_uri).strip().lower():
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
                conversant_speaker_uri = identification.get("speakerUri")
                conversant_service_url = identification.get("serviceUrl")
                conversational_name = identification.get("conversationalName")
            else:
                conversant_speaker_uri = getattr(identification, "speakerUri", None)
                conversant_service_url = getattr(identification, "serviceUrl", None)
                conversational_name = getattr(identification, "conversationalName", None)

            matches_sender = (
                (utterance_speaker_uri and self._normalize_agent_key(conversant_speaker_uri) == self._normalize_agent_key(utterance_speaker_uri))
                or (sender_speaker_uri and self._normalize_agent_key(conversant_speaker_uri) == self._normalize_agent_key(sender_speaker_uri))
                or (sender_service_url and self._normalize_agent_key(conversant_service_url) == self._normalize_agent_key(sender_service_url))
            )
            if matches_sender and conversational_name:
                self._cache_conversational_name(conversational_name, conversant_speaker_uri, conversant_service_url)
                return conversational_name

        cached_name = self._lookup_cached_conversational_name(
            utterance_speaker_uri,
            sender_speaker_uri,
            sender_service_url,
        )
        if cached_name:
            return cached_name

        if utterance_speaker_uri:
            return utterance_speaker_uri
        if sender_speaker_uri:
            return sender_speaker_uri
        if sender_service_url:
            return sender_service_url
        return "unknown agent"

    def _normalize_agent_key(self, value) -> str:
        if not value:
            return ""
        return str(value).strip().rstrip('/').lower()

    def _cache_conversational_name(self, conversational_name: str, *keys) -> None:
        if not conversational_name:
            return
        for key in keys:
            normalized = self._normalize_agent_key(key)
            if normalized:
                self._conversational_name_cache[normalized] = conversational_name

    def _lookup_cached_conversational_name(self, *keys) -> str:
        for key in keys:
            normalized = self._normalize_agent_key(key)
            if normalized and normalized in self._conversational_name_cache:
                return self._conversational_name_cache[normalized]
        return ""

    def _cache_conversation_conversants(self, in_envelope: Envelope) -> None:
        conversation = getattr(in_envelope, "conversation", None)
        conversants = getattr(conversation, "conversants", []) if conversation else []

        for conversant in conversants or []:
            identification = getattr(conversant, "identification", None)
            if identification is None and isinstance(conversant, dict):
                identification = conversant.get("identification", {})

            if isinstance(identification, dict):
                self._cache_conversational_name(
                    identification.get("conversationalName"),
                    identification.get("speakerUri"),
                    identification.get("serviceUrl"),
                )
            elif identification is not None:
                self._cache_conversational_name(
                    getattr(identification, "conversationalName", None),
                    getattr(identification, "speakerUri", None),
                    getattr(identification, "serviceUrl", None),
                )

    def _extract_speaker_uri_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
            params = getattr(event, "parameters", None)
            if params is None:
                return ""

            if hasattr(params, "dialogEvent"):
                dialog_event = params.dialogEvent
            elif isinstance(params, dict) and "dialogEvent" in params:
                dialog_event = params.get("dialogEvent")
            elif hasattr(params, "get"):
                dialog_event = params.get("dialogEvent")
            else:
                dialog_event = params

            if isinstance(dialog_event, dict):
                return dialog_event.get("speakerUri", "") or ""
            return getattr(dialog_event, "speakerUri", "") or ""
        except Exception:
            return ""

    def _extract_text_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
            def _tokens_to_text(tokens) -> str:
                if not tokens:
                    return ""
                text_parts = []
                for token in tokens:
                    if hasattr(token, 'value'):
                        value = getattr(token, 'value', '')
                    elif isinstance(token, dict):
                        value = token.get('value', '')
                    else:
                        value = str(token)
                    if value is not None:
                        text_parts.append(str(value))
                return ' '.join(part for part in text_parts if part).strip()

            def _values_to_text(values) -> str:
                if not values:
                    return ""
                text_parts = []
                for value in values:
                    if isinstance(value, dict):
                        value = value.get('value', '')
                    if value is not None:
                        text_parts.append(str(value))
                return ' '.join(part for part in text_parts if part).strip()

            def _extract_from_text_feature(text_feature) -> str:
                if text_feature is None:
                    return ""

                if isinstance(text_feature, dict):
                    text = _values_to_text(text_feature.get('values'))
                    if text:
                        return text

                    text = _tokens_to_text(text_feature.get('tokens'))
                    if text:
                        return text

                    nested = text_feature.get('textFeature')
                    if nested is not None:
                        return _extract_from_text_feature(nested)

                else:
                    values_attr = getattr(text_feature, 'values', None) if hasattr(text_feature, 'values') else None
                    if values_attr is not None and not callable(values_attr):
                        text = _values_to_text(values_attr)
                        if text:
                            return text

                    tokens_attr = getattr(text_feature, 'tokens', None) if hasattr(text_feature, 'tokens') else None
                    if tokens_attr is not None and not callable(tokens_attr):
                        text = _tokens_to_text(tokens_attr)
                        if text:
                            return text

                    nested_attr = getattr(text_feature, 'textFeature', None) if hasattr(text_feature, 'textFeature') else None
                    if nested_attr is not None:
                        text = _extract_from_text_feature(nested_attr)
                        if text:
                            return text

                return ""

            if hasattr(event, 'parameters'):
                params = event.parameters

                if hasattr(params, 'dialogEvent'):
                    dialog_event = params.dialogEvent
                elif isinstance(params, dict) and 'dialogEvent' in params:
                    dialog_event = params['dialogEvent']
                elif hasattr(params, '__contains__') and 'dialogEvent' in params:
                    dialog_event = params.get('dialogEvent')
                else:
                    dialog_event = params

                if hasattr(dialog_event, 'features'):
                    features = dialog_event.features
                elif isinstance(dialog_event, dict) and 'features' in dialog_event:
                    features = dialog_event['features']
                elif hasattr(dialog_event, '__contains__') and 'features' in dialog_event:
                    features = dialog_event.get('features')
                else:
                    return ""

                if isinstance(features, dict):
                    if 'text' in features:
                        text_feature = features['text']
                        text = _extract_from_text_feature(text_feature)
                        if text:
                            return text

                elif hasattr(features, '__iter__'):
                    for feature in features:
                        text = _extract_from_text_feature(feature)
                        if text:
                            return text

            return ""

        except Exception:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""

    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[INVITE] Received invitation to conversation: %s", in_envelope.conversation.id)

        self.joinedFloor = False
        for evt in in_envelope.events:
            if hasattr(evt, 'eventType') and evt.eventType == 'joinFloor':
                self.joinedFloor = True
                logger.info("[INVITE] Joining floor in this conversation")
                break

        self.currentConversation = in_envelope.conversation.id

        utt_event = next((e for e in in_envelope.events if getattr(e, "eventType", None) == "utterance"), None)
        if utt_event:
            utterance_text = self._extract_text_from_utterance_event(utt_event)
            detected_intents = search_intent(utterance_text) or []
            if detected_intents:
                response_text = "ok, i will be a hallucination sentinel in this conversation."
                self.invited_sentinel = True
                self.doing_invite = True
                self.private = True
                self.is_sentinel = True
                self._append_utterance(out_envelope, response_text, in_envelope)
                self.doing_invite = False
                self.invited_sentinel = False
                return

        response_text = "Thanks for the invitation, I am ready to assist."
        self._append_utterance(out_envelope, response_text, in_envelope)

    def _handle_uninvite(self, event: UninviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[UNINVITE] Received uninvite from conversation: %s", in_envelope.conversation.id)

        agent_name = self._manifest.identification.conversationalName
        farewell = f"Goodbye! {agent_name} is leaving the conversation."

        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[farewell])}
        )

        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None

    def _handle_decline_invite(self, event: DeclineInviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[DECLINE_INVITE] Agent declined invitation in conversation: %s", in_envelope.conversation.id)
        if hasattr(event, 'parameters') and event.parameters:
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
                "discoveryManifests": []
            }))
        )

        self._append_utterance(out_envelope, "Thanks for asking, here is my manifest.", in_envelope)

    def _handle_publish_manifests(self, event: PublishManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[PUBLISH_MANIFESTS] Received manifests from other agents")
        params = getattr(event, 'parameters', None)
        manifests = []
        if isinstance(params, dict):
            manifests = params.get('manifests') or params.get('servicingManifests') or []
        elif params is not None:
            manifests = getattr(params, 'manifests', None) or getattr(params, 'servicingManifests', None) or []

        for manifest in manifests:
            identification = getattr(manifest, 'identification', None)
            if identification is None and isinstance(manifest, dict):
                identification = manifest.get('identification', {})

            if isinstance(identification, dict):
                agent_name = identification.get('conversationalName') or "Unknown"
                speaker_uri = identification.get('speakerUri') or identification.get('uri')
                service_url = identification.get('serviceUrl')
            else:
                agent_name = getattr(identification, 'conversationalName', "Unknown") if identification is not None else "Unknown"
                speaker_uri = getattr(identification, 'speakerUri', None) if identification is not None else None
                service_url = getattr(identification, 'serviceUrl', None) if identification is not None else None

            self._cache_conversational_name(agent_name, speaker_uri, service_url)
            logger.debug("[PUBLISH_MANIFESTS] - %s", agent_name)

    def _handle_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[GRANT_FLOOR] Floor granted in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = True

    def _handle_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[REVOKE_FLOOR] Floor revoked in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = False

    def _handle_yield_floor(self, event: YieldFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[YIELD_FLOOR] Another agent yielded floor in conversation: %s", in_envelope.conversation.id)

    def _handle_context(self, event: Event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[CONTEXT] Context received in conversation: %s", in_envelope.conversation.id)
        if hasattr(event, 'parameters') and event.parameters:
            logger.debug("[CONTEXT] Context data: %s", event.parameters)

    def _build_to(self, in_envelope: Envelope) -> To:
        speaker_uri = None
        service_url = None
        if in_envelope.sender:
            speaker_uri = getattr(in_envelope.sender, 'speakerUri', None)
            service_url = getattr(in_envelope.sender, 'serviceUrl', None)

        if speaker_uri:
            return To(speakerUri=speaker_uri, private=self.private)
        if service_url:
            return To(serviceUrl=service_url, private=self.private)
        return None

    def _append_utterance(self, out_envelope: Envelope, response_text: str, in_envelope: Envelope) -> None:
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[response_text])}
        )
        to_obj = self._build_to(in_envelope)
        if to_obj is not None:
            out_envelope.events.append(UtteranceEvent(to=to_obj, dialogEvent=dialog))
        else:
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))


def load_manifest_from_config(config_path: str = "agent_config.json") -> Manifest:
    script_dir = os.path.dirname(__file__)
    full_path = os.path.join(script_dir, config_path)

    with open(full_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    manifest_data = config.get('manifest', {})

    ident_data = manifest_data.get('identification', {})
    _service_host = os.environ.get('SERVICE_HOST', '').strip()
    _raw_speaker_uri = ident_data.get('speakerUri', ident_data.get('serviceEndpoint', 'http://localhost:8768/verity/'))
    _raw_service_url = ident_data.get('serviceUrl', ident_data.get('serviceEndpoint', 'http://localhost:8768/verity/'))
    if _service_host:
        _raw_speaker_uri = _raw_speaker_uri.replace('localhost', _service_host).replace('127.0.0.1', _service_host)
        _raw_service_url = _raw_service_url.replace('localhost', _service_host).replace('127.0.0.1', _service_host)
    identification = Identification(
        speakerUri=_raw_speaker_uri,
        serviceUrl=_raw_service_url,
        conversationalName=ident_data.get('conversationalName', 'Verity'),
        organization=ident_data.get('organization', 'BeaconForge'),
        role=ident_data.get('role', 'detect and mitigate hallucinations'),
        synopsis=ident_data.get('synopsis', 'can detect if statements are correct or not'),
        department=ident_data.get('department')
    )

    cap_data = manifest_data.get('capabilities', {})
    if isinstance(cap_data, list) and cap_data:
        cap_data = cap_data[0]

    supported_layers_data = cap_data.get('supportedLayers', ['text'])
    if isinstance(supported_layers_data, list):
        supported_layers = SupportedLayers(input=supported_layers_data, output=supported_layers_data)
    else:
        supported_layers = SupportedLayers(**supported_layers_data) if isinstance(supported_layers_data, dict) else SupportedLayers()

    capabilities = Capability(
        keyphrases=cap_data.get('keyphrases', []),
        descriptions=cap_data.get('descriptions', []),
        languages=cap_data.get('languages', ['en-us']),
        supportedLayers=supported_layers
    )

    return Manifest(
        identification=identification,
        capabilities=[capabilities]
    )
