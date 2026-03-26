"""Event handling and OpenFloor protocol processing for the Assistant Client."""

import json
import requests
import threading
import time
import re
from CTkMessagebox import CTkMessagebox
import ui_components

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}


def _normalize_agent_id(value):
    if not value:
        return value
    if value.startswith("agent:"):
        value = value[len("agent:"):]
    return value.rstrip("/").lower()


def _is_url_like(value):
    if not value or not isinstance(value, str):
        return False
    lowered = _clean_url_candidate(value).lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("agent:http://") or lowered.startswith("agent:https://")


def _clean_url_candidate(value):
    if not value or not isinstance(value, str):
        return ""
    cleaned = value.strip().strip("[]()<>{}\"'")
    cleaned = cleaned.rstrip("\"'.,:;!?)]}>")
    return cleaned


def _url_from_speaker_uri(speaker_uri):
    if not speaker_uri:
        return None
    candidate = _clean_url_candidate(speaker_uri)
    if candidate.startswith("agent:http://") or candidate.startswith("agent:https://"):
        return candidate[len("agent:"):]
    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate
    return None


def _prepend_direct_address_context(text, directed_addressee, *, speaker_name=None, speaker_uri=None, speaker_service_url=None, display_name_resolver=None):
    if not text or not directed_addressee:
        return text

    def _replace_leading_url_with_name(raw_text):
        if display_name_resolver is None:
            return raw_text

        trimmed = raw_text.lstrip()
        leading_ws = raw_text[: len(raw_text) - len(trimmed)]
        match = re.match(r"^(?:agent:)?https?://[^\s]+", trimmed, flags=re.IGNORECASE)
        if not match:
            return raw_text

        raw_url = match.group(0)
        candidate_url = _url_from_speaker_uri(raw_url) or _clean_url_candidate(raw_url)
        try:
            resolved_name = display_name_resolver(candidate_url, speaker_uri=speaker_uri)
        except TypeError:
            resolved_name = display_name_resolver(candidate_url)
        except Exception:
            resolved_name = None

        if not resolved_name or _is_url_like(resolved_name):
            return raw_text

        remainder = trimmed[match.end():]
        remainder = re.sub(r"^[\s,:;.!?\-]+", "", remainder)
        if not remainder:
            return f"{leading_ws}{resolved_name}"
        return f"{leading_ws}{resolved_name}: {remainder}"

    normalized_text = text
    normalized_text = _replace_leading_url_with_name(normalized_text)
    stripped_text = text.strip()
    addressee_url = directed_addressee.get("url")
    if _is_url_like(stripped_text):
        candidate_url = _url_from_speaker_uri(stripped_text) or _clean_url_candidate(stripped_text)
        if display_name_resolver is not None:
            try:
                resolved_name = display_name_resolver(candidate_url, speaker_uri=speaker_uri)
            except TypeError:
                resolved_name = display_name_resolver(candidate_url)
            except Exception:
                resolved_name = None
            if resolved_name and not _is_url_like(resolved_name):
                normalized_text = resolved_name
        if addressee_url and _normalize_agent_id(addressee_url) == _normalize_agent_id(candidate_url):
            normalized_text = (directed_addressee.get("name") or "").strip() or normalized_text
        elif speaker_service_url and _normalize_agent_id(speaker_service_url) == _normalize_agent_id(candidate_url):
            if speaker_name and not _is_url_like(speaker_name):
                normalized_text = speaker_name

    addressee_name = (directed_addressee.get("name") or "").strip()
    if not addressee_name:
        return normalized_text

    if speaker_name:
        normalized_speaker_name = speaker_name.strip()
        if normalized_speaker_name:
            if normalized_text.strip().lower() == normalized_speaker_name.lower():
                return normalized_text
            if re.match(
                rf"^{re.escape(normalized_speaker_name)}(?:\b|[\s,:;.!?\-])",
                normalized_text.strip(),
                flags=re.IGNORECASE,
            ):
                return normalized_text

    if speaker_name and speaker_name.strip().lower() == addressee_name.lower():
        return normalized_text

    addressee_speaker_uri = directed_addressee.get("speaker_uri")
    if addressee_speaker_uri and speaker_uri:
        if _normalize_agent_id(addressee_speaker_uri) == _normalize_agent_id(speaker_uri):
            return normalized_text

    if addressee_url:
        normalized_addressee_url = _normalize_agent_id(addressee_url)
        if speaker_service_url and _normalize_agent_id(speaker_service_url) == normalized_addressee_url:
            return normalized_text
        if speaker_uri and _normalize_agent_id(speaker_uri) == normalized_addressee_url:
            return normalized_text

    if re.match(rf"^{re.escape(addressee_name)}(?:\b|[\s,:;.!?\-])", normalized_text.lstrip(), flags=re.IGNORECASE):
        return normalized_text

    return f"{addressee_name}, {normalized_text}"


