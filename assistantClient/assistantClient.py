from customtkinter import CTkButton, CTkCheckBox

# Set True to enable very verbose console debug output (HTTP payloads, headers, etc.)
DEBUG_CONSOLE_HTTP = False
import openfloor

import json
import requests
from datetime import datetime
import socket
import traceback

from openfloor import events,envelope,dialog_event,manifest,agent,DialogEvent,Conversation
from openfloor import OpenFloorEvents, OpenFloorAgent, BotAgent
from openfloor import Manifest, Event, UtteranceEvent, InviteEvent, UninviteEvent, RevokeFloorEvent, GrantFloorEvent, PublishManifestsEvent
from openfloor import Envelope, Sender, To, Parameters, Conversant
from openfloor.manifest import Identification

import floor
from known_agents import KNOWN_AGENTS
import ui_components
import event_handlers

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}

client_uri = ""
client_url = ""  
private = False
# construct a uri for the client
authority = socket.getfqdn()
hostname = socket.gethostname()
ip_address = socket.gethostbyname(hostname)
client_name = "AssistantClientConvener"
client_url = f"http://{ip_address}"
client_uri = f"openFloor://{ip_address}/" + client_name

assistantConversationalName = ""
floor_manager = None
invited_agents = []  # List to keep track of invited agents
agent_textboxes = []  # List to keep track of individual agent textboxes
revoked_agents = []  # List to keep track of agents whose floor has been revoked
agent_checkboxes = {}  # Dictionary to track checkboxes: {agent_url: checkbox_widget}
manifest_cache = {}  # Dictionary to cache conversational names from manifests: {url: conversational_name}

def _extract_known_agent_url(agent_info):
    if isinstance(agent_info, dict):
        return agent_info.get("url", "")
    return agent_info

def _extract_known_agent_name(agent_info):
    if isinstance(agent_info, dict):
        return agent_info.get("conversational_name", "")
    return ""

def _build_known_agent_urls(known_agents):
    urls = []
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if url and url not in urls:
            urls.append(url)
    return urls

def _build_known_agent_name_map(known_agents):
    name_map = {}
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        name = _extract_known_agent_name(agent_info)
        if name:
            name_map[url] = name
    return name_map

def _format_known_agent_display(url, conversational_name):
    if conversational_name:
        return f"{conversational_name} | {url}"
    return url

def _build_known_agent_displays(known_agents):
    displays = []
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        display = _format_known_agent_display(url, _extract_known_agent_name(agent_info))
        if display not in displays:
            displays.append(display)
    return displays

def _build_display_to_url_map(known_agents):
    display_map = {}
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        display = _format_known_agent_display(url, _extract_known_agent_name(agent_info))
        display_map[display] = url
        display_map[url] = url
    return display_map

def _display_for_url(url):
    name = KNOWN_AGENT_NAME_BY_URL.get(url, "")
    if not name:
        name = resolve_conversational_name(f"agent:{url}", url) or ""
    if not name:
        for agent_info in invited_agents:
            if extract_url_from_agent_info(agent_info) == url:
                if isinstance(agent_info, dict):
                    name = agent_info.get("conversational_name", "")
                break
    return _format_known_agent_display(url, name)

def _build_unique_urls(*url_lists):
    ordered = []
    seen = set()
    for urls in url_lists:
        for url in urls:
            if url and url not in seen:
                ordered.append(url)
                seen.add(url)
    return ordered

def refresh_agent_combobox():
    all_urls = _build_unique_urls(KNOWN_AGENT_URLS, previous_urls)
    all_displays = [_display_for_url(url) for url in all_urls]
    url_combobox.configure(values=all_displays)

KNOWN_AGENT_URLS = _build_known_agent_urls(KNOWN_AGENTS)
KNOWN_AGENT_NAME_BY_URL = _build_known_agent_name_map(KNOWN_AGENTS)
KNOWN_AGENT_DISPLAYS = _build_known_agent_displays(KNOWN_AGENTS)
KNOWN_AGENT_DISPLAY_TO_URL = _build_display_to_url_map(KNOWN_AGENTS)

