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

# Import OpenFloor components
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

# Import envelope handling (separated from event handling)
import envelope_handler

# Import the utterance handler (custom logic)
import utterance_handler

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
        self.on_context += self._handle_context

    def _is_invite_addressed_to_me(self, event: InviteEvent) -> bool:
        """Return True if the invite is broadcast or explicitly addressed to this agent."""
        if event.to is None:
            return True

        to_speaker = getattr(event.to, "speakerUri", None)
        to_service = getattr(event.to, "serviceUrl", None)
        if not to_speaker and not to_service:
            return True

        my_speaker = self._manifest.identification.speakerUri
        my_service = self._manifest.identification.serviceUrl

        if to_speaker and my_speaker and to_speaker.strip().lower() == my_speaker.strip().lower():
            return True
        if to_service and my_service and to_service.rstrip("/").lower() == my_service.rstrip("/").lower():
            return True

        return False
    
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
            # Get dialog event from parameters
            if hasattr(event, 'parameters'):
                params = event.parameters
                
                # Handle Parameters object
                if hasattr(params, 'dialogEvent'):
                    dialog_event = params.dialogEvent
                elif hasattr(params, '__contains__') and 'dialogEvent' in params:
                    dialog_event = params.get('dialogEvent')
                elif isinstance(params, dict) and 'dialogEvent' in params:
                    dialog_event = params['dialogEvent']
                else:
                    dialog_event = params
                
                # Extract features
                if hasattr(dialog_event, 'features'):
                    features = dialog_event.features
                elif isinstance(dialog_event, dict) and 'features' in dialog_event:
                    features = dialog_event['features']
                else:
                    return ""
                
                # Handle dict-based features (common format)
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
                        elif isinstance(text_feature, dict):
                            if 'tokens' in text_feature:
                                tokens = text_feature['tokens']
                                text_parts = [str(t.get('value', '')) for t in tokens if 'value' in t]
                                return ' '.join(text_parts)
                            if 'values' in text_feature:
                                return ' '.join([str(v) for v in text_feature.get('values', [])])
                
                # Handle list-based features
                elif hasattr(features, '__iter__'):
                    for feature in features:
                        if hasattr(feature, 'mimeType') and 'text' in feature.mimeType:
                            if hasattr(feature, 'tokens'):
                                tokens = feature.tokens
                                text_parts = [str(token.value) for token in tokens if hasattr(token, 'value')]
                                return ' '.join(text_parts)
                        elif isinstance(feature, dict):
                            mime_type = feature.get('mimeType')
                            if mime_type and 'text' in mime_type:
                                if 'tokens' in feature:
                                    tokens = feature.get('tokens', [])
                                    text_parts = [str(t.get('value', '')) for t in tokens if 'value' in t]
                                    return ' '.join(text_parts)
                                if 'values' in feature:
                                    return ' '.join([str(v) for v in feature.get('values', [])])
            
            return ""
            
        except Exception as e:
            logger.exception("[EXTRACT_TEXT] Error extracting text")
            return ""
    
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
        if not self._is_invite_addressed_to_me(event):
            logger.info("[INVITE] Ignoring invite not addressed to this agent")
            return

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
    
    def _handle_context(self, event: ContextEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
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
