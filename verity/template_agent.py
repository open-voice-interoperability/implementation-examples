#!/usr/bin/env python3
"""
OpenFloor-compliant Verity agent based on the agent template.
"""

import json
import logging
import os

from openfloor.agent import BotAgent
from openfloor.envelope import Envelope, Parameters, To
from openfloor.events import (
    UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
    ContextEvent
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature

import utterance_handler

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
        self.on_context += self._handle_context

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
            user_text = self._extract_text_from_utterance_event(event)
            if not user_text:
                logger.debug("[UTTERANCE] No text found in utterance event")
                return

            logger.debug("[UTTERANCE] Received: %s", user_text)

            response_dict = utterance_handler.review_utterance(user_text)
            logger.info("generated %s.", response_dict)

            if response_dict.get("suppress"):
                logger.info("[UTTERANCE] Suppressing response due to conversant count")
                return

            applicable = response_dict.get("applicable")
            self.decision = response_dict.get("decision", "factual")
            if applicable == "no":
                response_text = (
                    "the request was to verify: "
                    + '"'
                    + user_text
                    + '".'
                    + "\n\nHowever, this utterance is neither factual nor fictional. "
                    + response_dict.get("explanation", "")
                )
            else:
                response_text = (
                    "the request was to verify: "
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

    def _extract_text_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
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
                        if hasattr(text_feature, 'tokens'):
                            tokens = text_feature.tokens
                            text_parts = []
                            for token in tokens:
                                if hasattr(token, 'value'):
                                    text_parts.append(str(token.value))
                                elif isinstance(token, dict) and 'value' in token:
                                    text_parts.append(str(token['value']))
                            return ' '.join(text_parts)
                        elif isinstance(text_feature, dict) and 'tokens' in text_feature:
                            tokens = text_feature['tokens']
                            text_parts = [str(t.get('value', '')) for t in tokens if 'value' in t]
                            return ' '.join(text_parts)

                elif hasattr(features, '__iter__'):
                    for feature in features:
                        if hasattr(feature, 'mimeType') and 'text' in feature.mimeType:
                            if hasattr(feature, 'tokens'):
                                tokens = feature.tokens
                                text_parts = [str(token.value) for token in tokens if hasattr(token, 'value')]
                                return ' '.join(text_parts)

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

        if hasattr(event, 'parameters') and hasattr(event.parameters, 'manifests'):
            manifests = event.parameters.manifests
            for manifest in manifests:
                agent_name = manifest.identification.conversationalName if hasattr(manifest, 'identification') else "Unknown"
                logger.debug("[PUBLISH_MANIFESTS] - %s", agent_name)

    def _handle_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[GRANT_FLOOR] Floor granted in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = True

    def _handle_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[REVOKE_FLOOR] Floor revoked in conversation: %s", in_envelope.conversation.id)
        self.grantedFloor = False

    def _handle_yield_floor(self, event: YieldFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        logger.info("[YIELD_FLOOR] Another agent yielded floor in conversation: %s", in_envelope.conversation.id)

    def _handle_context(self, event: ContextEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
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
    identification = Identification(
        speakerUri=ident_data.get('speakerUri', ident_data.get('serviceEndpoint', 'http://localhost:8768/verity')),
        serviceUrl=ident_data.get('serviceUrl', ident_data.get('serviceEndpoint', 'http://localhost:8768/verity')),
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