def _post_with_optional_ui_pump(target_url, payload_obj, *, headers=None, timeout=None, ui_pump_callback=None):
    if ui_pump_callback is None:
        return requests.post(
            target_url,
            json=payload_obj,
            timeout=timeout,
            headers=headers,
        )

    result = {}

    def _worker():
        try:
            result["response"] = requests.post(
                target_url,
                json=payload_obj,
                timeout=timeout,
                headers=headers,
            )
        except Exception as exc:
            result["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    while worker.is_alive():
        try:
            ui_pump_callback()
        except Exception:
            pass
        time.sleep(0.05)

    if "error" in result:
        raise result["error"]

    return result["response"]


def _extract_response_envelope(response_data):
    if not isinstance(response_data, dict):
        return {}

    for key in ("openFloor", "ovon", "openfloor"):
        candidate = response_data.get(key)
        if isinstance(candidate, dict):
            return candidate

    if isinstance(response_data.get("events"), list):
        return response_data

    return {}


def _extract_events_and_sender(response_data):
    envelope = _extract_response_envelope(response_data)
    incoming_events = envelope.get("events", [])
    if not isinstance(incoming_events, list):
        incoming_events = []
    original_sender = envelope.get("sender", {})
    if not isinstance(original_sender, dict):
        original_sender = {}
    return incoming_events, original_sender


def send_broadcast_to_agents(payload_obj, urls_to_send, status_callback=None, ui_pump_callback=None):
    """Phase 1: Send broadcast to all agents and collect their responses.
    
    Args:
        payload_obj: The JSON payload to send
        urls_to_send: List of URLs to send to
        
    Returns:
        list: List of tuples (target_url, response_data, original_sender, incoming_events)
    """
    all_responses = []
    
    for target_url in urls_to_send:
        if status_callback is not None:
            try:
                status_callback(target_url, "working")
            except Exception:
                pass
        try:
            print(f"\nSending broadcast to: {target_url}")
            response = _post_with_optional_ui_pump(
                target_url,
                payload_obj,
                timeout=5,
                headers=DEFAULT_REQUEST_HEADERS,
                ui_pump_callback=ui_pump_callback,
            )
            print(f"HTTP status from {target_url}: {response.status_code}")
            print("Response headers:", dict(response.headers))
            print("Response text (first 500 chars):", response.text[:500])
            
            # Check if response is actually JSON
            if response.status_code != 200:
                if status_callback is not None:
                    try:
                        status_callback(target_url, "error")
                    except Exception:
                        pass
                CTkMessagebox(
                    title="Error",
                    message=f"Server {target_url} returned status {response.status_code}\n\nResponse: {response.text[:200]}",
                    icon="cancel"
                )
                continue
        except requests.exceptions.ConnectionError as e:
            if status_callback is not None:
                try:
                    status_callback(target_url, "error")
                except Exception:
                    pass
            print(f"Connection error for {target_url}: {e}")
            CTkMessagebox(
                title="Connection Error",
                message=f"Cannot connect to {target_url}\n\nIs the server running?",
                icon="cancel"
            )
            continue
        except requests.exceptions.Timeout:
            if status_callback is not None:
                try:
                    status_callback(target_url, "error")
                except Exception:
                    pass
            print(f"Timeout connecting to {target_url}")
            CTkMessagebox(
                title="Timeout Error",
                message=f"Connection to {target_url} timed out",
                icon="cancel"
            )
            continue
        except Exception as e:
            if status_callback is not None:
                try:
                    status_callback(target_url, "error")
                except Exception:
                    pass
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
            if status_callback is not None:
                try:
                    status_callback(target_url, "error")
                except Exception:
                    pass
            print(f"JSON decode error for {target_url}: {e}")
            CTkMessagebox(
                title="Error",
                message=f"Server {target_url} did not return valid JSON.\n\nStatus: {response.status_code}\n\nResponse: {response.text[:200]}",
                icon="cancel"
            )
            print(f"Full response text: {response.text}")
            continue

        if status_callback is not None:
            try:
                status_callback(target_url, "idle")
            except Exception:
                pass
            
        print("Response JSON:", json.dumps(response_data, indent=2))
        incoming_events, original_sender = _extract_events_and_sender(response_data)
        
        # Store response for Phase 2 processing
        all_responses.append((target_url, response_data, original_sender, incoming_events))
    
    return all_responses


def process_agent_responses(root, all_responses, floor_manager, update_conversation_history_callback, invited_agents=None, update_agent_textboxes_callback=None, extract_url_callback=None, manifest_cache=None, show_incoming_events: bool = False, directed_addressee=None, display_name_resolver=None):
    """Phase 2: Process all responses and update conversation history.
    
    Args:
        root: The main Tkinter window
        all_responses: List of response tuples from Phase 1
        floor_manager: Floor manager instance (or None)
        update_conversation_history_callback: Function to update conversation history
        invited_agents: List of invited agent info dicts (optional)
        update_agent_textboxes_callback: Function to update agent textboxes (optional)
        extract_url_callback: Function to extract URL from agent info (optional)
        manifest_cache: Dictionary to cache conversational names (optional)
    """
    def _url_from_speaker_uri(speaker_uri):
        if not speaker_uri:
            return None
        if speaker_uri.startswith("agent:http://") or speaker_uri.startswith("agent:https://"):
            return speaker_uri[len("agent:"):]
        if speaker_uri.startswith("http://") or speaker_uri.startswith("https://"):
            return speaker_uri
        return None

    for target_url, response_data, original_sender, incoming_events in all_responses:
        assistantConversationalName = ""
        assistant_url = target_url
        
        for event in incoming_events:
            if event.get("eventType") in ("publishManifests", "publishManifest"):
                manifests = event.get("parameters", {}).get("servicingManifests", [])
                if manifests:
                    manifest = manifests[0]
                    assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                    assistant_uri = manifest.get("identification", {}).get("uri", "")
                    manifest_speaker_uri = manifest.get("identification", {}).get("speakerUri", "")
                    manifest_service_url = manifest.get("identification", {}).get("serviceUrl", target_url)
                    
                    # Cache conversational name for later use
                    if manifest_cache is not None and assistantConversationalName:
                        for key in (manifest_service_url, target_url, assistant_uri, manifest_speaker_uri):
                            normalized = _normalize_agent_id(key)
                            if normalized:
                                manifest_cache[normalized] = assistantConversationalName
                    
                    # Update agent info with conversational name
                    if invited_agents is not None and extract_url_callback is not None:
                        for agent_info in invited_agents:
                            agent_info_url = extract_url_callback(agent_info)
                            # Try matching both with the manifest_service_url and target_url
                            if agent_info_url == manifest_service_url or agent_info_url == target_url:
                                if assistantConversationalName:
                                    print(f"[event_handlers] Updating agent {agent_info_url} with conversational name: {assistantConversationalName}")
                                    agent_info['conversational_name'] = assistantConversationalName
                                    print(f"[event_handlers] Agent info after update: {agent_info}")
                                    if update_agent_textboxes_callback is not None:
                                        update_agent_textboxes_callback()
                                break
                    
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
                print(f"[DEBUG] Processing utterance - speakerUri from dialogEvent: {speaker_uri}")
                
                # Get the conversational name for the actual speaker (from speakerUri in dialogEvent)
                speaker_conversational_name = None
                speaker_service_url = _url_from_speaker_uri(speaker_uri) or target_url
                if floor_manager is not None and speaker_uri != "Unknown":
                    try:
                        print(f"[DEBUG] Looking up speaker in floor manager. Available conversants: {list(floor_manager.conversants.keys())}")
                        conversant = floor_manager.conversants.get(speaker_uri)
                        if conversant:
                            speaker_conversational_name = conversant.conversational_name
                            speaker_service_url = getattr(conversant, "service_url", None) or getattr(getattr(conversant, "identification", None), "serviceUrl", None) or speaker_service_url
                            print(f"[DEBUG] Found conversant: {speaker_conversational_name}")
                        else:
                            print(f"[DEBUG] No conversant found for speaker_uri: {speaker_uri}")
                    except Exception as e:
                        print(f"Could not look up conversational name from floor manager: {e}")
                if invited_agents is not None and extract_url_callback is not None and speaker_uri:
                    normalized_speaker = _normalize_agent_id(speaker_uri)
                    if normalized_speaker:
                        for agent_info in invited_agents:
                            candidate_url = extract_url_callback(agent_info)
                            if _normalize_agent_id(candidate_url) == normalized_speaker:
                                speaker_service_url = candidate_url or speaker_service_url
                                if not speaker_conversational_name and isinstance(agent_info, dict):
                                    speaker_conversational_name = (agent_info.get("conversational_name") or "")
                                break
                if not speaker_conversational_name and manifest_cache is not None:
                    normalized_speaker = _normalize_agent_id(speaker_uri)
                    normalized_target = _normalize_agent_id(target_url)
                    if normalized_speaker and normalized_speaker in manifest_cache:
                        speaker_conversational_name = manifest_cache.get(normalized_speaker)
                    elif normalized_target and normalized_target in manifest_cache:
                        speaker_conversational_name = manifest_cache.get(normalized_target)
                
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
                    extracted_value = _prepend_direct_address_context(
                        extracted_value,
                        directed_addressee,
                        speaker_name=speaker_conversational_name,
                        speaker_uri=speaker_uri,
                        speaker_service_url=speaker_service_url,
                        display_name_resolver=display_name_resolver,
                    )
                    
                    # Update conversation history with utterance ID for deduplication
                    utterance_id = dialog_event.get("id")
                    # Prefer conversational name; fallback to URL (not speaker URI)
                    speaker_display = speaker_conversational_name or speaker_service_url or target_url or speaker_uri
                    update_conversation_history_callback(
                        speaker_display,
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
                        
        if show_incoming_events:
            ui_components.display_incoming_envelope_json(
                root,
                response_data,
                assistantConversationalName,
                assistant_url,
            )


def forward_responses_to_agents(all_responses, urls_to_send, global_conversation, update_conversation_history_callback, status_callback=None, ui_pump_callback=None, directed_addressee=None, display_name_resolver=None):
    """Phase 3: Forward all responses to all other agents (after processing all initial responses).
    
    Args:
        all_responses: List of response tuples from Phase 1
        urls_to_send: List of all agent URLs
        global_conversation: The global conversation object
        update_conversation_history_callback: Function to update conversation history
    """
    def _url_from_speaker_uri(speaker_uri):
        if not speaker_uri:
            return None
        if speaker_uri.startswith("agent:http://") or speaker_uri.startswith("agent:https://"):
            return speaker_uri[len("agent:"):]
        if speaker_uri.startswith("http://") or speaker_uri.startswith("https://"):
            return speaker_uri
        return None

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
                # Preserve directed utterances; only strip `to` when events are not directed.
                forward_was_directed = any(
                    isinstance(event, dict)
                    and event.get("eventType") == "utterance"
                    and isinstance(event.get("to"), dict)
                    and (event.get("to", {}).get("speakerUri") or event.get("to", {}).get("serviceUrl"))
                    for event in incoming_events
                )

                broadcast_events = []
                for event in incoming_events:
                    event_copy = event.copy() if isinstance(event, dict) else event
                    if isinstance(event_copy, dict) and not forward_was_directed and 'to' in event_copy:
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
                        if status_callback is not None:
                            try:
                                status_callback(other_agent_url, "working")
                            except Exception:
                                pass
                        print(f"\n=== FORWARDING TO {other_agent_url} ===")
                        print(f"Conversation ID: {global_conversation.id}")
                        print(f"Number of broadcast events: {len(broadcast_events)}")
                        print(f"Broadcast events: {json.dumps(broadcast_events, indent=2)}")
                        forward_response = _post_with_optional_ui_pump(
                            other_agent_url,
                            forward_payload,
                            headers=DEFAULT_REQUEST_HEADERS,
                            ui_pump_callback=ui_pump_callback,
                        )
                        print(f"Forward response status: {forward_response.status_code}")
                        if status_callback is not None:
                            try:
                                if forward_response.status_code == 200:
                                    status_callback(other_agent_url, "idle")
                                else:
                                    status_callback(other_agent_url, "error")
                            except Exception:
                                pass
                        
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
                                        speaker_service_url = _url_from_speaker_uri(speaker_uri)
                                        for c in global_conversation.conversants:
                                            if c.identification.speakerUri == speaker_uri:
                                                speaker_name = c.identification.conversationalName
                                                speaker_service_url = c.identification.serviceUrl or speaker_service_url
                                                break
                                        
                                        # If not found by speakerUri, try by serviceUrl
                                        if not speaker_name:
                                            for c in global_conversation.conversants:
                                                if c.identification.serviceUrl == other_agent_url:
                                                    speaker_name = c.identification.conversationalName
                                                    speaker_service_url = c.identification.serviceUrl or speaker_service_url
                                                    break

                                        if not speaker_service_url:
                                            speaker_service_url = other_agent_url
                                        
                                        # Update conversation history with utterance ID
                                        utterance_id = dialog.get("id")
                                        text = _prepend_direct_address_context(
                                            text,
                                            directed_addressee,
                                            speaker_name=speaker_name,
                                            speaker_uri=speaker_uri,
                                            speaker_service_url=speaker_service_url,
                                            display_name_resolver=display_name_resolver,
                                        )
                                        speaker_display = speaker_name or speaker_service_url or speaker_uri
                                        update_conversation_history_callback(
                                            speaker_display,
                                            text,
                                            speaker_uri,
                                            utterance_id
                                        )
                            
                            # If the agent responded, forward those responses to all other agents (recursive forwarding)
                            if forward_events:
                                responding_agent_sender = forward_response_data.get("openFloor", {}).get("sender", {})
                                # For directed utterances, route replies back to the original sender.
                                if forward_was_directed:
                                    other_recipients = [target_url] if target_url != other_agent_url else []
                                else:
                                    other_recipients = [url for url in urls_to_send if url != other_agent_url and url != target_url]
                                
                                if other_recipients:
                                    reply_to_sender = {}
                                    if isinstance(original_sender, dict):
                                        if original_sender.get("speakerUri"):
                                            reply_to_sender["speakerUri"] = original_sender.get("speakerUri")
                                        if original_sender.get("serviceUrl"):
                                            reply_to_sender["serviceUrl"] = original_sender.get("serviceUrl")

                                    response_broadcast_events = []
                                    for evt in forward_events:
                                        evt_copy = evt.copy() if isinstance(evt, dict) else evt
                                        if isinstance(evt_copy, dict):
                                            if forward_was_directed and evt_copy.get("eventType") == "utterance" and reply_to_sender:
                                                evt_copy["to"] = dict(reply_to_sender)
                                            elif not forward_was_directed and 'to' in evt_copy:
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
                                            if status_callback is not None:
                                                try:
                                                    status_callback(recipient_url, "working")
                                                except Exception:
                                                    pass
                                            print(f"  → Recursive forward from {other_agent_url} to {recipient_url}")
                                            recursive_response = _post_with_optional_ui_pump(
                                                recipient_url,
                                                recursive_payload,
                                                headers=DEFAULT_REQUEST_HEADERS,
                                                ui_pump_callback=ui_pump_callback,
                                            )
                                            print(f"  → Recursive forward status: {recursive_response.status_code}")
                                            if status_callback is not None:
                                                try:
                                                    if recursive_response.status_code == 200:
                                                        status_callback(recipient_url, "idle")
                                                    else:
                                                        status_callback(recipient_url, "error")
                                                except Exception:
                                                    pass
                                        except Exception as e:
                                            if status_callback is not None:
                                                try:
                                                    status_callback(recipient_url, "error")
                                                except Exception:
                                                    pass
                                            print(f"  → Failed recursive forward to {recipient_url}: {e}")
                        except:
                            print(f"Forward response text: {forward_response.text[:500]}")
                    except Exception as e:
                        if status_callback is not None:
                            try:
                                status_callback(other_agent_url, "error")
                            except Exception:
                                pass
                        print(f"Failed to forward response to {other_agent_url}: {e}")
