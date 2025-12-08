from tkinterweb import HtmlFrame
from customtkinter import CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, CTkComboBox,CTkCheckBox,CTkScrollableFrame,CTkFrame,set_appearance_mode, set_default_color_theme
import tkinter.messagebox as messagebox
from CTkMessagebox import CTkMessagebox
import openfloor

from tkhtmlview import HTMLLabel

import json
import requests
from datetime import datetime, date
import re
import socket

from pathlib import Path
import webbrowser


from openfloor import events,envelope,dialog_event,manifest,agent,DialogEvent,Conversation
from openfloor import OpenFloorEvents, OpenFloorAgent, BotAgent
from openfloor import Manifest, Event, UtteranceEvent, InviteEvent, UninviteEvent, RevokeFloorEvent, GrantFloorEvent, PublishManifestsEvent
from openfloor import Envelope, Sender, To, Parameters

import floor
from known_agents import KNOWN_AGENTS

client_uri = ""
client_url = ""  
private = False
invite_sentinel = False
# construct a uri for the client
today_str = ""
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

set_appearance_mode("light")
set_default_color_theme("blue")

previous_urls = []
# Initialize the last_event variable globally
last_event = None

root = CTk()
root.title("Open Floor Client Assistant")
root.geometry("600x720")  # 50% bigger than default size

CTkLabel(root, text="Enter Text:").pack(pady=(5, 0))
entry = CTkEntry(root, width=400)
entry.pack(pady=5, padx=20)

CTkLabel(root, text = "Assistant URL:").pack(pady=(10, 0))
url_combobox = CTkComboBox(root, width=400, values=[], state="normal")
# Add the values to the combo box
url_combobox.configure(values=[
    "http://localhost:8767/"
])
url_combobox.set("http://localhost:8767/") 
url_combobox.pack(pady=5, padx=20)


display_text = CTkLabel(root, text="", wraplength=400)
display_text.pack(pady=(5, 10))

CTkLabel(root, text="Invited Agents:").pack(pady=(10, 0))

# Frame to contain individual agent textboxes
agents_frame = CTkScrollableFrame(root, height=200)
agents_frame.pack(pady=5, padx=20, fill="both", expand=False)

# Label to show when no agents are invited
no_agents_label = CTkLabel(agents_frame, text="No agents invited yet")
no_agents_label.pack(pady=10)

def add_invited_agent(agent_info):
    """Add an agent to the invited agents list."""
    if agent_info not in invited_agents:
        invited_agents.append(agent_info)
    update_agent_textboxes()

def update_agent_status(old_info, new_info):
    """Update an existing agent's status in the list."""
    if old_info in invited_agents:
        index = invited_agents.index(old_info)
        invited_agents[index] = new_info
    else:
        invited_agents.append(new_info)
    update_agent_textboxes()

def create_agent_textbox(agent_info):
    """Create a frame with uninvite button and textbox for a specific agent."""
    # Create a frame to hold both button and textbox
    agent_frame = CTkFrame(agents_frame)
    agent_frame.pack(pady=2, padx=5, fill="x")
    
    # Extract URL from agent_info (format: "Invited: URL" or "Connected: Name (URL)")
    agent_url = extract_url_from_agent_info(agent_info)
    
    # Determine button text and command based on revoked status
    if agent_url in revoked_agents:
        floor_btn_text = "Grant Floor"
        floor_btn_command = lambda: grant_floor_to_agent(agent_info, agent_url)
    else:
        floor_btn_text = "Revoke Floor"
        floor_btn_command = lambda: revoke_floor_from_agent(agent_info, agent_url)
    
    # Create revoke/grant floor button
    floor_btn = CTkButton(agent_frame, text=floor_btn_text, width=90, height=25,
                         command=floor_btn_command)
    floor_btn.pack(side="left", padx=5, pady=5)
    
    # Create uninvite button
    uninvite_btn = CTkButton(agent_frame, text="Uninvite", width=80, height=25,
                            command=lambda: uninvite_agent(agent_info, agent_url))
    uninvite_btn.pack(side="left", padx=(0,5), pady=5)
    
    # Create textbox for agent info
    textbox = CTkEntry(agent_frame, placeholder_text=agent_info)
    textbox.insert(0, agent_info)
    
    # Apply strikethrough if floor has been revoked
    if agent_url in revoked_agents:
        # Create a struck-through version of the text
        struck_text = ''.join([char + '\u0336' for char in agent_info])
        textbox.delete(0, 'end')
        textbox.insert(0, struck_text)
    
    textbox.configure(state="disabled")
    textbox.pack(side="left", fill="x", expand=True, padx=(0,5), pady=5)
    
    agent_textboxes.append((agent_frame, textbox, uninvite_btn, floor_btn))
    return agent_frame