def _resolve_assistant_url(value):
    if not value:
        return value
    resolved = KNOWN_AGENT_DISPLAY_TO_URL.get(value)
    if resolved:
        return resolved
    if " | " in value:
        return value.split(" | ", 1)[-1].strip()
    return value

def _normalize_agent_id(value):
    if not value:
        return value
    if value.startswith("agent:"):
        value = value[len("agent:"):]
    return value.rstrip("/").lower()

def _cache_conversational_name(conversational_name, *keys):
    if not conversational_name:
        return
    for key in keys:
        normalized = _normalize_agent_id(key)
        if normalized:
            manifest_cache[normalized] = conversational_name

def resolve_conversational_name(speaker_uri, target_url=None):
    """Resolve a friendly name for a speaker using floor manager or manifest cache."""
    normalized_speaker = _normalize_agent_id(speaker_uri)
    normalized_target = _normalize_agent_id(target_url)

    if floor_manager is not None and normalized_speaker:
        try:
            conversant = floor_manager.conversants.get(speaker_uri)
            if conversant and conversant.conversational_name:
                return conversant.conversational_name
        except Exception:
            pass

    if normalized_speaker and normalized_speaker in manifest_cache:
        return manifest_cache.get(normalized_speaker)
    if normalized_target and normalized_target in manifest_cache:
        return manifest_cache.get(normalized_target)

    return None

def resolve_display_name_for_target(target_url, speaker_uri=None):
    if speaker_uri:
        name = resolve_conversational_name(speaker_uri, target_url)
        if name:
            return name
    for agent_info in invited_agents:
        if extract_url_from_agent_info(agent_info) == target_url:
            if isinstance(agent_info, dict):
                name = agent_info.get("conversational_name", "")
                if name:
                    return name
            break
    name = KNOWN_AGENT_NAME_BY_URL.get(target_url, "")
    if name:
        return name
    name = resolve_conversational_name(f"agent:{target_url}", target_url)
    if name:
        return name
    return target_url or speaker_uri or "Unknown"

def _normalize_display_name(name):
    if not name:
        return name
    if name.strip().lower().startswith("verity"):
        return "Verity"
    return name

# Global conversation to track conversants across the session
global_conversation = Conversation()

# Track full conversation history for context events
conversation_history_for_context = []  # List of (speaker_name, speaker_uri, text) tuples

# Track utterance IDs we've already added to conversation history to avoid duplicates
processed_utterance_ids = set()

# Setup UI appearance
ui_components.setup_appearance()

previous_urls = []
# Initialize the outgoing_events variable globally to track all sent events
outgoing_events = []

# Create main window and UI elements
root = ui_components.create_main_window()
widgets = ui_components.create_ui_elements(root, KNOWN_AGENT_DISPLAYS)

# Extract widget references for easier access
entry = widgets['entry']
url_combobox = widgets['url_combobox']
send_to_all_checkbox = widgets['send_to_all_checkbox']
show_incoming_events_checkbox = widgets['show_incoming_events_checkbox']
conversation_text = widgets['conversation_text']
get_manifests_button = widgets['get_manifests_button']
invite_button = widgets['invite_button']
send_utterance_button = widgets['send_utterance_button']
reset_conversation_button = widgets['reset_conversation_button']
agents_frame = widgets['agents_frame']
no_agents_label = widgets['no_agents_label']
show_outgoing_events_checkbox = widgets['show_outgoing_events_checkbox']
start_floor_button = widgets['start_floor_button']
show_error_log_checkbox = widgets['show_error_log_checkbox']

# Error log window state (shown/hidden via checkbox)
error_log_window = None
error_log_textbox = None
error_log_buffer = []  # list[str]

# Initialize send utterance button as disabled (no agents yet)
send_utterance_button.configure(state="disabled")

def reset_conversation_history():
    """Clear the conversation history and reset numbering."""
    global conversation_history_for_context, processed_utterance_ids
    conversation_history_for_context = []
    processed_utterance_ids = set()
    try:
        conversation_text.configure(state='normal')
        conversation_text.delete('1.0', 'end')
        conversation_text.configure(state='disabled')
    except Exception:
        pass

reset_conversation_button.configure(command=reset_conversation_history)

