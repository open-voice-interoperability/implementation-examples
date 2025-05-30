from customtkinter import CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, CTkComboBox,set_appearance_mode, set_default_color_theme
import tkinter.messagebox as messagebox
from CTkMessagebox import CTkMessagebox
from tkhtmlview import HTMLLabel

import json
import requests
from datetime import datetime,date
import re
import socket

client_uri = ""
client_url = ""  
private = False
# construct a uri for the client
today_str = ""
authority = socket.getfqdn()
hostname = socket.gethostname()
ip_address = socket.gethostbyname(hostname)
client_url = f"http://{ip_address}"
client_name = "AssistantClientConvener"

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
url_combobox.set("")  # Start blank
url_combobox.pack(pady=5, padx=20)

display_text = CTkLabel(root, text="", wraplength=400)
display_text.pack(pady=(5, 10))

# Functions for constructing uris

def get_current_date_tag_format():
    """
    Returns today’s date as a string in YYYY-MM-DD format,
    suitable for use in a tag-URI (e.g., 2025-05-23).
    """
    return date.today().isoformat()

today_str = get_current_date_tag_format()

def get_tag_uri():
    """
    Constructs a tag URI using the system's FQDN as the authority.
    Format: tag:<authority>,<YYYY-MM-DD>:<specific>
    """
    today_str = get_current_date_tag_format()
    return f"tag:{authority},{today_str}:{client_name}"

# construct the url to send the event to

def construct_to():
    to = {
            "serviceUrl": url_combobox.get().strip(),
            "private": private
        }
    return to

def send_utterance():
    send_event("utterance")

def get_manifests():
    send_event("getManifests")

def invite():
    send_event("invite")

# The main function to send events

def send_event(event_type):
    global client_url
    user_input = entry.get()
    global assistant_url 
    assistant_url = url_combobox.get()
    if assistant_url not in previous_urls:
        previous_urls.append(assistant_url)
        url_combobox.configure(values=previous_urls)

    timestamp = datetime.utcnow().isoformat()
    convo_id = f"convoID_{timestamp}"

    if assistant_url and (event_type != "utterance" or user_input):
        display_text.configure(text = user_input)

    envelope = {
        "openFloor": {
            "conversation": {"id": convo_id, "startTime": timestamp},
            "schema": {"version": "1.0.0", "url": "https://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.0.0/conversation-envelope-schema.json"},
            "sender":{
                "speakerUri" : get_tag_uri(),
                "serviceUrl": client_url
            },
            "events": [{
                "to": construct_to(),
                "eventType": event_type,
                "parameters": {} if event_type != "utterance" else {
                    "dialogEvent": {
                        "speakerUri": get_tag_uri(),
                        "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": user_input}]}}
                    }
                }
            }]
        }
    }

    global last_event, client_uri, assistant_name
    last_event = envelope
    
    try:
        response = requests.post(assistant_url, json=envelope)
        response_data = response.json()

        if event_type == "utterance":
            open_floor = response_data.get("openFloor", {})
            events = open_floor.get("events", [])
            utterance_event = next((event for event in events if event.get("eventType") == "utterance"), None)
            extracted_value = "No utterance event found"
            if utterance_event:
                parameters = utterance_event.get("parameters", {})
                dialog_event = parameters.get("dialogEvent", {})
                features = dialog_event.get("features", {})
                text_features = features.get("text", {})
                tokens = text_features.get("tokens", [])
                #if tokens:
                   # extracted_value = tokens[0].get("value", "No value found")
                    #html_content = f"<p>{convert_text_to_html(extracted_value)}</p>"
            #display_response_html(convert_text_to_html(extracted_value))
            display_response_json(response_data)

        else:
            display_response_json(response_data)

    except requests.RequestException as e:
        CTkMessagebox(title="Error", message=str(e), icon="cancel")

def display_response_json(response_data):
    response_window = CTkToplevel(root)
    response_window.title("Assistant Response")
    response_window.geometry("600x400")
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(response_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)

def display_response_html(html_content):
    html_window = CTkToplevel(root)
    html_window.title("Assistant Response (HTML)")
    html_window.geometry("600x400")
    html_label = HTMLLabel(html_window, html=html_content, width=600, height=400, background="white")
    html_label.pack(fill="both", expand=True, padx=10, pady=10)

def show_outgoing_event():
    global last_event
    if last_event:
        event_window = CTkToplevel(root)
        event_window.title("Outgoing Event")
        event_text = CTkTextbox(
            event_window, wrap='word', width=600, height=400)
        event_text.insert('insert', json.dumps(last_event, indent=2))
        event_text.configure(state='disabled')
        event_text.pack(pady=10, padx=10)
    else:
        messagebox.showinfo("Info", "No outgoing event to show")


def convert_text_to_html(text):
    # Improved URL detection to prevent trailing punctuation issues
    url_pattern = r'(?<!\w)(https?://[^\s<>"\'()]+[^\s<>"\'().,])(?!\w)'

    def url_replacer(match):
        url = match.group(0)
        return f'<a href="{url}" target="_blank">{url}</a>'
    text_with_links = re.sub(url_pattern, url_replacer, text)
    return text_with_links.replace("\n", "<br>")

# Buttons
get_manifests_button = CTkButton(
    root, text="Get Manifests", command=get_manifests)
get_manifests_button.pack(pady=(10, 5))

invite_button = CTkButton(root, text="Invite", command=invite)
invite_button.pack(pady=5)

send_utterance_button = CTkButton(
    root, text = "Send Utterance", command=send_utterance)
send_utterance_button.pack(pady=5)

show_event_button = CTkButton(
    root, text="Show Outgoing Event", command=show_outgoing_event)
show_event_button.pack(pady=(10, 5))

root.mainloop()