def extract_url_from_agent_info(agent_info):
    """Extract URL from agent info string."""
    if agent_info.startswith("Invited: "):
        return agent_info[9:]  # Remove "Invited: " prefix
    return agent_info

def update_agent_textbox(textbox, new_info):
    """Update an existing agent textbox with new information."""
    textbox.configure(state="normal")
    textbox.delete(0, "end")
    textbox.insert(0, new_info)
    textbox.configure(state="disabled")

def grant_floor_to_agent(agent_info, agent_url):
    """Send grant floor message to agent."""
    try:
        # Create grant floor envelope
        conversation = Conversation()
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
        global last_event
        last_event = envelope
        
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
        CTkMessagebox(title="Error", message=f"Failed to grant floor to agent: {str(e)}", icon="cancel")
        print(f"Error granting floor to agent: {e}")

def revoke_floor_from_agent(agent_info, agent_url):
    """Send revoke floor message to agent."""
    try:
        # Create revoke floor envelope
        conversation = Conversation()
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
        global last_event
        last_event = envelope
        
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
        CTkMessagebox(title="Error", message=f"Failed to revoke floor from agent: {str(e)}", icon="cancel")
        print(f"Error revoking floor from agent: {e}")

def uninvite_agent(agent_info, agent_url):
    """Send uninvite message to agent and remove from list."""
    try:
        # Create uninvite envelope
        conversation = Conversation()
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
        global last_event
        last_event = envelope
        
        # Remove from invited agents list
        if agent_info in invited_agents:
            invited_agents.remove(agent_info)
        
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
        CTkMessagebox(title="Error", message=f"Failed to uninvite agent: {str(e)}", icon="cancel")
        print(f"Error uninviting agent: {e}")

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


def construct_event(event_type, user_input, convo_id, timestamp):
    global client_uri, client_url, private, invite_sentinel
    if event_type == "utterance":
        event = openfloor.events.UtteranceEvent(
            eventType="utterance",
            to=To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=Parameters(
                dialogEvent=openfloor.dialog_event.DialogEvent(
                    speakerUri=client_uri,
                    features={
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": user_input}]
                        }
                    }
                )
            )
        )
    elif event_type == "invite":
        event = InviteEvent(
            eventType="invite",
            to=To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=Parameters()
        )
    elif event_type == "getManifests":
        event = openfloor.events.GetManifestsEvent(
            eventType="getManifests",
            to=To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=Parameters()
        )
    return event

def send_utterance():
    send_events(["utterance"])

def get_manifests():
    send_events(["getManifests"])

def invite():
    events_to_send = ["invite"]
    user_input = entry.get().strip()
    if user_input:
        events_to_send.append("utterance")
    send_events(events_to_send)

def invite_sentinel():
    send_events(["inviteSentinel","utterance"])

# The main function to send events

