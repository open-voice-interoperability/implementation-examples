from customtkinter import CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, CTkComboBox,set_appearance_mode, set_default_color_theme
import tkinter.messagebox as messagebox
from CTkMessagebox import CTkMessagebox
from tkhtmlview import HTMLLabel

import json
import requests
from datetime import datetime
import re

# ejcAdded
# beginning of asr tts
import speech_recognition as sr
import pyttsx3
#you also need to install PyAudio

def speak(text):
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()

def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        recognizer.adjust_for_ambient_noise(source) #optional but helps with accuracy
        audio = recognizer.listen(source)

    try:
        print("Recognizing...")
        query = recognizer.recognize_google(audio)  # Use Google Web Speech API
        print(f"You said: {query}")
        return query.lower()
    except sr.UnknownValueError:
        print("Sorry, I didn't catch that.")
        return ""
    except sr.RequestError as e:
        print(f"Could not request results from Google Speech Recognition service; {e}")
        return ""
#end of asr tts

set_appearance_mode("light")
set_default_color_theme("blue")

previous_urls = []
# Initialize the last_event variable globally
last_event = None


root = CTk()
root.title("Open Voice Assistant")

CTkLabel(root, text="Enter Text:").pack(pady=(5, 0))
entry = CTkEntry(root, width=400)
entry.pack(pady=5, padx=20)

CTkLabel(root, text="Server URL:").pack(pady=(10, 0))
url_combobox = CTkComboBox(root, width=400, values=[], state="normal")
url_combobox.set("")  # Start blank
url_combobox.pack(pady=5, padx=20)

display_text = CTkLabel(root, text="", wraplength=400)
display_text.pack(pady=(5, 10))

# Functions
def on_submit():
    url = url_combobox.get().strip()
    if url and url not in previous_urls:
        previous_urls.append(url)
        url_combobox.configure(values=previous_urls)
# ejcAdded
    input = listen()
    send_event("utterance", "ASR", input )


def request_manifest():
    send_event("requestManifest", "UI", "")

def invite():
    send_event("invite", "UI", "")

# ejcAdded
user_input = ""
def send_event(event_type, input_type, input_value ):
    if input_type == "UI":
        user_input = entry.get()
    else:
        user_input = input_value
    url = url_combobox.get()
    if url not in previous_urls:
        previous_urls.append(url)
        url_combobox.configure(values=previous_urls)

    timestamp = datetime.utcnow().isoformat()
    convo_id = f"convoID_{timestamp}"

    if url and (event_type != "utterance" or user_input):
        display_text.configure(text=user_input)

    envelope = {
        "ovon": {
            "conversation": {"id": convo_id, "startTime": timestamp},
            "schema": {"version": "0.9.0", "url": "not_published_yet"},
            "sender": {"from": "Debbie"},
            "events": [{
                "to": url,
                "eventType": event_type,
                "parameters": {} if event_type != "utterance" else {
                    "dialogEvent": {
                        "speakerId": "Debbie",
                        "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": user_input}]}}
                    }
                }
            }]
        }
    }
    global last_event
    last_event = envelope
    
    try:
        response = requests.post(url, json=envelope)
        response_data = response.json()

        if event_type == "utterance" or event_type == "invite":
            ovon = response_data.get("ovon", {})
            events = ovon.get("events", [])
            utterance_event = next((event for event in events if event.get("eventType") == "utterance"), None)
            extracted_value = "No utterance event found"
            if utterance_event:
                parameters = utterance_event.get("parameters", {})
                dialog_event = parameters.get("dialogEvent", {})
                features = dialog_event.get("features", {})
                text_features = features.get("text", {})
                tokens = text_features.get("tokens", [])
                if tokens:
                    extracted_value = tokens[0].get("value", "No value found")
                    html_content = f"<p>{convert_text_to_html(extracted_value)}</p>"
                    # ejcAdded
                    speak(extracted_value)
            # display_response_html(convert_text_to_html(extracted_value))

        else:
            display_response_json(response_data)

    except requests.RequestException as e:
        CTkMessagebox(title="Error", message=str(e), icon="cancel")

def display_response_json(response_data):
    response_window = CTkToplevel(root)
    response_window.title("Server Response")
    response_window.geometry("600x400")
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(response_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)

def display_response_html(html_content):
    html_window = CTkToplevel(root)
    html_window.title("Server Response (HTML)")
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
request_manifest_button = CTkButton(
    root, text="Request Manifest", command=request_manifest)
request_manifest_button.pack(pady=(10, 5))

invite_button = CTkButton(root, text="Invite", command=invite)
invite_button.pack(pady=5)

send_utterance_button = CTkButton(
    root, text="Speak to Agent", command=on_submit)
send_utterance_button.pack(pady=5)

show_event_button = CTkButton(
    root, text="Show Outgoing Event", command=show_outgoing_event)
show_event_button.pack(pady=(10, 5))

root.mainloop()
