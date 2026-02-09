#!/usr/bin/env python3
"""
Envelope Handler - OpenFloor Envelope Parsing and Generation

This module handles all envelope-related operations using the OpenFloor library.
"""

import logging
from typing import Optional
from openfloor.envelope import Envelope, Conversation, Sender, Schema, To
from openfloor.manifest import Manifest

logger = logging.getLogger(__name__)


def parse_incoming_envelope(json_payload: str) -> Envelope:
    try:
        envelope = Envelope.from_json(json_payload, as_payload=True)
        return envelope
    except Exception as e:
        raise ValueError(f"Failed to parse incoming envelope: {e}")


def create_response_envelope(in_envelope: Envelope, agent_manifest: Manifest) -> Envelope:
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
    if envelope.conversation and hasattr(envelope.conversation, 'id'):
        return envelope.conversation.id
    return None


def extract_sender_name(envelope: Envelope) -> Optional[str]:
    if envelope.sender and hasattr(envelope.sender, 'speakerUri'):
        return envelope.sender.speakerUri
    return None


def validate_envelope(envelope: Envelope) -> bool:
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
    in_envelope = parse_incoming_envelope(json_payload)
    out_envelope = agent.process_envelope(in_envelope)
    response_json = serialize_envelope(out_envelope)
    return response_json
