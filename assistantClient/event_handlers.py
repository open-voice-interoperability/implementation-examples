"""Event handling and OpenFloor protocol processing for the Assistant Client."""

import json
import requests
from CTkMessagebox import CTkMessagebox
import openfloor
from openfloor import DialogEvent, UtteranceEvent
import ui_components


def send_broadcast_to_agents(payload_obj, urls_to_send):
    """Phase 1: Send broadcast to all agents and collect their responses.
    
    Args:
        payload_obj: The JSON payload to send
        urls_to_send: List of URLs to send to
        
    Returns:
        list: List of tuples (target_url, response_data, original_sender, incoming_events)
    """
    all_responses = []
    
    for target_url in urls_to_send:
        try:
            print(f"\nSending broadcast to: {target_url}")
            response = requests.post(target_url, json=payload_obj, timeout=5)
            print(f"HTTP status from {target_url}: {response.status_code}")
            print("Response headers:", dict(response.headers))
            print("Response text (first 500 chars):", response.text[:500])
            
            # Check if response is actually JSON
            if response.status_code != 200:
                CTkMessagebox(
                    title="Error",
                    message=f"Server {target_url} returned status {response.status_code}\n\nResponse: {response.text[:200]}",
                    icon="cancel"
                )
                continue
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error for {target_url}: {e}")
            CTkMessagebox(
                title="Connection Error",
                message=f"Cannot connect to {target_url}\n\nIs the server running?",
                icon="cancel"
            )
            continue
        except requests.exceptions.Timeout:
            print(f"Timeout connecting to {target_url}")
            CTkMessagebox(
                title="Timeout Error",
                message=f"Connection to {target_url} timed out",
                icon="cancel"
            )
            continue
        except Exception as e:
            print(f"Error sending to {target_url}: {e}")
            CTkMessagebox(
                title="Error",
                message=f"Error sending to {target_url}: {str(e)}",
                icon="cancel"
            )
            continue
            
        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            print(f"JSON decode error for {target_url}: {e}")
            CTkMessagebox(
                title="Error",
                message=f"Server {target_url} did not return valid JSON.\n\nStatus: {response.status_code}\n\nResponse: {response.text[:200]}",
                icon="cancel"
            )
            print(f"Full response text: {response.text}")
            continue
            
        print("Response JSON:", json.dumps(response_data, indent=2))
        incoming_events = response_data.get("openFloor", {}).get("events", [])
        original_sender = response_data.get("openFloor", {}).get("sender", {})
        
        # Store response for Phase 2 processing
        all_responses.append((target_url, response_data, original_sender, incoming_events))
    
    return all_responses


