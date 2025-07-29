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
is_sentinel = False  # Flag to indicate if the assistant is acting as a sentinel
invited_sentinel = False  # Flag to indicate if the assistant has been invited as a sentinel
doing_invite = False  # Flag to indicate if the assistant is currently handling an invite
decision = "factual"  # Default decision for the assistant

conversation_state = {}

messages = [
    {"role": "system", "content": agent_config["personalPrompt"]},
    {"role": "system", "content": agent_config["functionPrompt"]}
]


private = True
hallucination_threshold = .5  # Set the threshold for flagging a hallucination

def search_intent(input_text):
    my_dir = os.path.dirname(__file__)
    json_file_path = os.path.join(my_dir, 'intentConcepts.json')
    with open(json_file_path, 'r') as f:
        concepts_data = json.load(f)

    matched_intents = []
    input_text_lower = input_text.lower()

    for concept in concepts_data["concepts"]:
        matched_words = [word for word in concept["examples"] if word in input_text_lower]
        if matched_words:
            matched_intents.append({"intent": concept["name"], "matched_words": matched_words})
    return matched_intents if matched_intents else None

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
    global client_url, client_uri, assistant_uri, assistant_url, messages, conversation_state,is_sentinel, invited_sentinel, doing_invite, private, manifest,decision 
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
            utt_event = next((e for e in inputOPENFLOOR["openFloor"]["events"] if e["eventType"] == "utterance"), None)

            if utt_event:
                # Handle the invite that has an utterance event
                utterance_text = utt_event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                detected_intents.extend(search_intent(utterance_text) or [])
                if detected_intents:
                    response_text = "ok, i will be a hallucination sentinel in this conversation."
                    invited_sentinel = True
                    doing_invite = True
                    private = True
            else:
                # Handle the bare invite event
                print(event_type)
                if event_type == "invite":
                    server_info = f"Server: {client_url}"
                    response_text = "Thanks for the invitation, I am ready to assist."

        elif event_type == "getManifests":
            response_text = "Thanks for asking, here is my manifest."
            include_manifest_request = True

        elif event_type == "utterance" and not doing_invite:
            user_input = event["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
            conversation_id = inputOPENFLOOR["openFloor"]["conversation"]["id"]
            response_text = ""

            if conversation_id not in conversation_state:
                conversation_state[conversation_id] = {}
            # this agent only has one intent, "fixHallucination", so no need for intent parameter
            # here is where we call the LLM to process the user input
            response_components = interactive_process(user_input)
            logging.info(f"generated {response_components}.")
            response_dict = ast.literal_eval(response_components) 
            decision = response_dict.get("decision", "factual")
            if response_dict["applicable"] == "no":
                response_text = ("the request was to verify: " + 
                                user_input + "." + " However, this utterance is neither factual nor fictional. " +
                                response_dict["explanation"]
                )
             
            else: 
                response_text = ("the request was to verify: " + 
                                user_input + "." + "The utterance is " +
                                decision + " with a likelihood of being factual of " +
                                str(response_dict["factual_likelihood"]) + ". " +
                                response_dict["explanation"] 
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
    # cases for handling the sentinel invitation and responses
    if invited_sentinel:
         doing_invite = False  # Reset the invite handling flag after responding
         invited_sentinel = False  # Reset the sentinel invitation flag after responding
         # If the assistant is invited as a sentinel, set the is_sentinel flag to True
         # and add the utterance event to the response
         is_sentinel = True
         openfloor_response["openFloor"]["events"].append(utterance_event)

    elif is_sentinel == False or decision == "not factual":
        # Only add the utterance event if the assistant is not a sentinel or if the response is not factual
        # This prevents the assistant from responding if it is acting as a sentinel
        openfloor_response["openFloor"]["events"].append(utterance_event)

    openfloor_response_json = json.dumps(openfloor_response)

    return openfloor_response_json