def send_events(event_types):
    global client_url,client_uri,assistant_url, assistant_uri, assistantConversationalName, previous_urls, last_event,private
    user_input = entry.get().strip()
    assistant_url = url_combobox.get()
    
    if assistant_url not in previous_urls:
        previous_urls.append(assistant_url)
        url_combobox.configure(values=previous_urls)
    #construct a conversation envelope
    conversation = Conversation()
    sender = Sender(
        speakerUri=client_uri,
        serviceUrl=client_url
    )
    envelope = Envelope(
        conversation=conversation,
        sender=sender
    )

   
    for event_type in event_types:
        if assistant_url and (event_type != "utterance" or user_input):
            display_text.configure(text = user_input)
        if event_type == "inviteSentinel":
            event_type = "invite"
            private = True
            invite_sentinel = True          
            user_input = "act as a sentinel in this conversation"
        elif event_type == "invite":
            inviteEvent = openfloor.events.InviteEvent(to=To(serviceUrl=url_combobox.get().strip()))
            private = True
            invite_sentinel = False
            envelope.events.append(inviteEvent)
            
            # Add to invited agents list
            invited_url = url_combobox.get().strip()
            add_invited_agent(f"Invited: {invited_url}")
            
            # If floor manager is active, add "joining floor" utterance
            if floor_manager is not None:
                floor_join_dialog = DialogEvent(
                    speakerUri=client_uri,
                    features={
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": "joining floor"}]
                        }
                    }
                )
                envelope.events.append(UtteranceEvent(dialogEvent=floor_join_dialog,
                                                      to=To(serviceUrl=url_combobox.get().strip(), private=True)))
        elif event_type == "getManifests":
            getManifestsEvent = openfloor.events.GetManifestsEvent(to=To(serviceUrl=url_combobox.get().strip()))
            envelope.events.append(getManifestsEvent)
        elif event_type == "utterance":
            if not user_input:
                messagebox.showwarning("Warning", "Please enter some text before sending an utterance.")
                return
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
            envelope.events.append(UtteranceEvent(dialogEvent=dialog,
                                                  to=To(serviceUrl=url_combobox.get().strip(), private=private)))
        
    last_event = envelope
    envelope_to_send = envelope.to_json(as_payload=True)
    
    # Convert JSON string to Python object
    try:
        payload_obj = json.loads(envelope_to_send)
        print("Payload to send:", json.dumps(payload_obj, indent=2))  # debug
        # Send POST request
        response = requests.post(
            assistant_url,
            json=payload_obj
            )
        print("HTTP status:", response.status_code)
        print("Response headers:", dict(response.headers))
        print("Response text (first 500 chars):", response.text[:500])
        
        # Check if response is actually JSON
        if response.status_code != 200:
            CTkMessagebox(title="Error", 
                         message=f"Server returned status {response.status_code}\n\nResponse: {response.text[:200]}", 
                         icon="cancel")
            return
            
        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            CTkMessagebox(title="Error", 
                         message=f"Server did not return valid JSON.\n\nStatus: {response.status_code}\n\nResponse: {response.text[:200]}", 
                         icon="cancel")
            print(f"Full response text: {response.text}")
            return
            
        print("Response JSON:", json.dumps(response_data, indent=2))
        incoming_events = response_data.get("openFloor", {}).get("events", [])
        for event in incoming_events:
            if event.get("eventType") == "publishManifests":
                manifests = event.get("parameters", {}).get("servicingManifests", [])
                if manifests:
                    manifest = manifests[0]
                    assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                    assistant_uri = manifest.get("identification", {}).get("uri", "")
                    manifest_service_url = manifest.get("identification", {}).get("serviceUrl", assistant_url)
                    
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
                    #assistant_url = manifest.get("identification", {}).get("serviceUrl", "")
                else:
                    CTkMessagebox(title="Error", message="No servicing manifests found in the response.", icon="cancel")
            elif event.get("eventType") == "utterance":
                parameters = event.get("parameters", {})
                dialog_event = parameters.get("dialogEvent", {})
                features = dialog_event.get("features", {})
                text_features = features.get("text", {})
                html_features = features.get("html", {})
                
                # Check if there's an HTML feature and display it in browser
                if html_features:
                    html_tokens = html_features.get("tokens", [])
                    if html_tokens:
                        html_value = html_tokens[0].get("value", "")
                        if html_value:
                            display_response_html(html_value)
                        
                # Check the MIME type to determine how to display the content
                mime_type = text_features.get("mimeType", "")
                tokens = text_features.get("tokens", [])  
                if tokens:
                    extracted_value = tokens[0].get("value", "No value found")
                    # If MIME type is text/plain, only display JSON response
                    if mime_type == "text/plain":
                        # For plain text, don't convert to HTML or display in browser
                        pass  # Just continue to display_response_json at the end
                    else:
                        # For other MIME types (or no MIME type), process as HTML
                        html_content = f"{convert_text_to_html(extracted_value)}"
                        display_response_html(html_content)
            display_response_json(response_data)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error processing incoming event: {error_details}")
        CTkMessagebox(title="Error", message=f"Error processing incoming event: {str(e)}\n\nCheck console for details.", icon="cancel")


# user interface functions
def getAssistantWindowTitle():
    title = "Assistant Response from " + assistantConversationalName + "  at " + assistant_url
    return title

def display_response_json(response_data):
    response_window = CTkToplevel(root)
    title = getAssistantWindowTitle()
    response_window.title(title)
    response_window.geometry("600x400")
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(response_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)

def display_response_html(html_content):
    file_path = Path.cwd() / "cards.html"
    file_path.write_text(html_content, encoding="utf-8")

    webbrowser.open(file_path.as_uri())
    