def process_agent_responses(root, all_responses, floor_manager, update_conversation_history_callback):
    """Phase 2: Process all responses and update conversation history.
    
    Args:
        root: The main Tkinter window
        all_responses: List of response tuples from Phase 1
        floor_manager: Floor manager instance (or None)
        update_conversation_history_callback: Function to update conversation history
    """
    for target_url, response_data, original_sender, incoming_events in all_responses:
        assistantConversationalName = ""
        assistant_url = target_url
        
        for event in incoming_events:
            if event.get("eventType") == "publishManifests":
                manifests = event.get("parameters", {}).get("servicingManifests", [])
                if manifests:
                    manifest = manifests[0]
                    assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                    assistant_uri = manifest.get("identification", {}).get("uri", "")
                    manifest_service_url = manifest.get("identification", {}).get("serviceUrl", target_url)
                    
                    # Add agent to floor manager if active
                    if floor_manager is not None and assistant_uri:
                        try:
                            floor_manager.add_conversant(
                                speaker_uri=assistant_uri,
                                service_url=manifest_service_url,
                                conversational_name=assistantConversationalName
                            )
                            print(f"Added {assistantConversationalName or assistant_uri} to floor manager")
                        except Exception as e:
                            print(f"Failed to add agent to floor manager: {e}")
                else:
                    CTkMessagebox(title="Error", message="No servicing manifests found in the response.", icon="cancel")
                    
            elif event.get("eventType") == "utterance":
                parameters = event.get("parameters", {})
                dialog_event = parameters.get("dialogEvent", {})
                features = dialog_event.get("features", {})
                text_features = features.get("text", {})
                html_features = features.get("html", {})
                
                # Extract speaker info for conversation history
                speaker_uri = dialog_event.get("speakerUri", "Unknown")
                
                # Check if there's an HTML feature and display it in browser
                if html_features:
                    html_tokens = html_features.get("tokens", [])
                    if html_tokens:
                        html_value = html_tokens[0].get("value", "")
                        if html_value:
                            ui_components.display_response_html(html_value)
                            
                # Check the MIME type to determine how to display the content
                mime_type = text_features.get("mimeType", "")
                tokens = text_features.get("tokens", [])
                if tokens:
                    extracted_value = tokens[0].get("value", "No value found")
                    
                    # Update conversation history with utterance ID for deduplication
                    utterance_id = dialog_event.get("id")
                    update_conversation_history_callback(
                        assistantConversationalName or speaker_uri,
                        extracted_value,
                        speaker_uri,
                        utterance_id
                    )
                    
                    # If MIME type is text/plain, only display JSON response
                    if mime_type == "text/plain":
                        # For plain text, don't convert to HTML or display in browser
                        pass  # Just continue to display_response_json at the end
                    else:
                        # For other MIME types (or no MIME type), process as HTML
                        html_content = f"{ui_components.convert_text_to_html(extracted_value)}"
                        ui_components.display_response_html(html_content)
                        
        ui_components.display_response_json(root, response_data, assistantConversationalName, assistant_url)


