"""
OpenFloor Floor Management System
Implementation based on OpenFloor Inter-Agent Message Specification Version 1.0.1

This module provides a floor management system for OpenFloor conversations,
handling floor control, permissions, and coordination between conversants.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any
from enum import Enum
from dataclasses import dataclass, field


class FloorRole(Enum):
    """Roles that can be assigned to conversants in a floor-managed conversation."""
    CONVENER = "convener"
    DISCOVERY = "discovery"


class FloorState(Enum):
    """States representing the current floor status."""
    IDLE = "idle"
    GRANTED = "granted"
    REQUESTED = "requested"
    REVOKED = "revoked"
    YIELDED = "yielded"


@dataclass
class FloorRequest:
    """Represents a floor request from a conversant."""
    requester_uri: str
    timestamp: datetime
    reason: Optional[str] = None


@dataclass
class FloorGrant:
    """Represents a granted floor to a conversant."""
    grantee_uri: str
    granted_by: str
    timestamp: datetime
    reason: Optional[str] = None


@dataclass
class Conversant:
    """Represents a participant in the conversation."""
    speaker_uri: str
    service_url: Optional[str] = None
    conversational_name: Optional[str] = None
    roles: Set[FloorRole] = field(default_factory=set)
    persistent_state: Dict[str, Any] = field(default_factory=dict)
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FloorManager:
    """
    Manages the conversational floor for OpenFloor conversations.
    
    This class implements the floor management behaviors as defined in section 2.2
    of the OpenFloor specification, including floor granting, revoking, and 
    request handling.
    """
    
    def __init__(self, conversation_id: str, convener_uri: Optional[str] = None):
        """
        Initialize the floor manager for a conversation.
        
        Args:
            conversation_id: Unique identifier for the conversation
            convener_uri: URI of the convener agent (optional)
        """
        self.conversation_id = conversation_id
        self.convener_uri = convener_uri
        self.conversants: Dict[str, Conversant] = {}
        self.assigned_floor_roles: Dict[FloorRole, List[str]] = {
            FloorRole.CONVENER: [convener_uri] if convener_uri else [],
            FloorRole.DISCOVERY: []
        }
        self.current_floor_holder: Optional[str] = None
        self.floor_state = FloorState.IDLE
        self.pending_requests: List[FloorRequest] = []
        self.floor_history: List[FloorGrant] = []
        self.timeout_seconds = 30  # Default timeout for floor holding
        
    def add_conversant(self, speaker_uri: str, service_url: Optional[str] = None,
                      conversational_name: Optional[str] = None,
                      roles: Optional[Set[FloorRole]] = None) -> None:
        """
        Add a conversant to the conversation.
        
        Args:
            speaker_uri: Unique URI identifier for the conversant
            service_url: Service URL for the conversant (optional)
            conversational_name: Display name for the conversant (optional)
            roles: Set of floor roles for this conversant (optional)
        """
        if roles is None:
            roles = set()
            
        conversant = Conversant(
            speaker_uri=speaker_uri,
            service_url=service_url,
            conversational_name=conversational_name,
            roles=roles
        )
        
        self.conversants[speaker_uri] = conversant
        
        # Update assigned floor roles
        for role in roles:
            if speaker_uri not in self.assigned_floor_roles[role]:
                self.assigned_floor_roles[role].append(speaker_uri)
    
    def remove_conversant(self, speaker_uri: str) -> bool:
        """
        Remove a conversant from the conversation.
        
        Args:
            speaker_uri: URI of the conversant to remove
            
        Returns:
            bool: True if conversant was removed, False if not found
        """
        if speaker_uri not in self.conversants:
            return False
            
        # Remove from assigned roles
        for role_list in self.assigned_floor_roles.values():
            if speaker_uri in role_list:
                role_list.remove(speaker_uri)
        
        # Revoke floor if this conversant has it
        if self.current_floor_holder == speaker_uri:
            self.revoke_floor(speaker_uri, reason="@uninvited")
            
        # Remove pending requests from this conversant
        self.pending_requests = [req for req in self.pending_requests 
                               if req.requester_uri != speaker_uri]
        
        del self.conversants[speaker_uri]
        return True
    
    def request_floor(self, requester_uri: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle a floor request from a conversant.
        
        Args:
            requester_uri: URI of the conversant requesting the floor
            reason: Optional reason for the floor request
            
        Returns:
            dict: Response indicating the result of the request
        """
        if requester_uri not in self.conversants:
            return {
                "success": False,
                "error": "Conversant not found",
                "event_type": "error"
            }
        
        # Check if floor is available
        if self.current_floor_holder is None:
            # Grant floor immediately
            return self.grant_floor(requester_uri, granted_by=self.convener_uri, reason=reason)
        else:
            # Add to pending requests
            request = FloorRequest(
                requester_uri=requester_uri,
                timestamp=datetime.now(timezone.utc),
                reason=reason
            )
            self.pending_requests.append(request)
            
            return {
                "success": True,
                "message": "Floor request queued",
                "event_type": "requestFloor",
                "position_in_queue": len(self.pending_requests)
            }
    
    def grant_floor(self, grantee_uri: str, granted_by: Optional[str] = None, 
                   reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Grant the floor to a conversant.
        
        Args:
            grantee_uri: URI of the conversant to grant floor to
            granted_by: URI of the agent granting the floor (usually convener)
            reason: Optional reason for granting the floor
            
        Returns:
            dict: OpenFloor event for grantFloor
        """
        if grantee_uri not in self.conversants:
            return {
                "success": False,
                "error": "Conversant not found",
                "event_type": "error"
            }
        
        # Revoke current floor holder if any
        if self.current_floor_holder and self.current_floor_holder != grantee_uri:
            self.revoke_floor(self.current_floor_holder, reason="@override")
        
        # Grant floor
        self.current_floor_holder = grantee_uri
        self.floor_state = FloorState.GRANTED
        
        grant = FloorGrant(
            grantee_uri=grantee_uri,
            granted_by=granted_by or self.convener_uri or "system",
            timestamp=datetime.now(timezone.utc),
            reason=reason
        )
        self.floor_history.append(grant)
        
        # Remove any pending requests from this conversant
        self.pending_requests = [req for req in self.pending_requests 
                               if req.requester_uri != grantee_uri]
        
        # Update last activity
        self.conversants[grantee_uri].last_activity = datetime.now(timezone.utc)
        
        return {
            "eventType": "grantFloor",
            "to": {
                "speakerUri": grantee_uri
            },
            "reason": reason,
            "parameters": {},
            "success": True
        }
    
    def revoke_floor(self, revokee_uri: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Revoke the floor from a conversant.
        
        Args:
            revokee_uri: URI of the conversant to revoke floor from
            reason: Optional reason for revoking (supports @timedOut, @brokenPolicy, etc.)
            
        Returns:
            dict: OpenFloor event for revokeFloor
        """
        if self.current_floor_holder != revokee_uri:
            return {
                "success": False,
                "error": "Conversant does not have the floor",
                "event_type": "error"
            }
        
        self.current_floor_holder = None
        self.floor_state = FloorState.REVOKED
        
        # Process next pending request if any
        if self.pending_requests:
            next_request = self.pending_requests.pop(0)
            # Auto-grant to next in queue
            self.grant_floor(next_request.requester_uri, 
                           granted_by=self.convener_uri,
                           reason="next in queue")
        else:
            self.floor_state = FloorState.IDLE
        
        return {
            "eventType": "revokeFloor",
            "to": {
                "speakerUri": revokee_uri
            },
            "reason": reason,
            "parameters": {},
            "success": True
        }
    
    def yield_floor(self, yielder_uri: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle a conversant yielding the floor.
        
        Args:
            yielder_uri: URI of the conversant yielding the floor
            reason: Optional reason for yielding (supports @complete, @outOfDomain, etc.)
            
        Returns:
            dict: Response indicating the result
        """
        if self.current_floor_holder != yielder_uri:
            return {
                "success": False,
                "error": "Conversant does not have the floor",
                "event_type": "error"
            }
        
        self.current_floor_holder = None
        self.floor_state = FloorState.YIELDED
        
        # Process next pending request if any
        if self.pending_requests:
            next_request = self.pending_requests.pop(0)
            # Auto-grant to next in queue
            self.grant_floor(next_request.requester_uri, 
                           granted_by=self.convener_uri,
                           reason="next in queue")
        else:
            self.floor_state = FloorState.IDLE
        
        return {
            "success": True,
            "message": "Floor yielded",
            "event_type": "yieldFloor",
            "reason": reason
        }
    
    def assign_role(self, speaker_uri: str, role: FloorRole) -> bool:
        """
        Assign a floor role to a conversant.
        
        Args:
            speaker_uri: URI of the conversant
            role: Role to assign
            
        Returns:
            bool: True if role was assigned successfully
        """
        if speaker_uri not in self.conversants:
            return False
        
        # For convener role, ensure maximum cardinality of 1
        if role == FloorRole.CONVENER:
            # Remove existing convener
            if self.assigned_floor_roles[FloorRole.CONVENER]:
                old_convener = self.assigned_floor_roles[FloorRole.CONVENER][0]
                self.conversants[old_convener].roles.discard(FloorRole.CONVENER)
            self.assigned_floor_roles[FloorRole.CONVENER] = [speaker_uri]
        else:
            if speaker_uri not in self.assigned_floor_roles[role]:
                self.assigned_floor_roles[role].append(speaker_uri)
        
        self.conversants[speaker_uri].roles.add(role)
        return True
    
    def get_floor_status(self) -> Dict[str, Any]:
        """
        Get the current floor status.
        
        Returns:
            dict: Current floor state information
        """
        return {
            "conversation_id": self.conversation_id,
            "current_floor_holder": self.current_floor_holder,
            "floor_state": self.floor_state.value,
            "pending_requests": len(self.pending_requests),
            "conversants_count": len(self.conversants),
            "assigned_roles": {
                role.value: uris for role, uris in self.assigned_floor_roles.items()
            }
        }
    
    def check_timeouts(self) -> List[Dict[str, Any]]:
        """
        Check for floor timeouts and generate appropriate events.
        
        Returns:
            list: List of events to send (e.g., revokeFloor events)
        """
        events = []
        current_time = datetime.now(timezone.utc)
        
        if (self.current_floor_holder and 
            self.current_floor_holder in self.conversants):
            
            last_activity = self.conversants[self.current_floor_holder].last_activity
            time_diff = (current_time - last_activity).total_seconds()
            
            if time_diff > self.timeout_seconds:
                # Generate timeout event
                event = self.revoke_floor(self.current_floor_holder, reason="@timedOut")
                events.append(event)
        
        return events
    
    def to_conversation_object(self) -> Dict[str, Any]:
        """
        Generate the conversation object as defined in the OpenFloor specification.
        
        Returns:
            dict: Conversation object with conversants and assigned floor roles
        """
        conversants_list = []
        for speaker_uri, conversant in self.conversants.items():
            conversant_obj = {
                "identification": {
                    "speakerUri": speaker_uri,
                    "conversationalName": conversant.conversational_name
                }
            }
            
            if conversant.service_url:
                conversant_obj["identification"]["serviceUrl"] = conversant.service_url
            
            if conversant.roles:
                conversant_obj["identification"]["openFloorRoles"] = {
                    role.value: True for role in conversant.roles
                }
            
            if conversant.persistent_state:
                conversant_obj["persistentState"] = conversant.persistent_state
            
            conversants_list.append(conversant_obj)
        
        return {
            "id": self.conversation_id,
            "assignedFloorRoles": {
                role.value: uris for role, uris in self.assigned_floor_roles.items()
                if uris  # Only include roles that have assigned agents
            },
            "conversants": conversants_list
        }


def create_floor_manager(conversation_id: Optional[str] = None, 
                        convener_uri: Optional[str] = None) -> FloorManager:
    """
    Factory function to create a new FloorManager instance.
    
    Args:
        conversation_id: Unique conversation ID (auto-generated if None)
        convener_uri: URI of the convener agent (optional)
        
    Returns:
        FloorManager: New floor manager instance
    """
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())
    
    return FloorManager(conversation_id, convener_uri)


# Example usage and testing functions
def example_floor_usage():
    """
    Demonstrate basic floor management functionality.
    """
    print("OpenFloor Floor Management Example")
    print("=" * 40)
    
    # Create floor manager
    convener_uri = "tag:example-convener.com,2025:0001"
    floor = create_floor_manager(convener_uri=convener_uri)
    
    # Add conversants
    floor.add_conversant("tag:agent-a.com,2025:0001", 
                        service_url="https://agent-a.com",
                        conversational_name="Agent A")
    
    floor.add_conversant("tag:agent-b.com,2025:0001",
                        service_url="https://agent-b.com", 
                        conversational_name="Agent B")
    
    # Agent A requests floor
    print("\n1. Agent A requests floor:")
    result = floor.request_floor("tag:agent-a.com,2025:0001", reason="initial request")
    print(json.dumps(result, indent=2))
    
    # Agent B requests floor (should be queued)
    print("\n2. Agent B requests floor:")
    result = floor.request_floor("tag:agent-b.com,2025:0001", reason="follow-up question")
    print(json.dumps(result, indent=2))
    
    # Check floor status
    print("\n3. Floor status:")
    status = floor.get_floor_status()
    print(json.dumps(status, indent=2))
    
    # Agent A yields floor
    print("\n4. Agent A yields floor:")
    result = floor.yield_floor("tag:agent-a.com,2025:0001", reason="@complete")
    print(json.dumps(result, indent=2))
    
    # Final floor status
    print("\n5. Final floor status:")
    status = floor.get_floor_status()
    print(json.dumps(status, indent=2))
    
    # Generate conversation object
    print("\n6. Conversation object:")
    conversation = floor.to_conversation_object()
    print(json.dumps(conversation, indent=2))


if __name__ == "__main__":
    example_floor_usage()