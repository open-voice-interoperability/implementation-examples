import openai
import json
from datetime import datetime, date

import os
import logging
logging.basicConfig(level=logging.DEBUG)
import ast
import socket
from  agentic_hallucination import interactive_process

# information about the assistant
with open("./assistant_config.json", "r") as file:
    agent_config = json.load(file)

manifest = agent_config.get("manifest")

assistant_url = manifest["identification"]["serviceUrl"]
assistant_name = manifest["identification"]["conversationalName"]
assistant_uri = manifest["identification"]["speakerUri"]

# information about the client and assistant
# client information will be obtained from the event
# client_url and client_uri will be set when the event is received
client_url = "unknown"  
client_uri = "unknown"

conversation_state = {}

messages = [
    {"role": "system", "content": agent_config["personalPrompt"]},
    {"role": "system", "content": agent_config["functionPrompt"]}
]


private = True
hallucination_threshold = .5  # Set the threshold for flagging a hallucination

def construct_to():
    global client_url, client_uri, private
    to = {
        "speakerUri": client_uri,
        "private": private
    }

    logging.debug(f"client_uri is {client_uri!r}")
    return to



def generate_response(inputOPENFLOOR, sender_from):
    global conversation_history
    global client_url, client_uri, assistant_uri, assistant_url, messages, conversation_state 
    client_url = sender_from
    
    response_text = "I'm not sure how to respond."
    detected_intents = []
    include_manifest_request = False
    print("inputOPENFLOOR", inputOPENFLOOR)
    client_uri = inputOPENFLOOR["openFloor"]["sender"].get("speakerUri", "unknown")

    for event in inputOPENFLOOR["openFloor"]["events"]:
        event_type = event["eventType"]
        if event_type == "invite":
            # Handle invite events
            utt_event = next((e for e in inputOPENFLOOR["openFloor"]["events"] if e["eventType"] == "whisper"), None)

            if utt_event:
                # Handle the invite that has a whisper event
                whisper_text = utt_event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                detected_intents.extend([])
                if detected_intents:
                    response_text = "Hello! How can I assist you today?"
            else:
                # Handle the bare invite event
                print(event_type)
                if event_type == "invite":
                    server_info = f"Server: {client_url}"
                    response_text = "Thanks for the invitation, I am ready to assist."

        elif event_type == "getManifests":
            response_text = "Thanks for asking, here is my manifest."
            include_manifest_request = True

        elif event_type == "utterance":
            user_input = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            conversation_id = inputOPENFLOOR["openFloor"]["conversation"]["id"]
            response_text = ""

            if conversation_id not in conversation_state:
                conversation_state[conversation_id] = {}
            # this agent only has one intent, "fixHallucination", so no need for intent parameter
            response_components = interactive_process(user_input)
            logging.info(f"generated {response_components}.")
            response_dict = ast.literal_eval(response_components) 
            if response_dict["applicable"] == "no":
                response_text = ("the request was to verify:" + 
                                user_input + "." + " However, this utterance is neither factual nor fictional. " +
                                response_dict["explanation"] + ". " 
                )
           
            else: response_text = ("the request was to verify:" + 
                                user_input + "." + "The utterance is " +
                                response_dict["decision"] + " with a likelihood of being factual of " +
                                str(response_dict["factual_likelihood"]) + ". " +
                                response_dict["explanation"] + ". " 
            )
                                          
    currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    openfloor_response = {
        "openFloor": {
            "conversation": inputOPENFLOOR["openFloor"]["conversation"],
            "schema": {
                "version": "1.0.0",
                "url": "https://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.0.0/conversation-envelope-schema.json"
            },
            "sender": {"speakerUri": assistant_uri, 
                       "serviceUrl": assistant_url  
            },  
            "events": []
        }
    }
    
    if include_manifest_request:
        manifestRequestEvent = {
            "to": construct_to(),
            "eventType": "publishManifests",
            "parameters": {
                "servicingManifests":[
                    manifest
                    ]
            }
        }
        openfloor_response["openFloor"]["events"].append(manifestRequestEvent)

    utterance_event = {
        "to": construct_to(),
        "eventType": "utterance",
        "parameters": {
            "dialogEvent": {
                "speakerUri": assistant_uri,
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
    openfloor_response["openFloor"]["events"].append(utterance_event)

    openfloor_response_json = json.dumps(openfloor_response)

    return openfloor_response_json