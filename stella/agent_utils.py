"""
Utility functions for OpenFloor agents.
"""
from typing import Optional
from openfloor.envelope import Event, Parameters, To


def create_empty_openfloor_event(event_type: str, 
                                to_speaker_uri: Optional[str] = None,
                                to_service_url: Optional[str] = None,
                                private: bool = False,
                                reason: Optional[str] = None) -> Event:
    """
    Create an empty OpenFloor event with minimal required fields.
    
    Args:
        event_type (str): The type of event (e.g., "utterance", "invite", "grant_floor", etc.)
        to_speaker_uri (Optional[str]): Target speaker URI for the event
        to_service_url (Optional[str]): Target service URL for the event  
        private (bool): Whether this is a private event (default: False)
        reason (Optional[str]): Optional reason for the event
        
    Returns:
        Event: An empty OpenFloor event with the specified parameters
        
    Example:
        # Create a basic event
        event = create_empty_openfloor_event("grant_floor")
        
        # Create an event targeted to a specific speaker
        event = create_empty_openfloor_event("invite", to_speaker_uri="urn:agent:example")
        
        # Create a private event with reason
        event = create_empty_openfloor_event("revoke_floor", 
                                           to_speaker_uri="urn:agent:example",
                                           private=True,
                                           reason="Floor timeout")
    """
    # Create To object if either speaker URI or service URL is provided
    to = None
    if to_speaker_uri is not None or to_service_url is not None:
        to = To(speakerUri=to_speaker_uri, 
                serviceUrl=to_service_url, 
                private=private)
    
    # Create empty parameters
    parameters = Parameters()
    
    # Create and return the event
    return Event(
        eventType=event_type,
        to=to,
        reason=reason,
        parameters=parameters
    )
