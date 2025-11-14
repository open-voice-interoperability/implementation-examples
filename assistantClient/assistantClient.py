from tkinterweb import HtmlFrame
from customtkinter import CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, CTkComboBox,CTkCheckBox,set_appearance_mode, set_default_color_theme
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
from openfloor import Manifest, Event, UtteranceEvent, InviteEvent, PublishManifestsEvent
from openfloor import Envelope, Manifest, Event, UtteranceEvent, InviteEvent,Sender, To, Parameters

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

set_appearance_mode("light")
set_default_color_theme("blue")

previous_urls = []
# Initialize the last_event variable globally
last_event = None

root = CTk()
root.title("Open Floor Client Assistant")

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

destination_url = url_combobox.get().strip()


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
        response_data = response.json()
        print("Response JSON:", json.dumps(response_data, indent=2))
        incoming_events = response_data.get("openFloor", {}).get("events", [])
        for event in incoming_events:
            if event.get("eventType") == "publishManifests":
                manifests = event.get("parameters", {}).get("servicingManifests", [])
                if manifests:
                    manifest = manifests[0]
                    assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                    assistant_uri = manifest.get("identification", {}).get("uri", "")
                    #assistant_url = manifest.get("identification", {}).get("serviceUrl", "")
                else:
                    CTkMessagebox(title="Error", message="No servicing manifests found in the response.", icon="cancel")
            elif event.get("eventType") == "utterance":
                parameters = event.get("parameters", {})
                dialog_event = parameters.get("dialogEvent", {})
                features = dialog_event.get("features", {})
                text_features = features.get("text", {})
                        
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
        CTkMessagebox(title="Error", message=f"Error processing incoming event: {str(e)}", icon="cancel")


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

root.mainloop()
