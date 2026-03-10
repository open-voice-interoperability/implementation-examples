from customtkinter import CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, CTkComboBox,CTkCheckBox,set_appearance_mode, set_default_color_theme
import tkinter.messagebox as messagebox
from CTkMessagebox import CTkMessagebox
from tkhtmlview import HTMLLabel

import json
import requests
from datetime import datetime,date
import re
import socket
import openfloor


from openfloor import dialog_event,events,envelope,json_serializable,manifest

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

assistant_url = url_combobox.get().strip()
user_input = entry.get().strip()


def construct_event(event_type, user_input, convo_id, timestamp):
    global client_uri, client_url, private, invite_sentinel
    if event_type == "utterance":
        event = openfloor.events.UtteranceEvent(
            eventType="utterance",
            to=openfloor.events.To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=openfloor.events.Parameters(
                dialogEvent=dialog_event.DialogEvent(
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
        event = openfloor.events.InviteEvent(
            eventType="invite",
            to=openfloor.envelope.To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=openfloor.events.Parameters()
        )
    elif event_type == "getManifests":
        event = openfloor.events.GetManifestsEvent(
            eventType="getManifests",
             to=openfloor.envelope.To(
                serviceUrl=url_combobox.get().strip(),
                private=private
            ),
            parameters=openfloor.events.Parameters()
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
    global client_url,client_uri,assistant_url, user_input,assistant_uri, assistantConversationalName, previous_urls, last_event,private
    user_input = entry.get().strip()
    assistant_url = url_combobox.get()
    
    if assistant_url not in previous_urls:
        previous_urls.append(assistant_url)
        url_combobox.configure(values=previous_urls)
    #construct a conversation envelope
    conversation = openfloor.envelope.Conversation()
    sender = openfloor.envelope.Sender(
        speakerUri=client_uri,
        serviceUrl=client_url
    )
    envelope = openfloor.Envelope(
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
            inviteEvent = openfloor.events.InviteEvent()
            private = True
            invite_sentinel = False
            envelope.events.append(inviteEvent)
        elif event_type == "getManifests":
            getManifestsEvent = openfloor.events.GetManifestsEvent()
            envelope.events.append(getManifestsEvent)
        elif event_type == "utterance":
            if not user_input:
                messagebox.showwarning("Warning", "Please enter some text before sending an utterance.")
                return
            # Build a DialogEvent directly and attach it to an UtteranceEvent
            dialog = openfloor.dialog_event.DialogEvent(
                speakerUri=client_uri,
                features={
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": user_input}]
                    }
                }
            )
            envelope.events.append(openfloor.events.UtteranceEvent(dialogEvent=dialog,
                                                  to=openfloor.envelope.To(speakerUri=assistant_uri, serviceUrl=assistant_url, private=private)))
        
    last_event = envelope
    envelope_to_send = envelope.to_json(as_payload=True)
    
    try:
      
        # envelope_to_send is a JSON string; convert to an object so requests sends a proper JSON payload
        try:
            payload_obj = json.loads(envelope_to_send)
        except Exception:
            payload_obj = envelope_to_send
        response = requests.post(assistant_url, json=payload_obj, headers={"Content-Type": "application/json"})
        print(response)
        response_data = response.json()
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
                tokens = text_features.get("tokens", [])
                #if tokens:
                    # extracted_value = tokens[0].get("value", "No value found")
                    #html_content = f"<p>{convert_text_to_html(extracted_value)}</p>"
                    #display_response_html(convert_text_to_html(extracted_value))
        display_response_json(response_data)

    except:
        e = Exception("Error sending event to the assistant.")
        CTkMessagebox(title="Error", message=str(e), icon="cancel")


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
        event_text.insert('insert', last_event.to_json(as_payload=True, indent=2))
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