def forward_responses_to_agents(all_responses, urls_to_send, global_conversation, update_conversation_history_callback):
    """Phase 3: Forward all responses to all other agents (after processing all initial responses).
    
    Args:
        all_responses: List of response tuples from Phase 1
        urls_to_send: List of all agent URLs
        global_conversation: The global conversation object
        update_conversation_history_callback: Function to update conversation history
    """
    for target_url, response_data, original_sender, incoming_events in all_responses:
        print(f"\n=== FORWARDING CHECK ===")
        print(f"incoming_events count: {len(incoming_events)}")
        print(f"urls_to_send: {urls_to_send}")
        print(f"target_url: {target_url}")
        
        # Forward response to all other agents on the floor (OFP requirement)
        if incoming_events:
            other_agents = [url for url in urls_to_send if url != target_url]
            print(f"other_agents: {other_agents}")
            if other_agents:
                # Remove 'to' field from events so they're treated as broadcasts
                broadcast_events = []
                for event in incoming_events:
                    event_copy = event.copy()
                    if 'to' in event_copy:
                        del event_copy['to']
                    broadcast_events.append(event_copy)
                
                # Create the forward payload preserving the original sender
                forward_payload = {
                    "openFloor": {
                        "conversation": {
                            "id": global_conversation.id,
                            "conversants": [
                                {
                                    "identification": {
                                        "speakerUri": c.identification.speakerUri,
                                        "serviceUrl": c.identification.serviceUrl,
                                        "conversationalName": c.identification.conversationalName
                                    }
                                }
                                for c in global_conversation.conversants
                            ]
                        },
                        "sender": original_sender,  # Preserve original sender, not client
                        "events": broadcast_events  # Forward events as broadcasts
                    }
                }
                
                # Send to all other agents
                for other_agent_url in other_agents:
                    try:
                        print(f"\n=== FORWARDING TO {other_agent_url} ===")
                        print(f"Conversation ID: {global_conversation.id}")
                        print(f"Number of broadcast events: {len(broadcast_events)}")
                        print(f"Broadcast events: {json.dumps(broadcast_events, indent=2)}")
                        forward_response = requests.post(other_agent_url, json=forward_payload)
                        print(f"Forward response status: {forward_response.status_code}")
                        
                        # Check what the agent returned
                        try:
                            forward_response_data = forward_response.json()
                            forward_events = forward_response_data.get("openFloor", {}).get("events", [])
                            print(f"Agent returned {len(forward_events)} events: {json.dumps(forward_events, indent=2)}")
                            
                            # If agent responded with new utterances, update conversation history
                            for evt in forward_events:
                                if evt.get("eventType") == "utterance":
                                    # Try both locations for dialogEvent
                                    dialog = evt.get("parameters", {}).get("dialogEvent") or evt.get("dialogEvent", {})
                                    speaker_uri = dialog.get("speakerUri", "Unknown")
                                    
                                    # Extract text from tokens or values
                                    text = None
                                    text_feature = dialog.get("features", {}).get("text", {})
                                    
                                    # Try tokens first
                                    tokens = text_feature.get("tokens", [])
                                    if tokens and isinstance(tokens, list):
                                        text = tokens[0].get("value")
                                    
                                    # Fallback to values if tokens not found
                                    if not text:
                                        values = text_feature.get("values", [])
                                        if values and isinstance(values, list):
                                            text = values[0] if isinstance(values[0], str) else values[0].get("value")
                                    
                                    if text:
                                        # Find speaker name by matching serviceUrl
                                        speaker_name = None
                                        for c in global_conversation.conversants:
                                            if c.identification.speakerUri == speaker_uri:
                                                speaker_name = c.identification.conversationalName
                                                break
                                        
                                        # If not found by speakerUri, try by serviceUrl
                                        if not speaker_name:
                                            for c in global_conversation.conversants:
                                                if c.identification.serviceUrl == other_agent_url:
                                                    speaker_name = c.identification.conversationalName
                                                    break
                                        
                                        # Update conversation history with utterance ID
                                        utterance_id = dialog.get("id")
                                        update_conversation_history_callback(
                                            speaker_name or speaker_uri,
                                            text,
                                            speaker_uri,
                                            utterance_id
                                        )
                            
                            # If the agent responded, forward those responses to all other agents (recursive forwarding)
                            if forward_events:
                                responding_agent_sender = forward_response_data.get("openFloor", {}).get("sender", {})
                                # Exclude both the agent that just responded AND the original sender
                                other_recipients = [url for url in urls_to_send if url != other_agent_url and url != target_url]
                                
                                if other_recipients:
                                    # Remove 'to' field from response events
                                    response_broadcast_events = []
                                    for evt in forward_events:
                                        evt_copy = evt.copy() if isinstance(evt, dict) else evt
                                        if isinstance(evt_copy, dict) and 'to' in evt_copy:
                                            del evt_copy['to']
                                        response_broadcast_events.append(evt_copy)
                                    
                                    # Create payload for recursive forwarding
                                    recursive_payload = {
                                        "openFloor": {
                                            "conversation": {
                                                "id": global_conversation.id,
                                                "conversants": [
                                                    {
                                                        "identification": {
                                                            "speakerUri": c.identification.speakerUri,
                                                            "serviceUrl": c.identification.serviceUrl,
                                                            "conversationalName": c.identification.conversationalName
                                                        }
                                                    }
                                                    for c in global_conversation.conversants
                                                ]
                                            },
                                            "sender": responding_agent_sender,
                                            "events": response_broadcast_events
                                        }
                                    }
                                    
                                    # Forward to all other agents
                                    for recipient_url in other_recipients:
                                        try:
                                            print(f"  → Recursive forward from {other_agent_url} to {recipient_url}")
                                            recursive_response = requests.post(recipient_url, json=recursive_payload)
                                            print(f"  → Recursive forward status: {recursive_response.status_code}")
                                        except Exception as e:
                                            print(f"  → Failed recursive forward to {recipient_url}: {e}")
                        except:
                            print(f"Forward response text: {forward_response.text[:500]}")
                    except Exception as e:
                        print(f"Failed to forward response to {other_agent_url}: {e}")