def log_error(message):
    """Log error message to the error log textbox."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n" + ("-" * 80) + "\n"
    error_log_buffer.append(entry)

    # If the error log window is open, append to it.
    global error_log_textbox
    if error_log_textbox is not None:
        try:
            error_log_textbox.configure(state='normal')
            error_log_textbox.insert('end', entry)
            error_log_textbox.see('end')
            error_log_textbox.configure(state='disabled')
        except Exception:
            pass
    print(message)  # Also print to console


def update_error_log_visibility():
    """Show/hide the error log window based on the checkbox."""
    global error_log_window, error_log_textbox
    try:
        if show_error_log_checkbox.get():
            if error_log_window is None or not error_log_window.winfo_exists():
                error_log_window, error_log_textbox = ui_components.create_error_log_window(root)

                # Populate with buffered log entries
                try:
                    error_log_textbox.configure(state='normal')
                    error_log_textbox.delete('0.0', 'end')
                    error_log_textbox.insert('end', ''.join(error_log_buffer))
                    error_log_textbox.see('end')
                    error_log_textbox.configure(state='disabled')
                except Exception:
                    pass

                # If user closes via X, reflect in checkbox state
                def _on_close():
                    global error_log_window, error_log_textbox
                    try:
                        show_error_log_checkbox.deselect()
                    except Exception:
                        pass
                    try:
                        if error_log_window is not None and error_log_window.winfo_exists():
                            error_log_window.destroy()
                    except Exception:
                        pass
                    error_log_window = None
                    error_log_textbox = None

                try:
                    error_log_window.protocol("WM_DELETE_WINDOW", _on_close)
                except Exception:
                    pass
        else:
            if error_log_window is not None and error_log_window.winfo_exists():
                error_log_window.destroy()
            error_log_window = None
            error_log_textbox = None
    except Exception:
        # UI should never crash on a visibility toggle
        pass

def add_invited_agent(agent_url, conversational_name='', update_ui=True):
    """Add an agent to the invited agents list."""
    # Check manifest cache for conversational name if not provided
    if not conversational_name and agent_url in manifest_cache:
        conversational_name = manifest_cache[agent_url]
    if not conversational_name:
        conversational_name = KNOWN_AGENT_NAME_BY_URL.get(agent_url, "")
    
    agent_info = {'url': agent_url, 'conversational_name': conversational_name}
    # Check if URL already exists in list
    for existing_agent in invited_agents:
        if extract_url_from_agent_info(existing_agent) == agent_url:
            # Update with conversational name if we now have one
            if conversational_name:
                existing_agent['conversational_name'] = conversational_name
                if update_ui:
                    update_agent_textboxes()
            return
    invited_agents.append(agent_info)
    add_conversant_to_global(agent_url)
    if update_ui:
        update_agent_textboxes()

def create_agent_textbox(agent_info):
    """Create a frame with uninvite button and textbox for a specific agent."""
    agent_url = extract_url_from_agent_info(agent_info)
    
    is_revoked = agent_url in revoked_agents
    
    # Create UI elements using ui_components
    agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, agent_checkbox = ui_components.create_agent_textbox_ui(
        agents_frame=agents_frame,
        agent_info=agent_info,
        agent_url=agent_url,
        is_revoked=is_revoked,
        grant_floor_callback=lambda: grant_floor_to_agent(agent_info, agent_url),
        revoke_floor_callback=lambda: revoke_floor_from_agent(agent_info, agent_url),
        uninvite_callback=lambda: uninvite_agent(agent_info, agent_url)
    )

    # UX rule: selecting any per-agent "send private" checkbox should turn off
    # the global "Send to all invited agents" mode.
    def _on_private_checkbox_toggle(url=agent_url, checkbox=agent_checkbox):
        try:
            if checkbox.get():
                send_to_all_checkbox.deselect()
        except Exception:
            pass

    try:
        agent_checkbox.configure(command=_on_private_checkbox_toggle)
    except Exception:
        pass
    
    # Store checkbox reference
    agent_checkboxes[agent_url] = agent_checkbox
    
    agent_textboxes.append((agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, agent_checkbox))
    return agent_frame

def extract_url_from_agent_info(agent_info):
    """Extract URL from agent info."""
    if isinstance(agent_info, dict):
        return agent_info.get('url', '')
    # Backwards compatibility: if agent_info is just a string URL
    return agent_info

def add_conversant_to_global(agent_url):
    """Add a conversant to the global conversation."""
    global global_conversation
    # Check if already exists
    for conversant in global_conversation.conversants:
        if conversant.identification.serviceUrl == agent_url:
            return  # Already exists
    
    # Add new conversant
    conversant = Conversant(
        identification=Identification(
            speakerUri=f"agent:{agent_url}",
            serviceUrl=agent_url,
            conversationalName=agent_url
        )
    )
    global_conversation.conversants.append(conversant)

def remove_conversant_from_global(agent_url):
    """Remove a conversant from the global conversation."""
    global global_conversation
    global_conversation.conversants = [
        c for c in global_conversation.conversants 
        if c.identification.serviceUrl != agent_url
    ]

def update_conversation_history(speaker, text, speaker_uri=None, utterance_id=None):
    """Update the conversation history text area with a new utterance."""
    global conversation_history_for_context, processed_utterance_ids

    speaker = _normalize_display_name(speaker)
    
    # Skip if we've already processed this utterance
    if utterance_id and utterance_id in processed_utterance_ids:
        return
    
    # Add to context history
    conversation_history_for_context.append((speaker, speaker_uri or speaker, text))
    
    # Mark as processed
    if utterance_id:
        processed_utterance_ids.add(utterance_id)
    
    # Get the utterance number (1-indexed based on how many we've added)
    utterance_number = len(conversation_history_for_context)
    
    conversation_text.configure(state='normal')
    current_text = conversation_text.get("1.0", "end-1c")
    if current_text:
        conversation_text.insert("end", "\n\n")  # Double newline for more spacing
    # Use uppercase and special formatting to make speaker names stand out, with number
    conversation_text.insert("end", f"{utterance_number}. [{speaker.upper()}] {text}")
    conversation_text.configure(state='disabled')
    # Auto-scroll to bottom
    conversation_text.see("end")

def update_agent_textbox(textbox, new_info):
    """Update an existing agent textbox with new information."""
    ui_components.update_agent_textbox_ui(textbox, new_info)

def grant_floor_to_agent(agent_info, agent_url):
    """Send grant floor message to agent."""
    try:
        # Create grant floor envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create grant floor event
        grant_event = GrantFloorEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(grant_event)
        
        # Send grant floor message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = requests.post(
            agent_url,
            json=payload_obj,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Grant floor sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Update floor manager if active
        if floor_manager is not None:
            try:
                floor_manager.grant_floor(agent_url)
            except Exception as e:
                print(f"Could not grant floor in floor manager: {e}")
        
        # Remove from revoked agents list
        if agent_url in revoked_agents:
            revoked_agents.remove(agent_url)
        
        # Update the display to remove strikethrough and change button
        update_agent_textboxes()
        
    except Exception as e:
        error_msg = f"Failed to grant floor to agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to grant floor to agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error granting floor to agent: {e}")

def revoke_floor_from_agent(agent_info, agent_url):
    """Send revoke floor message to agent."""
    try:
        # Create revoke floor envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create revoke floor event
        revoke_event = RevokeFloorEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(revoke_event)
        
        # Send revoke floor message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = requests.post(
            agent_url,
            json=payload_obj,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Revoke floor sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Update floor manager if active
        if floor_manager is not None:
            try:
                floor_manager.revoke_floor(agent_url)
            except Exception as e:
                print(f"Could not revoke floor in floor manager: {e}")
        
        # Track that this agent's floor has been revoked
        if agent_url not in revoked_agents:
            revoked_agents.append(agent_url)
        
        # Update the display to show strikethrough
        update_agent_textboxes()
        
    except Exception as e:
        error_msg = f"Failed to revoke floor from agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to revoke floor from agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error revoking floor from agent: {e}")

def uninvite_agent(agent_info, agent_url):
    """Send uninvite message to agent and remove from list."""
    try:
        # Create uninvite envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create uninvite event
        uninvite_event = UninviteEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(uninvite_event)
        
        # Send uninvite message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = requests.post(
            agent_url,
            json=payload_obj,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Uninvite sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Remove from global conversation
        remove_conversant_from_global(agent_url)
        
        # Remove from invited agents list by URL (since agent_info might be a reference issue)
        invited_agents[:] = [agent for agent in invited_agents if extract_url_from_agent_info(agent) != agent_url]
        
        # Remove from revoked agents list if present
        if agent_url in revoked_agents:
            revoked_agents.remove(agent_url)
            
        # Remove from floor manager if active
        if floor_manager is not None:
            # Try to find and remove agent from floor manager
            # Note: This is a simple approach, might need refinement
            try:
                floor_manager.remove_conversant(agent_url)
            except Exception as e:
                print(f"Could not remove agent from floor manager: {e}")
        
        # Update display
        update_agent_textboxes()
        
    except Exception as e:
        error_msg = f"Failed to uninvite agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to uninvite agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error uninviting agent: {e}")

def update_send_utterance_button_state():
    """Enable or disable the send utterance button based on whether there are invited agents."""
    if invited_agents:
        send_utterance_button.configure(state="normal")
    else:
        send_utterance_button.configure(state="disabled")

def update_agent_textboxes():
    """Update all agent textboxes to match the invited agents list."""
    # Clear all existing textboxes
    for item in agent_textboxes:
        if len(item) >= 3:  # Handle both old and new tuple formats
            agent_frame = item[0]
            agent_frame.destroy()
    agent_textboxes.clear()
    
    # Show or hide the no agents label
    if invited_agents:
        no_agents_label.pack_forget()
        # Create new textboxes for each agent
        for agent_info in invited_agents:
            create_agent_textbox(agent_info)
    else:
        no_agents_label.pack(pady=10)
    
    # Update send utterance button state
    update_send_utterance_button_state()


def send_utterance():
    send_events(["utterance"])

def get_manifests():
    send_events(["getManifests"])

def invite():
    # Check if the agent in the URL combobox is already invited
    assistant_url = _resolve_assistant_url(url_combobox.get())
    if assistant_url:
        # Check if this URL is already in the invited agents list
        for agent_info in invited_agents:
            if extract_url_from_agent_info(agent_info) == assistant_url:
                # Agent already invited, do nothing
                return
    
    events_to_send = ["invite"]
    user_input = entry.get().strip()
    if user_input:
        events_to_send.append("utterance")
    send_events(events_to_send)

# The main function to send events

def send_events(event_types):
    global client_url,client_uri,assistant_url, assistant_uri, assistantConversationalName, previous_urls, outgoing_events, private, global_conversation
    user_input = entry.get().strip()
    assistant_url = _resolve_assistant_url((url_combobox.get() or "").strip())
    
    # Check if we should send to all invited agents
    send_to_all = send_to_all_checkbox.get()
    
    # Determine target URLs based on event type
    if "invite" in event_types or "getManifests" in event_types:
        # For invite and getManifests, use the URL from the combobox
        target_urls = [assistant_url] if assistant_url else []
    elif send_to_all and invited_agents:
        # For utterances, extract URLs from invited agents list
        target_urls = [extract_url_from_agent_info(agent) for agent in invited_agents]
    else:
        # When send_to_all is unchecked, check individual agent checkboxes
        target_urls = []
        for agent_url, checkbox in agent_checkboxes.items():
            if checkbox.get():  # If checkbox is checked
                # Only include if the agent is in the invited list
                if any(extract_url_from_agent_info(agent) == agent_url for agent in invited_agents):
                    target_urls.append(agent_url)
    
    # For invite events, determine which URLs are new (not already invited)
    new_invite_urls = []
    if "invite" in event_types:
        already_invited_urls = [extract_url_from_agent_info(agent) for agent in invited_agents]
        new_invite_urls = [url for url in target_urls if url not in already_invited_urls]
        # If all target URLs are already invited, don't send anything
        if not new_invite_urls and "invite" in event_types and len(event_types) == 1:
            return

    if "utterance" in event_types:
        if not user_input:
            ui_components.show_app_message(root, "Warning", "Please enter some text before sending an utterance.")
            return
        update_conversation_history("You", user_input)
    
    if not target_urls:
        # Note: for utterances we send to invited agents (or selected private-agent checkboxes),
        # not directly to the combobox URL. So it’s possible to have a visible Assistant URL
        # while still having “no target” for an utterance.
        if "invite" in event_types or "getManifests" in event_types:
            ui_components.show_app_message(root, "Warning", "No Assistant URL specified.")
        elif not invited_agents:
            ui_components.show_app_message(root, "Warning", "No invited agents to send to. Invite an agent first.")
        else:
            ui_components.show_app_message(
                root,
                "Warning",
                "No agents selected. Enable 'Send to all invited agents' or select an agent checkbox.",
            )
        return
    
    # Update previous_urls while keeping KNOWN_AGENTS
    if assistant_url and assistant_url not in previous_urls:
        previous_urls.append(assistant_url)
    # Merge known and previous URLs, preserving order and removing duplicates
    refresh_agent_combobox()
    
    # When sending to all, use broadcast (no 'to' field) and send same envelope to all URLs
    # Each agent will process it as a broadcast message
    is_broadcast = send_to_all and len(target_urls) > 1
    
    # Messages sent via individual checkboxes should be private
    use_private = not send_to_all
    
    # Create the envelope once (broadcast or addressed)
    if is_broadcast:
        # Create a single envelope with no 'to' field (broadcast)
        # Use global conversation with current conversants
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )

        for event_type in event_types:
            if event_type == "invite":
                # Invite without 'to' field = broadcast invite
                inviteEvent = openfloor.events.InviteEvent()
                private = True
                envelope.events.append(inviteEvent)
                
                # Add only new target URLs to invited agents list (not already invited)
                for target_url in new_invite_urls:
                    add_invited_agent(target_url, update_ui=True)
            elif event_type == "getManifests":
                # GetManifests without 'to' field = broadcast
                getManifestsEvent = openfloor.events.GetManifestsEvent()
                envelope.events.append(getManifestsEvent)
            elif event_type == "utterance":
                # Build a DialogEvent directly and attach it to an UtteranceEvent without 'to' field
                dialog = DialogEvent(
                    speakerUri=client_uri,
                    features={
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": user_input}]
                        }
                    }
                )
                # Utterance without 'to' field = broadcast
                envelope.events.append(UtteranceEvent(dialogEvent=dialog))
            
        outgoing_events.append(envelope)
        envelope_to_send = envelope.to_json(as_payload=True)
        
        # Convert JSON string to Python object
        try:
            payload_obj = json.loads(envelope_to_send)
            if DEBUG_CONSOLE_HTTP:
                print("Payload to send (BROADCAST):", json.dumps(payload_obj, indent=2))

            if show_outgoing_events_checkbox.get():
                ui_components.display_outgoing_envelope_json(root, payload_obj, target_label="broadcast")
            
            # For invite events, only send to new agents; for other events, send to all target URLs
            urls_to_send = new_invite_urls if "invite" in event_types else target_urls
            
            # Phase 1: Send broadcast to all agents and collect their responses
            all_responses = event_handlers.send_broadcast_to_agents(payload_obj, urls_to_send)
            
            # Phase 2: Process all responses and update conversation history
            event_handlers.process_agent_responses(
                root,
                all_responses,
                floor_manager,
                update_conversation_history,
                invited_agents,
                update_agent_textboxes,
                extract_url_from_agent_info,
                manifest_cache,
                show_incoming_events=bool(show_incoming_events_checkbox.get())
            )
            
            # Phase 3: Forward all responses to all other agents (after processing all initial responses)
            event_handlers.forward_responses_to_agents(all_responses, urls_to_send, global_conversation, update_conversation_history)
        
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Error processing incoming event: {error_details}")
            ui_components.show_app_message(root, "Error", f"Error processing incoming event: {str(e)}\n\nCheck console for details.")
    
    else:
        # Send to each target URL with a properly addressed envelope
        for target_url in target_urls:
            #construct a conversation envelope for this specific target
            # Use global conversation (conversants are added on invite)
            conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
            
            sender = Sender(
                speakerUri=client_uri,
                serviceUrl=client_url
            )
            envelope = Envelope(
                conversation=conversation,
                sender=sender
            )

            for event_type in event_types:
                if event_type == "invite":
                    inviteEvent = openfloor.events.InviteEvent(to=To(serviceUrl=target_url))
                    private = True
                    envelope.events.append(inviteEvent)
                    
                    # Add to invited agents list
                    add_invited_agent(target_url, update_ui=True)
                elif event_type == "getManifests":
                    getManifestsEvent = openfloor.events.GetManifestsEvent(to=To(serviceUrl=target_url))
                    envelope.events.append(getManifestsEvent)
                elif event_type == "utterance":
                    # Build a DialogEvent directly and attach it to an UtteranceEvent
                    dialog = DialogEvent(
                        speakerUri=client_uri,
                        features={
                            "text": {
                                "mimeType": "text/plain",
                                "tokens": [{"value": user_input}]
                            }
                        }
                    )
                    # Use private flag when sending via individual checkboxes
                    envelope.events.append(UtteranceEvent(dialogEvent=dialog,
                                                          to=To(serviceUrl=target_url, private=use_private or private)))
                
            outgoing_events.append(envelope)
            envelope_to_send = envelope.to_json(as_payload=True)
            
            # Convert JSON string to Python object
            try:
                payload_obj = json.loads(envelope_to_send)
                if DEBUG_CONSOLE_HTTP:
                    print("="*80)
                    print("OUTGOING ENVELOPE JSON:")
                    print("="*80)
                    print(json.dumps(payload_obj, indent=2))
                    print("="*80)

                if show_outgoing_events_checkbox.get():
                    ui_components.display_outgoing_envelope_json(root, payload_obj, target_label=target_url)
                
                # Send POST request to this target URL
                if DEBUG_CONSOLE_HTTP:
                    print(f"\nSending to: {target_url}")
                try:
                    response = requests.post(
                        target_url,
                        json=payload_obj,
                        timeout=10,
                        headers=DEFAULT_REQUEST_HEADERS,
                    )
                except requests.RequestException as exc:
                    error_msg = f"Failed to reach {target_url}: {exc}"
                    log_error(error_msg)
                    ui_components.show_app_message(
                        root,
                        "Error",
                        f"Failed to reach {target_url}. See Error Log for details.",
                    )
                    continue
                if DEBUG_CONSOLE_HTTP:
                    print(f"HTTP status from {target_url}: {response.status_code}")
                    print("Response headers:", dict(response.headers))
                    print("Response text (first 500 chars):", response.text[:500])
                
                # Check if response is actually JSON
                if response.status_code != 200:
                    error_msg = f"Server {target_url} returned status {response.status_code}\n\nFull Response:\n{response.text}"
                    log_error(error_msg)
                    ui_components.show_app_message(
                        root,
                        "Error",
                        f"Server {target_url} returned status {response.status_code}\n\nSee Error Log for full response",
                    )
                    continue
                    
                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    error_msg = f"Server {target_url} did not return valid JSON.\n\nStatus: {response.status_code}\n\nFull Response:\n{response.text}\n\nJSON Error: {str(e)}"
                    log_error(error_msg)
                    ui_components.show_app_message(
                        root,
                        "Error",
                        f"Server {target_url} did not return valid JSON.\n\nSee Error Log for full response",
                    )
                    continue
                    
                if DEBUG_CONSOLE_HTTP:
                    print("Response JSON:", json.dumps(response_data, indent=2))
                incoming_events = response_data.get("openFloor", {}).get("events", [])
                for event in incoming_events:
                    if event.get("eventType") == "publishManifests":
                        manifests = event.get("parameters", {}).get("servicingManifests", [])
                        if manifests:
                            manifest = manifests[0]
                            assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                            assistant_uri = manifest.get("identification", {}).get("uri", "")
                            manifest_speaker_uri = manifest.get("identification", {}).get("speakerUri", "")
                            manifest_service_url = manifest.get("identification", {}).get("serviceUrl", assistant_url)
                            
                            # Cache conversational name for later use
                            _cache_conversational_name(
                                assistantConversationalName,
                                manifest_service_url,
                                target_url,
                                assistant_uri,
                                manifest_speaker_uri,
                            )
                            
                            # Update agent info with conversational name
                            for agent_info in invited_agents:
                                agent_info_url = extract_url_from_agent_info(agent_info)
                                # Try matching both with the manifest_service_url and target_url
                                if agent_info_url == manifest_service_url or agent_info_url == target_url:
                                    if assistantConversationalName:
                                        if DEBUG_CONSOLE_HTTP:
                                            print(f"Updating agent {agent_info_url} with conversational name: {assistantConversationalName}")
                                        agent_info['conversational_name'] = assistantConversationalName
                                        if DEBUG_CONSOLE_HTTP:
                                            print(f"Agent info after update: {agent_info}")
                                        update_agent_textboxes()
                                    break

                            if manifest_service_url and manifest_service_url not in previous_urls and manifest_service_url not in KNOWN_AGENT_URLS:
                                previous_urls.append(manifest_service_url)
                                refresh_agent_combobox()
                            
                            # Add agent to floor manager if active
                            if floor_manager is not None and assistant_uri:
                                try:
                                    floor_manager.add_conversant(
                                        speaker_uri=assistant_uri,
                                        service_url=manifest_service_url,
                                        conversational_name=assistantConversationalName
                                    )
                                    if DEBUG_CONSOLE_HTTP:
                                        print(f"Added {assistantConversationalName or assistant_uri} to floor manager")
                                except Exception as e:
                                    if DEBUG_CONSOLE_HTTP:
                                        print(f"Failed to add agent to floor manager: {e}")
                            #assistant_url = manifest.get("identification", {}).get("serviceUrl", "")
                        else:
                            ui_components.show_app_message(root, "Error", "No servicing manifests found in the response.")
                    elif event.get("eventType") == "utterance":
                        parameters = event.get("parameters", {})
                        dialog_event = parameters.get("dialogEvent", {})
                        features = dialog_event.get("features", {})
                        text_features = features.get("text", {})
                        html_features = features.get("html", {})
                        
                        # Extract speaker info for conversation history
                        speaker_uri = dialog_event.get("speakerUri", "Unknown")
                        
                        # Resolve speaker name for this utterance (avoid stale global name)
                        resolved_name = resolve_conversational_name(speaker_uri, target_url)
                        display_name = resolve_display_name_for_target(target_url, speaker_uri)
                        if not assistantConversationalName and resolved_name:
                            assistantConversationalName = resolved_name
                        
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
                            update_conversation_history(display_name, extracted_value, speaker_uri, utterance_id)
                            
                            # If MIME type is text/plain, only display JSON response
                            if mime_type == "text/plain":
                                # For plain text, don't convert to HTML or display in browser
                                pass  # Just continue to display_response_json at the end
                            else:
                                # For other MIME types (or no MIME type), process as HTML
                                html_content = f"{ui_components.convert_text_to_html(extracted_value)}"
                                ui_components.display_response_html(html_content)

                # Optionally show incoming events in separate windows
                if show_incoming_events_checkbox.get():
                    ui_components.display_incoming_envelope_json(
                        root,
                        response_data,
                        assistantConversationalName,
                        assistant_url,
                    )

            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                print(f"Error processing incoming event: {error_details}")
                ui_components.show_app_message(root, "Error", f"Error processing incoming event: {str(e)}\n\nCheck console for details.")


# user interface functions

def start_floor_manager():
    """Start a new floor manager for the current conversation."""
    global floor_manager
    floor_manager = ui_components.start_floor_manager_ui(root, client_uri, client_url, client_name, show_window=False, show_message=False)

# Configure button commands
get_manifests_button.configure(command=get_manifests)
invite_button.configure(command=invite)
send_utterance_button.configure(command=send_utterance)
start_floor_button.configure(command=start_floor_manager)
show_error_log_checkbox.configure(command=update_error_log_visibility)

# Automatically start floor manager on launch
start_floor_manager()

# Apply initial error log visibility
update_error_log_visibility()

root.mainloop()
