#!/usr/bin/env python3
"""
OpenFloor Compliant Agent Template

A complete template for building OpenFloor agents. All OpenFloor events are
fully implemented except for utterance processing, which is delegated to
utterance_handler.py for customization.

This template demonstrates:
- Full OpenFloor protocol compliance
- Proper event handling and routing (this file)
- Envelope parsing/generation (envelope_handler.py)
- Custom conversation logic (utterance_handler.py)
- Manifest publishing and configuration
- Floor management
- Multi-agent conversation support

Architecture:
- template_agent.py: Event handling logic (this file)
- envelope_handler.py: Envelope parsing and JSON serialization
- utterance_handler.py: Custom conversation logic
"""

import json
import logging
import os
from typing import Any, Callable, Dict, List

# Import OpenFloor components
from openfloor.envelope import Envelope, Parameters, Conversation, Sender
from openfloor.events import (
    Event, UtteranceEvent, InviteEvent, UninviteEvent, DeclineInviteEvent,
    ByeEvent, GetManifestsEvent, PublishManifestsEvent,
    RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent, YieldFloorEvent,
)
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.dialog_event import DialogEvent, TextFeature

# Import envelope handling (separated from event handling)
import envelope_handler

# Import the utterance handler (custom logic)
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


class TemplateAgent(BotAgent):
    """
    A template OpenFloor agent with full event handling.
    
    Customize this agent by:
    1. Modifying the manifest in config.json
    2. Implementing your utterance logic in utterance_handler.py
    3. Optionally customizing other event handlers as needed
    """
    
    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        
        # Agent state management
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None
        
        # Register event handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all OpenFloor event handlers."""
        # NOTE: BotAgent already wires `on_utterance` to `bot_on_utterance`.
        # We override `bot_on_utterance` in this class, so we do not register an
        # additional utterance handler here (avoids double-responses).
        self.on_invite += self._handle_invite
        self.on_uninvite += self._handle_uninvite
        self.on_decline_invite += self._handle_decline_invite
        self.on_bye += self._handle_bye
        # Note: get_manifests is handled by overriding bot_on_get_manifests method below
        self.on_publish_manifests += self._handle_publish_manifests
        # Note: request_floor is sent BY agents TO Floor Managers, not received by agents
        self.on_grant_floor += self._handle_grant_floor
        self.on_revoke_floor += self._handle_revoke_floor
        self.on_yield_floor += self._handle_yield_floor
        context_handler = getattr(self, "on_context", None)
        if context_handler is not None:
            context_handler += self._handle_context
    
    # =========================================================================
    # UTTERANCE EVENT - Delegated to utterance_handler.py
    # =========================================================================

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Override BotAgent default utterance behavior.

        The base `BotAgent` implementation always emits a stub utterance.
        We route utterances through the template handler which respects floor state.
        """
        self._handle_utterance(event, in_envelope, out_envelope)
    
    def _handle_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle utterance event - user input processing.
        
        This method handles all OpenFloor event parsing and envelope construction.
        The utterance_handler.py only processes text-to-text logic.
        """
        # Check if floor has been revoked (agent shouldn't speak)
        if not self.grantedFloor and self.joinedFloor:
            logger.debug("[UTTERANCE] Floor not granted, ignoring utterance")
            return
        
        try:
            # Extract user text from the OpenFloor event
            user_text = self._extract_text_from_utterance_event(event)
            
            if not user_text:
                logger.debug("[UTTERANCE] No text found in utterance event")
                return

            logger.debug("[UTTERANCE] Received: %s", user_text)
            
            # Call utterance handler with just text + plain context - returns text response
            response_text = utterance_handler.process_utterance(
                user_text,
                agent_name=self._manifest.identification.conversationalName,
            )
            
            if not response_text:
                logger.debug("[UTTERANCE] No response generated")
                return

            responding_to_name = self._resolve_utterance_speaker_name(event, in_envelope)
            if responding_to_name:
                response_text = f"{responding_to_name}: {response_text}"

            logger.debug("[UTTERANCE] Response: %s", response_text)
            
            # Construct OpenFloor response event
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(values=[response_text])}
            )
            
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
            
        except Exception as e:
            logger.exception("[UTTERANCE] Error processing utterance")
            # Send error response to user
            error_msg = "I'm sorry, I encountered an error processing your message."
            dialog = DialogEvent(
                speakerUri=self._manifest.identification.speakerUri,
                features={"text": TextFeature(values=[error_msg])}
            )
            out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
    
    def _extract_text_from_utterance_event(self, event: UtteranceEvent) -> str:
        """
        Extract text from an UtteranceEvent.
        
        Handles various DialogEvent structures robustly.
        
        Args:
            event: The UtteranceEvent
            
        Returns:
            Extracted text string, or empty string if not found
        """
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
            elif isinstance(event, dict):
                params = event.get('parameters')
            else:
                params = None

            if params is None:
                return ""

            if hasattr(params, 'dialogEvent'):
                dialog_event = params.dialogEvent
            elif isinstance(params, dict) and 'dialogEvent' in params:
                dialog_event = params['dialogEvent']
            elif hasattr(params, 'get'):
                dialog_event = params.get('dialogEvent')
                if dialog_event is None:
                    dialog_event = params
            else:
                dialog_event = params

            if hasattr(dialog_event, 'features'):
                features = dialog_event.features
            elif isinstance(dialog_event, dict) and 'features' in dialog_event:
                features = dialog_event['features']
            else:
                return ""

            if isinstance(features, dict):
                if 'text' in features:
                    text = _extract_from_text_feature(features['text'])
                    if text:
                        return text

            elif hasattr(features, '__iter__'):
                for feature in features:
                    text = _extract_from_text_feature(feature)
                    if text:
                        return text

            return ""
            
        except Exception as e:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""

    def _extract_speaker_uri_from_utterance_event(self, event: UtteranceEvent) -> str:
        try:
            # Get dialog event from parameters
            if hasattr(event, 'parameters'):
                params = event.parameters

                # Handle Parameters object
                if hasattr(params, 'dialogEvent'):
                    dialog_event = params.dialogEvent
                elif isinstance(params, dict) and 'dialogEvent' in params:
                    dialog_event = params['dialogEvent']
                elif hasattr(params, 'get'):
                    dialog_event = params.get('dialogEvent')
                    if dialog_event is None:
                        dialog_event = params
                else:
                    dialog_event = params

                if hasattr(dialog_event, 'speakerUri'):
                    return getattr(dialog_event, 'speakerUri', '') or ''
                if isinstance(dialog_event, dict):
                    return dialog_event.get('speakerUri', '') or ''

            return ""

        except Exception:
            return ""

    def _resolve_utterance_speaker_name(self, event: UtteranceEvent, in_envelope: Envelope) -> str:
        speaker_uri = self._extract_speaker_uri_from_utterance_event(event)
        if not speaker_uri:
            return ""
        if "assistantclientconvener" in str(speaker_uri).strip().lower():
            return ""

        conversation = getattr(in_envelope, 'conversation', None)
        conversants = getattr(conversation, 'conversants', []) if conversation else []

        for conversant in conversants or []:
            identification = getattr(conversant, 'identification', None)
            if identification is None and isinstance(conversant, dict):
                identification = conversant.get('identification', {})

            if identification is None:
                continue

            if isinstance(identification, dict):
                conversant_speaker = identification.get('speakerUri')
                conversational_name = identification.get('conversationalName')
            else:
                conversant_speaker = getattr(identification, 'speakerUri', None)
                conversational_name = getattr(identification, 'conversationalName', None)

            if conversant_speaker and str(conversant_speaker).strip().lower() == str(speaker_uri).strip().lower():
                return conversational_name or speaker_uri

        return speaker_uri
    
    # =========================================================================
    # CONVERSATION LIFECYCLE EVENTS
    # =========================================================================
    
    def _handle_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle invite event - agent is invited to join a conversation.
        
        Standard behavior:
        1. Check if we're joining a floor
        2. Accept the invitation
        3. Send a greeting if appropriate
        """
        logger.info("[INVITE] Received invitation to conversation: %s", in_envelope.conversation.id)
        
        # Check if we're joining a floor
        self.joinedFloor = False
        for evt in in_envelope.events:
            if hasattr(evt, 'eventType') and evt.eventType == 'joinFloor':
                self.joinedFloor = True
                logger.info("[INVITE] Joining floor in this conversation")
                break
        
        # Store conversation ID
        self.currentConversation = in_envelope.conversation.id
        
        # Send greeting (customize in your utterance_handler if needed)
        agent_name = self._manifest.identification.conversationalName
        
        if self.joinedFloor:
            greeting = f"Hi, I'm {agent_name}. I've joined the floor and I'm ready to help!"
        else:
            greeting = f"Hi, I'm {agent_name}. How can I help you today?"
        
        # Create greeting utterance
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[greeting])}
        )
        
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))
        
        logger.debug("[INVITE] Sent greeting: %s", greeting)
    
    def _handle_uninvite(self, event: UninviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle uninvite event - agent is being removed from conversation.
        
        Standard behavior:
        1. Log the uninvite
        2. Send a goodbye message
        3. Clean up conversation state
        """
        logger.info("[UNINVITE] Received uninvite from conversation: %s", in_envelope.conversation.id)
        
        # Send goodbye message
        agent_name = self._manifest.identification.conversationalName
        farewell = f"Goodbye! {agent_name} is leaving the conversation."
        
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features=[TextFeature.from_text(farewell)]
        )
        
        utterance_event = UtteranceEvent.create(dialog)
        out_envelope.events.append(utterance_event)
        
        # Clean up state
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None
        
        logger.debug("[UNINVITE] Sent farewell and cleaned up state")
    
    def _handle_decline_invite(self, event: DeclineInviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle decline invite event - another agent declined our invitation.
        
        Standard behavior:
        1. Log the decline
        2. Update internal state if needed
        """
        logger.info("[DECLINE_INVITE] Agent declined invitation in conversation: %s", in_envelope.conversation.id)
        
        # Extract who declined if available
        if hasattr(event, 'parameters') and event.parameters:
            logger.debug("[DECLINE_INVITE] Details: %s", event.parameters)
    
    def _handle_bye(self, event: ByeEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle bye event - conversation is ending.
        
        Standard behavior:
        1. Log the bye event
        2. Clean up conversation state
        3. Send acknowledgment if appropriate
        """
        logger.info("[BYE] Conversation ending: %s", in_envelope.conversation.id)
        
        # Clean up state
        self.joinedFloor = False
        self.grantedFloor = False
        self.currentConversation = None
        
        logger.debug("[BYE] Cleaned up conversation state")
    
    # =========================================================================
    # MANIFEST EVENTS - Override base class method
    # =========================================================================
    
    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope):
        """
        Handle getManifests event - OVERRIDES base class method.
        
        Standard behavior:
        1. Create PublishManifestsEvent with manifest data
        2. Add it to the outgoing envelope
        """
        logger.info("[GET_MANIFESTS] Manifest requested, publishing capabilities")
        
        # Respond with the manifest we were constructed with
        # The manifest object will be serialized automatically by JsonSerializable
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [self._manifest],
                "discoveryManifests": []
            }))
        )

        agent_name = self._manifest.identification.conversationalName
        logger.debug("[GET_MANIFESTS] Published manifest for %s", agent_name)
    
    def _handle_publish_manifests(self, event: PublishManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle publish manifests event - received manifests from other agents.
        
        Standard behavior:
        1. Log received manifests
        2. Store for potential use (e.g., agent discovery)
        """
        logger.info("[PUBLISH_MANIFESTS] Received manifests from other agents")
        
        if hasattr(event, 'parameters') and hasattr(event.parameters, 'manifests'):
            manifests = event.parameters.manifests
            for manifest in manifests:
                agent_name = manifest.identification.conversationalName if hasattr(manifest, 'identification') else "Unknown"
                logger.debug("[PUBLISH_MANIFESTS] - %s", agent_name)
        
        # Store manifests if needed for your application
        # self.known_agents = manifests
    
    # =========================================================================
    # FLOOR MANAGEMENT EVENTS
    # =========================================================================
    
    # NOTE: request_floor event is sent BY agents TO the Floor Manager to request
    # speaking permission. Agents never receive this event - only send it.
    # To request the floor, create and send a RequestFloorEvent:
    #     request_event = RequestFloorEvent.create()
    #     out_envelope.events.append(request_event)
    
    def _handle_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle grant floor event - agent is granted speaking permission.
        
        Standard behavior:
        1. Update granted floor state
        2. Log the grant
        3. Agent can now speak freely
        """
        logger.info("[GRANT_FLOOR] Floor granted in conversation: %s", in_envelope.conversation.id)
        
        self.grantedFloor = True
        logger.info("[GRANT_FLOOR] Agent now has floor and can speak")
    
    def _handle_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle revoke floor event - speaking permission is revoked.
        
        Standard behavior:
        1. Update granted floor state
        2. Stop speaking
        3. Wait for floor to be granted again
        """
        logger.info("[REVOKE_FLOOR] Floor revoked in conversation: %s", in_envelope.conversation.id)
        
        self.grantedFloor = False

        logger.info("[REVOKE_FLOOR] Agent no longer has floor, will not respond to utterances")
    
    def _handle_yield_floor(self, event: YieldFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle yield floor event - agent yields speaking permission.
        
        Standard behavior:
        1. Log the yield
        2. Another agent is giving up the floor
        3. We might request it if needed
        """
        logger.info("[YIELD_FLOOR] Another agent yielded floor in conversation: %s", in_envelope.conversation.id)
        
        # Extract who yielded if available
        yielder = "Unknown"
        if in_envelope.sender and hasattr(in_envelope.sender, 'speakerUri'):
            yielder = in_envelope.sender.speakerUri
        
        logger.debug("[YIELD_FLOOR] Agent %s yielded the floor", yielder)
        
        # Optional: Request floor if we want it
        # request_event = RequestFloorEvent.create()
        # out_envelope.events.append(request_event)
    
    # =========================================================================
    # CONTEXT EVENT
    # =========================================================================
    
    def _handle_context(self, event: Event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """
        Handle context event - contextual information provided.
        
        Standard behavior:
        1. Log context received
        2. Extract and store relevant context
        3. Use in subsequent utterance processing
        """
        logger.info("[CONTEXT] Context received in conversation: %s", in_envelope.conversation.id)
        
        if hasattr(event, 'parameters') and event.parameters:
            logger.debug("[CONTEXT] Context data: %s", event.parameters)
            # Store context for use in utterance handling
            # self.context = event.parameters


def load_manifest_from_config(config_path: str = "agent_config.json") -> Manifest:
    """
    Load agent manifest from configuration file.
    
    Args:
        config_path: Path to JSON configuration file
        
    Returns:
        Configured Manifest object
    """
    script_dir = os.path.dirname(__file__)
    full_path = os.path.join(script_dir, config_path)
    
    with open(full_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    manifest_data = config.get('manifest', {})
    
    # Build Identification
    ident_data = manifest_data.get('identification', {})
    identification = Identification(
        speakerUri=ident_data.get('speakerUri', ident_data.get('serviceEndpoint', 'http://localhost:8080')),
        serviceUrl=ident_data.get('serviceUrl', ident_data.get('serviceEndpoint', 'http://localhost:8080')),
        conversationalName=ident_data.get('conversationalName', 'TemplateAgent'),
        organization=ident_data.get('organization', 'YourOrganization'),
        role=ident_data.get('role', 'assistant'),
        synopsis=ident_data.get('synopsis', 'A template OpenFloor agent')
    )
    
    # Build Capabilities
    cap_data = manifest_data.get('capabilities', {})
    supported_layers_data = cap_data.get('supportedLayers', ['text'])
    if isinstance(supported_layers_data, list):
        # Convert list to SupportedLayers object
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
        capabilities=[capabilities]  # Must be a list!
    )


# Entry point for testing
if __name__ == "__main__":
    print("OpenFloor Agent Template")
    print("=" * 50)
    
    # Load manifest
    manifest = load_manifest_from_config()
    print(f"Agent: {manifest.identification.conversationalName}")
    print(f"Service URL: {manifest.identification.serviceUrl}")
    print(f"Speaker URI: {manifest.identification.speakerUri}")
    
    # Create agent
    agent = TemplateAgent(manifest)
    print("\nAgent initialized successfully!")
    print("All OpenFloor events are registered and ready.")
    print("\nArchitecture:")
    print("  - template_agent.py: Event handling (this file)")
    print("  - envelope_handler.py: JSON parsing/serialization")
    print("  - utterance_handler.py: Custom conversation logic")
    print("\nImplement your utterance logic in utterance_handler.py")
    
    # Example: Process a test envelope
    print("\n" + "=" * 50)
    print("Example: Processing a test envelope")
    print("=" * 50)
    
    # Create a simple test envelope JSON
    test_envelope_json = '''
    {
      "openFloor": {
        "schema": {
          "version": "1.1",
          "url": "https://openvoicenetwork.org/schema"
        },
        "conversation": {
          "id": "test-conversation-123"
        },
        "sender": {
          "speakerUri": "http://test-client",
          "serviceUrl": "http://test-client"
        },
        "events": [
          {
            "eventType": "getManifests",
            "id": "event-123"
          }
        ]
      }
    }
    '''
    
    print("\nTest Input (GetManifests request):")
    print(test_envelope_json[:200] + "...")
    
    try:
        # Process using envelope_handler
        response_json = envelope_handler.process_request(test_envelope_json, agent)
        print("\n✓ Successfully processed envelope")
        print("\nResponse envelope created with agent manifest")
        print("(Full JSON output available via envelope_handler)")
    except Exception as e:
        print(f"\n✗ Error processing envelope: {e}")
