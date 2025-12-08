"""
Refactored StellaAgent with separated concerns.

This is the main agent class that orchestrates the event handling and core logic
while keeping the components cleanly separated.
"""

import json
import os
from typing import Optional, List

import openfloor
from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.agent import BotAgent
from openfloor.envelope import Envelope, Event as EnvelopeEvent
from openfloor.events import UtteranceEvent, InviteEvent
from openfloor.dialog_event import DialogEvent, TextFeature, Feature, Token, Span

from event_handlers import StellaEventHandlers
from stella_core import StellaCore, is_html_string


def make_stella_manifest() -> Manifest:
    """Create the manifest for Stella agent."""
    identification = Identification(
        serviceUrl="http://localhost:8767",
        conversationId="",
        speakerName="Stella",
        speakerUri="http://localhost:8767"
    )
    
    supported = SupportedLayers(
        text=True,
        dtmf=False,
        emotion=False,
        ssml=False,
        speech=False
    )
    
    capability = Capability(
        capabilityName="StellaCapability",
        capabilityDescription="Stella can answer questions about NASA space missions and provide general assistance.",
        version="1.0.0",
        supportedLayers=supported
    )

    manifest = Manifest(identification=identification, capabilities=[capability])
    return manifest


class StellaAgent(BotAgent):
    """A refactored OpenFloor-compatible agent with separated concerns.

    This agent routes utterances to OpenAI or NASA APIs while maintaining
    clean separation between event handling, core logic, and the agent framework.
    """

    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        
        # Initialize core components
        self.core = StellaCore()
        self.event_handlers = StellaEventHandlers(self)
        
        # Agent state
        self.conversationJoined = False
        self.joinedFloor = False
        self.grantedFloor = False

    # OpenFloor event handlers - delegate to event handler class
    def bot_on_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle invite event."""
        self.event_handlers.on_invite(event, in_envelope, out_envelope)

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle utterance event."""
        self.event_handlers.on_utterance(event, in_envelope, out_envelope)

    def bot_on_get_manifests(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle get manifests event."""
        self.event_handlers.on_get_manifests(event, in_envelope, out_envelope)

    def bot_on_grant_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle grant floor event."""
        self.event_handlers.on_grant_floor(event, in_envelope, out_envelope)

    def bot_on_decline_invite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle decline invite event."""
        self.event_handlers.on_decline_invite(event, in_envelope, out_envelope)

    def bot_on_uninvite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle uninvite event."""
        self.event_handlers.on_uninvite(event, in_envelope, out_envelope)

    def bot_on_revoke_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle revoke floor event."""
        self.event_handlers.on_revoke_floor(event, in_envelope, out_envelope)

    # Core processing methods
    def _generate_response_text(self, user_input: str, conversation_id: str = "default") -> str:
        """Generate response text using core logic."""
        return self.core.generate_response(user_input, conversation_id)

    def _add_text_feature(self, dialog_event: DialogEvent, text: str) -> None:
        """Add text feature to dialog event."""
        if is_html_string(text):
            # Handle HTML content
            text_feature = TextFeature(
                featureType="text",
                mimeType="text/html", 
                encoding="utf-8",
                text=text
            )
        else:
            # Handle plain text
            tokens = self._tokenize_text(text)
            text_feature = TextFeature(
                featureType="text",
                mimeType="text/plain",
                encoding="utf-8", 
                text=text,
                tokens=tokens
            )
        
        feature = Feature(textFeature=text_feature)
        dialog_event.features.append(feature)

    def _tokenize_text(self, text: str) -> List[Token]:
        """Simple tokenization of text into tokens."""
        words = text.split()
        tokens = []
        start_offset = 0
        
        for word in words:
            # Find the actual position in original text
            word_start = text.find(word, start_offset)
            if word_start == -1:
                word_start = start_offset
            
            word_end = word_start + len(word)
            
            span = Span(start=word_start, end=word_end)
            token = Token(value=word, span=span)
            tokens.append(token)
            
            start_offset = word_end
        
        return tokens

    # Convenience helpers
    def events_for_envelope(self, in_envelope: Envelope) -> List[EnvelopeEvent]:
        """Process the incoming envelope and return the list of outgoing events."""
        out_env = super().process_envelope(in_envelope)
        return out_env.events

    def payload_for_envelope(self, in_envelope: Envelope, as_payload: bool = True) -> str:
        """Process the incoming envelope and return the outgoing OpenFloor payload JSON."""
        out_env = super().process_envelope(in_envelope)
        return out_env.to_json(as_payload=as_payload)

    # Backwards-compatibility API
    def generate_response(self, inputOpenFloor, sender_from: Optional[str] = None) -> str:
        """Compatibility wrapper for the old assistant.generate_response signature."""
        try:
            if isinstance(inputOpenFloor, dict):
                payload_text = json.dumps(inputOpenFloor)
            else:
                payload_text = str(inputOpenFloor)

            in_envelope = Envelope.from_json(payload_text, as_payload=True)
        except Exception:
            raise ValueError("Invalid OpenFloor payload passed to generate_response")

        out_envelope = self.process_envelope(in_envelope)
        return out_envelope.to_json(as_payload=True)


# Factory function for easy instantiation
def create_stella_agent() -> StellaAgent:
    """Create and return a configured Stella agent."""
    manifest = make_stella_manifest()
    return StellaAgent(manifest)


# For backwards compatibility
def make_agent() -> StellaAgent:
    """Legacy function name for creating agent."""
    return create_stella_agent()