def show_outgoing_event():
    global last_event
    if last_event:
        event_window = CTkToplevel(root)
        event_window.title("Outgoing Event")
        event_text = CTkTextbox(
            event_window, wrap='word', width=600, height=400)
        event_text.insert('insert', last_event.to_json(as_payload=True, indent=2))
        event_text.configure(state='disabled')
        event_text.pack(pady=10, padx=10)
    else:
        messagebox.showinfo("Info", "No outgoing event to show")


def escape_blanks_in_url(url):
    """
    Escape blanks (spaces) in URLs by replacing them with %20
    Uses regex to find and replace spaces in URLs
    """
    # Only escape if it's a standalone URL, not already in HTML
    blank_pattern = r'\s+'
    escaped_url = re.sub(blank_pattern, '%20', url)
    return escaped_url

def convert_text_to_html(text):
    """Convert text to HTML with URL detection and blank escaping"""
    # Check if the text already contains HTML tags (like img tags)
    if '<' in text and '>' in text:
        # If it's already HTML, don't process it further to avoid breaking image links
        return text
    
    # Only process plain text for URL detection
    # Improved URL detection to prevent trailing punctuation issues
    url_pattern = r'(?<!\w)(https?://[^\s<>"\'()]+[^\s<>"\'().,])(?!\w)'

    def url_replacer(match):
        url = match.group(0)
        # Escape any blanks in the URL before creating the link
        escaped_url = escape_blanks_in_url(url)
        return f'<a href="{escaped_url}" target="_blank">{url}</a>'
    
    text_with_links = re.sub(url_pattern, url_replacer, text)
    #return text_with_links.replace("\n", "<br>")
    return text_with_links

def start_floor_manager():
    """Start a new floor manager for the current conversation."""
    global floor_manager
    try:
        # Create floor manager with current client as convener
        floor_manager = floor.create_floor_manager(convener_uri=client_uri)
        
        # Add the client as a conversant
        floor_manager.add_conversant(
            speaker_uri=client_uri,
            service_url=client_url,
            conversational_name=client_name,
            roles={floor.FloorRole.CONVENER}
        )
        
        # Show floor manager window
        show_floor_manager_window()
        
        CTkMessagebox(title="Floor Manager", 
                     message="Floor manager started successfully!", 
                     icon="info")
    except Exception as e:
        CTkMessagebox(title="Error", 
                     message=f"Failed to start floor manager: {str(e)}", 
                     icon="cancel")

def show_floor_manager_window():
    """Show the floor manager status window."""
    global floor_manager
    if not floor_manager:
        CTkMessagebox(title="Error", 
                     message="No floor manager is running", 
                     icon="cancel")
        return
        
    floor_window = CTkToplevel(root)
    floor_window.title("Floor Manager Status")
    floor_window.geometry("500x400")
    
    # Get floor status
    status = floor_manager.get_floor_status()
    
    # Create text widget to display status
    status_text = CTkTextbox(floor_window, wrap="word", width=480, height=350)
    status_text.insert("0.0", json.dumps(status, indent=2))
    status_text.configure(state="disabled")
    status_text.pack(padx=10, pady=10)
    
    # Add refresh button
    def refresh_status():
        status = floor_manager.get_floor_status()
        status_text.configure(state="normal")
        status_text.delete("0.0", "end")
        status_text.insert("0.0", json.dumps(status, indent=2))
        status_text.configure(state="disabled")
    
    refresh_button = CTkButton(floor_window, text="Refresh", command=refresh_status)
    refresh_button.pack(pady=5)

# Buttons
get_manifests_button = CTkButton(
    root, text="Get Manifests", command=get_manifests)
get_manifests_button.pack(pady=(10, 5))

invite_button = CTkButton(root, text="Invite", command=invite)
invite_button.pack(pady=5)

invite_sentinel_button = CTkButton(
    root, text="Invite sentinel", command = invite_sentinel)
invite_sentinel_button.pack(pady=5)

send_utterance_button = CTkButton(
    root, text = "Send Utterance", command=send_utterance)
send_utterance_button.pack(pady=5)

show_event_button = CTkButton(
    root, text="Show Outgoing Event", command=show_outgoing_event)
show_event_button.pack(pady=(10, 5))

start_floor_button = CTkButton(
    root, text="Start Floor Manager", command=start_floor_manager)
start_floor_button.pack(pady=5)

root.mainloop()
