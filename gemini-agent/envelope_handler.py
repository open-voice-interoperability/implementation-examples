#!/usr/bin/env python3
"""
Envelope Handler - OpenFloor Envelope Parsing and Generation

This module handles all envelope-related operations using the OpenFloor library.
It provides clean interfaces for parsing incoming envelopes and creating outgoing responses.

Separation of concerns:
- This file: Envelope parsing, creation, serialization (using openfloor library)
- template_agent.py: Event handling logic
- utterance_handler.py: Custom conversation logic
"""

import logging
from typing import Optional
from openfloor.envelope import Envelope, Conversation, Sender, Schema, To
from openfloor.manifest import Manifest

logger = logging.getLogger(__name__)


def parse_incoming_envelope(json_payload: str) -> Envelope:
    """
    Parse an incoming OpenFloor envelope from JSON.

    Uses the openfloor library's built-in JSON parsing.

    Args:
        json_payload: JSON string containing the OpenFloor envelope

    Returns:
        Parsed Envelope object

    Raises:
        Exception: If JSON is invalid or doesn't conform to OpenFloor schema
    """
    try:
        envelope = Envelope.from_json(json_payload, as_payload=True)
        return envelope
    except Exception as e:
        raise ValueError(f"Failed to parse incoming envelope: {e}")


def create_response_envelope(
    in_envelope: Envelope,
    agent_manifest: Manifest
) -> Envelope:
    """
    Create a response envelope based on an incoming envelope.

    Uses the openfloor library to construct a properly formatted response.

    Args:
        in_envelope: The incoming envelope we're responding to
        agent_manifest: The agent's manifest for identification

    Returns:
        New Envelope configured as a response
    """
    out_envelope = Envelope()

    out_envelope.schema = Schema(
        version="1.1",
        url="https://openvoicenetwork.org/schema"
    )

    if in_envelope.conversation:
        out_envelope.conversation = Conversation(id=in_envelope.conversation.id)
    else:
        import uuid
        out_envelope.conversation = Conversation(id=str(uuid.uuid4()))

    out_envelope.sender = Sender(
        speakerUri=agent_manifest.identification.speakerUri,
        serviceUrl=agent_manifest.identification.serviceUrl
    )

    if in_envelope.sender and in_envelope.sender.speakerUri:
        out_envelope.to = [To(
            speakerUri=in_envelope.sender.speakerUri
        )]

    out_envelope.events = []

    return out_envelope


def serialize_envelope(envelope: Envelope) -> str:
    """
    Serialize an envelope to JSON string.

    Uses the openfloor library's built-in JSON serialization.

    Args:
        envelope: The Envelope to serialize

    Returns:
        JSON string representation of the envelope
    """
    try:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[SERIALIZE] Envelope has %d events", len(envelope.events))
            for i, event in enumerate(envelope.events):
                logger.debug("[SERIALIZE] Event %d: %s", i, type(event).__name__)
                if hasattr(event, 'parameters'):
                    logger.debug("[SERIALIZE] Event %d parameters type: %s", i, type(event.parameters))
                    logger.debug("[SERIALIZE] Event %d parameters value: %s", i, event.parameters)

        json_str = envelope.to_json(as_payload=True)
        return json_str
    except Exception as e:
        logger.exception("[SERIALIZE ERROR] Failed to serialize envelope")
        raise ValueError(f"Failed to serialize envelope: {e}")


def extract_conversation_id(envelope: Envelope) -> Optional[str]:
    """
    Extract conversation ID from an envelope.

    Utility function for logging and tracking.

    Args:
        envelope: The envelope to extract from

    Returns:
        Conversation ID string, or None if not present
    """
    if envelope.conversation and hasattr(envelope.conversation, 'id'):
        return envelope.conversation.id
    return None


def extract_sender_name(envelope: Envelope) -> Optional[str]:
    """
    Extract sender's speaker URI from an envelope.

    Utility function for logging and identification.

    Args:
        envelope: The envelope to extract from

    Returns:
        Sender's speaker URI, or None if not present
    """
    if envelope.sender and hasattr(envelope.sender, 'speakerUri'):
        return envelope.sender.speakerUri
    return None


def validate_envelope(envelope: Envelope) -> bool:
    """
    Validate that an envelope has required fields.

    Basic validation - the openfloor library does more comprehensive validation.

    Args:
        envelope: The envelope to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        if not envelope.schema:
            return False
        if not envelope.events:
            return False
        if not envelope.conversation:
            return False
        return True
    except Exception:
        return False


def process_request(json_payload: str, agent) -> str:
    """
    High-level function to process a complete request.

    This is a convenience function that:
    1. Parses incoming JSON
    2. Creates response envelope
    3. Processes with agent
    4. Serializes response

    Args:
        json_payload: Incoming JSON payload
        agent: TemplateAgent instance

    Returns:
        JSON string response
    """
    in_envelope = parse_incoming_envelope(json_payload)
    out_envelope = agent.process_envelope(in_envelope)
    response_json = serialize_envelope(out_envelope)
    return response_json
