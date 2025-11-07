import openai
from openai import OpenAI
import json
from datetime import datetime
import os

import sys
import nasa_api 
import openfloor 
from openfloor import OpenFloorEvents, OpenFloorAgent, BotAgent
from openfloor import Manifest, Event, UtteranceEvent, InviteEvent, PublishManifestsEvent
from openfloor import Envelope, Manifest, Event, UtteranceEvent, InviteEvent, PublishManifestsEvent, GetManifestsEvent, ContextEvent, To, Sender, Parameters
from openfloor import agent,dialog_event,events,envelope,json_serializable,manifest

import re

conversation_state = {}

_MY_DIR = os.path.dirname(__file__)
_CONFIG_PATH = os.path.join(_MY_DIR, "assistant_config.json")
with open(_CONFIG_PATH, "r", encoding="utf-8") as file:
    agent_config = json.load(file)

client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)


nasa_key = agent_config.get("nasaAPI")
manifest = agent_config.get("manifest")

messages = [
    {"role": "system", "content": agent_config["personalPrompt"]},
    {"role": "system", "content": agent_config["functionPrompt"]}
]

def extract_location(input_text):
    location_match = re.search(r"(in|for|at) (.+)", input_text, re.IGNORECASE)
    if location_match:
        return location_match.group(2)
    else:
        return None

def search_intent(input_text):
    my_dir = os.path.dirname(__file__)
    json_file_path = os.path.join(my_dir, 'intentConcepts.json')
    with open(json_file_path, 'r') as f:
        concepts_data = json.load(f)

    matched_intents = []
    input_text_lower = input_text.lower()

    if "astronomy" in input_text_lower or "space" in input_text_lower:
        intent = "intent"
        matched_intents.append({intent:"nasa"})
    for concept in concepts_data["concepts"]:
        matched_words = [word for word in concept["examples"] if word in input_text.lower()]
        if matched_words:
            matched_intents.append({"intent": concept["name"], "matched_words": matched_words})
    return matched_intents if matched_intents else None

server_info = ""


def generate_openai_response(prompt):
    """Call OpenAI's API to generate a response based on the prompt."""
    try:
        # Build the message history from conversation_state, if available
        message_history = [{"role": "system", "content": "You are a helpful assistant named stella"}]

        # Add prior context/messages from the conversation state
        if "messages" in conversation_state:
            message_history.extend(conversation_state["messages"])  # Assuming conversation_state["messages"] is a list of messages

        # Add the latest user message to the conversation
        message_history.append({"role": "user", "content": prompt})
        print(message_history)

        # Make the API call
        response = client.chat.completions.create(
            model="gpt-4",
            messages=message_history,
            max_tokens=200,
            temperature=0.7
        )

        # Ensure response is available before trying to access it
        if response and "choices" in response and len(response.choices) > 0:
            assistant_reply = response.choices[0].message["content"].strip()

            # Update conversation_state with the latest assistant reply
            if "messages" not in conversation_state:
                conversation_state["messages"] = []
            conversation_state["messages"].append({"role": "user", "content": prompt})
            conversation_state["messages"].append({"role": "assistant", "content": assistant_reply})

            return assistant_reply
        else:
            return "Error: No valid response received."
    except openai.badRequestError as e:  # Catch OpenAI API errors
        print(f"Error with OpenAI API: {e}")
        return f"Error with OpenAI API: {str(e)}"
    except Exception as e:  # Catch general errors
        print(f"Unexpected error: {e}")
        return f"Unexpected error: {str(e)}"

def generate_response(inputOpenFloor, sender_from):
    global server_info
    global conversation_history
    server_info = ""
    response_text = "I'm not sure how to respond."
    detected_intents = []
    include_manifest_request = False

    envelope = Envelope.from_json(inputOpenFloor,as_payload=True)  
    event_list  = envelope.events
    print(f"Received event to {to_url} from {sender_from}")

    for event in event_list:
        print(event)
        event_type = event.eventType
        to_url = event.To.speakerUri if event.To and event.To.speakerUri else "Unknown"
        if event_type == "invite":
            response_text = "Thanks for the invitation, I am ready to assist."

        elif event_type == "getManifests":
            to_url = envelope.To
            response_text = "Thanks for asking, here is my manifest."
            include_manifest_request = True

        elif event_type == "utterance":
            user_input = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            detected_intents.extend(search_intent(user_input) or [])
            print(f"Detected intents: {detected_intents}")
            conversation_id = inputOpenFloor["openFloor"]["conversation"]["id"]
            response_text = ""

            if conversation_id not in conversation_state:
                conversation_state[conversation_id] = {}

            if detected_intents:
                for intent in detected_intents:
                   print(intent)
                if intent["intent"] == "nasa":
                   nasa_data = nasa_api.get_nasa()
                   explanation, picture_url = nasa_api.parse_nasa_data(nasa_data)
                   conversation_state[conversation_id]["explanation"] = explanation
                   response_text = f"Today's astronomy picture can be found at: {picture_url}. Here's an explanation {explanation}"
                   print(f"Generated nasa response:{response_text}")
                else:
                        response_text = generate_openai_response(user_input)
            else:
                response_text = generate_openai_response(user_input)
            

    currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # /find the one with utterance, make if statement
    openFloor_response = {
        "openFloor": {
            "conversation": inputOpenFloor["openFloor"]["conversation"],
            "schema": {
                "version": "0.9.0",
                "url": "not_published_yet"
            },
            "sender": {"from": sender_from},
            "events": []
        }
    }

    # Construct a single whisper event containing all intents
    if detected_intents:
        whisper_event = {
            "eventType": "whisper",
            "parameters": {
                "concepts": [
                    {
                        "concept": intent_info["intent"],
                        "matchedWords": intent_info["matched_words"]
                    }
                    for intent_info in detected_intents if "matched_words" in intent_info
                ]
            }
        }
        openFloor_response["openFloor"]["events"].append(whisper_event)

    if include_manifest_request:
        manifestRequestEvent = {
            "eventType": "publishManifest",
            "parameters": {
                "manifest":
                    manifest

            }
        }
        openFloor_response["openFloor"]["events"].append(manifestRequestEvent)

    utterance_event = {
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerId": "assistant",
                "span": {
                    "startTime": currentTime
                },
                "features": {
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": response_text}]
                    }
                }
            }
        }
    }
    openFloor_response["openFloor"]["events"].append(utterance_event)

    openFloor_response_json = json.dumps(openFloor_response)

    return openFloor_response_json