# SPDX-License-Identifier: Apache-2.0 

import os
import sys
import datetime
import requests
import json
import secrets
from nlp import *

scriptpath = "../../lib-interop/python/lib"
sys.path.append(os.path.abspath(scriptpath))
import dialog_event as de
import assistantMgr as am

assistant_name = "primaryAssistant" 
nlp = NLP()
give_up = ["I'm sorry","I apologize", "I am sorry"]


def find_key(data, target):
    if isinstance(data, dict):
        if target in data:
            return data[target]
        else:
            for key, value in data.items():
                result = find_key(value, target)
                if result is not None:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = find_key(item, target)
            if result is not None:
                return result
    return None
    
    
class Assistant:
    def __init__(self,server_url):
        self.server_url = server_url
        print("server url is " + server_url)
        self.user = "test_user"
        self.input_message = ""
        self.output_message = ""
        self.raw_transcription = ""
        self.input_transcription = ""
        self.output_transcription = ""
        self.current_remote_assistant = ""
        self.current_remote_assistant_url = ""
        self.primary_assistant_response = ""
        self.name = assistant_name
        self.transfer = True
        self.conversations = {}
        self.in_dialog_with_secondary_assistant = False
        
	# the primary assistant has 4 items to send back
    # 1. the transcription of the primary assistant's response, which will be displayed in the 
    #    browser and rendered with TTS
    # 2. the transcription of the secondary assistant's response, which will be displayed in the
    #    browser and rendered with TTS
    # 3. The input and output OVON messages, which will be displayed in the browser, but are
    #    not actually used by the client 
    # Cases
    # 1. We have a message with a known conversation id that indicates an input that continues an ongoing conversation. 
    # In that case we need to revive the earlier dialog and resume.
    # 2. The user asked for a specific assistant by name, so there is no need to figure out what assistant to use.
    # We send the input to the requested assistant.
    #    a. the input is a bare invite, so the secondary assistant just asks the user what kind of help they need
    #    b. the input also contains a request, e.g. "I need to talk to OVON Auto about an oil change"
    # 3. The user asked a question without specifying the assistant. Then there are two cases
    #    a. try to handle the question locally
    #    b. if we can't handle locally, we have to figure out what assistant to use and send it the request

    def invoke_assistant(self,transcription):
        self.raw_transcription = transcription
        self.input_transcription = transcription
        # in "deconstruct" we take apart the utterance into "assistant name" and "user_request". We also look for a carrier phrase
        # that gets discarded
        deconstructed_utterance = deconstruct(self.input_transcription)
        # replace the current transcription with the actual user_request
        self.input_transcription = deconstructed_utterance.get("user_request")
        # convert input to OVON
        #self.input_message = self.convert_to_dialog_event(transcription)
        self.input_message = self.convert_to_message(direction="input")
        print("input message is " + str(self.input_message))
        print(deconstructed_utterance)
        # Case 1 are we already in a dialog?
        # this is the only case involving a remote assistant where we don't need an invite
        if self.in_dialog_with_secondary_assistant:
            resultOVON = self.send_message_to_secondary_assistant()
            self.output_transcription = self.parse_dialog_event(resultOVON)
            self.output_message = resultOVON
        # Case 2 did the user ask for a specific assistant?
        
        elif deconstructed_utterance.get("assistant_name") is not None:
            requested_assistant_info = am.get_requested_assistant_info(self.raw_transcription)
            requested_assistant = requested_assistant_info.get("name")
            print("requested assistant is " + requested_assistant)
            self.current_remote_assistant = requested_assistant
            self.current_remote_assistant_url = requested_assistant_info.get("url")
            self.primary_assistant_response = self.notify_user_of_transfer()
            invite_event = self.assemble_invite_event("output")
            self.append_event(invite_event)
            resultOVON = self.send_message_to_secondary_assistant()
            self.output_transcription = self.parse_dialog_event(resultOVON)
            # if the result does not contain "bye" event, we're still talking with secondary assistant
            # if !has_bye_event():
            # self.in_dialog_with_secondary_assistant = True
            #add the name of the secondary assistant
            self.output_transcription = "here's the response from " + self.current_remote_assistant + ": " + self.output_transcription
            self.output_message = resultOVON
        # Case 3, is this something this assistant can handle locally?
        elif self.handle_locally(self.input_transcription):
            print("handling locally")
            self.transfer = False
            self.output_transcription = self.decide_what_to_say(self.input_transcription)
            self.output_message = self.convert_to_message(direction = "output")
        # if not handle locally:
        # figure out what assistant to use and get response
        else:
            # should identify secondary assistant based on OVON message, not transcription
            self.identify_assistant(self.input_transcription)
            self.primary_assistant_response = self.notify_user_of_transfer()
            resultOVON = self.send_message_to_secondary_assistant()
            self.output_transcription = self.parse_dialog_event(resultOVON)
            #add the name of the secondary assistant
            self.output_transcription = "here's the answer from " + self.current_remote_assistant + ": " + self.output_transcription
            self.output_message = resultOVON
        # should add code here to log result
        print(self.output_transcription)
        return(self.primary_assistant_response)

    # figure out if the local assistant can help	
    def handle_locally(self,transcription):
        local_processing = True
        if ("my car" or "OVON Auto Service") in transcription:
            local_processing = False
            print("can't handle locally")
        else:
            local_result = self.decide_what_to_say(transcription)
            print("result from LLM is " + local_result)
            self.output_transcription = local_result
        # if the result contains an apology for not being able to handle the request, we need to find another assistant. this needs some work to make the LLM give up and not answer
        print(local_processing)
        return(local_processing)
    
# if it can't be handled locally, find a remote assistant that can help
# use pythonanywhere server if the user asks for it
    def identify_assistant(self,transcription):
        print(transcription)
        remote_assistant = am.find_name_with_keywords(transcription.lower())
        self.current_remote_assistant = remote_assistant.get("name")
        print(self.current_remote_assistant)
        self.current_remote_assistant_url = remote_assistant.get("url")

    def send_message_to_secondary_assistant(self):
    # URL endpoint to send the POST request
        url = self.current_remote_assistant_url
        # Request payload data
        payload = self.input_message
        print("sending message to assistant at " + url)
        # Send an HTTP POST request to the remote server
        response = requests.post(url, json = payload)
        # Print the HTTP response status code
        # Print the response content
        print('Response content:', response.text)
        return(response.text)

    def decide_what_to_say(self,text):
        nlp.answer_question(text)
        print("asking " + text + "getting answer" +nlp.get_current_result())
        return(nlp.get_current_result())
        
    def notify_user_of_transfer(self):
        message_to_user = "I don't know the answer, I will ask " + self.current_remote_assistant
        return(message_to_user)
        
    def convert_to_message(self,direction):
        #prepare the dialog event if the user has a request other than to talk to an assistant
        events = []
        if self.input_transcription != "":
            dialog_event = self.assemble_dialog_event(direction)
            #prepare the utterance event
            utterance_event = {"eventType" : "utterance"}
            utterance_parameters = {}
            utterance_parameters["dialogEvent"] = dialog_event
            utterance_event["parameters"] = utterance_parameters
            events.append(utterance_event)
        
        # prepare invite event
        # only relevant for output from assistant (user doesn't send "invite")
        if direction == "output":
            invite_event = self.assemble_invite_event(direction)
            #add invite to  event list
            
            
            events.append(invite_event)            
        #prepare the conversation envelope
        schema = {}
        schema["url"] = "https://github.com/open-voice-interoperability/lib-interop/schemas/conversation-envelope/0.9.0"
        schema["version"] = "0.9.0"
        from_url = self.server_url
        sender = {}
        sender["from"] = from_url
        ovon = {}
        ovon["schema"] = schema
        conversation = {}
        conversation["id"] = generate_conversation_id()
        ovon["conversation"] = conversation
        ovon["sender"] = sender
        ovon["responseCode"] = 200
        ovon["events"] = events
        final = {}
        final["ovon"] = ovon
        return(final)
   
    def parse_dialog_event(self,string_event):
        d = de.DialogEvent()
        print("received event is: " + string_event)
        json_event = json.loads(string_event)
        d._packet = json_event
        # Interrogate this object
        # in this example we are just interested in the text
        #text1 = d.get_feature('user-request-text').get_token().value
        #confidence1=d.get_feature('user-request-text').get_token().confidence
        #t2=d.get_feature('user-request-text').get_token(1)
        #l1=d.get_feature('user-request-text').get_token().linked_values(d)
        #Look at some of the variables
        #print(f'text packet: {f2.packet}')
        #print(f'text1: {text1} confidence1: {confidence1}')
        #print(f'text2: {t2.value} confidence1: {t2.confidence}')
        #print(f'l1: {l1}')
        transcription = find_key(json_event, 'value')
        print("transcription is ")
        print(transcription)
        return(transcription)
        
       #create the "text" feature of a dialog event
    def format_text_feature(self,text_value):
        value = {}
        value["value"] = text_value
        tokens = []
        tokens.append(value)
        text = {}
        text["mimeType"] = "text/plain"
        text["tokens"] = tokens
        return text  
    
    def append_event(self,event):
        events = find_key(self.input_message,"events")
        print("input message before")
        print(self.input_message)
        events.append(event)
        print(events)
       # self.input_message["events"] = events
        print("input message")
        print(self.input_message)
        
    def warn_delay(self, transcription):
        return("Ok, I'll check into your question: " + transcription + ".  just a minute")
        
    def get_input_message(self):
        print("here's the input" + str(self.input_message))
        return(self.input_message)
    
    def get_output_message(self):
        return(self.output_message)
        
    def get_output_transcription(self):
        return(self.output_transcription)
    
    def get_primary_assistant_response(self):
        return(self.primary_assistant_response)
        
    #utilities for putting together specific events
    def assemble_dialog_event(self,direction):
        features = {}
        text = ""
        features["text"] = text
        dialog_event = {}
        # input from a user
        if direction == "input":
            dialog_event["speakerId"] = self.user
            text = self.format_text_feature(self.input_transcription)
        else:
            dialog_event["speakerId"] = self.name
            text = self.format_text_feature(self.output_transcription)
        features["text"] = text
        span = {}
        span["startTime"] = datetime.datetime.now().isoformat()
        dialog_event["span"] = span
        dialog_event["features"] = features
        return(dialog_event)
        
    def assemble_invite_event(self,direction):
        invite_event = {"eventType" : "invite"}
        to_url_parameters = {}
        to_url_parameters["url"] = self.current_remote_assistant_url
        invite_event_parameters = {}
        invite_event_parameters["to"] = to_url_parameters
        invite_event["parameters"] = invite_event_parameters
        return(invite_event)
        
def request_assistant(transcription):
    assistant_name = ""
    lower_transcription = transcription.lower()
    for request in am.request_for_assistant_set:
        print("request for assistant is " + request)
        lower_request = request.lower()
        print(lower_transcription)
        if lower_request in lower_transcription:
            lower_transcription.replace(lower_request,"")
            assistants_list = am.synonyms_dict.keys()
            for name in assistants_list:
                if name in lower_transcription:
                    print("found " + name)
                    assistant_name = name
                    break
            break
    return(assistant_name)

def specific_assistant_request(transcription):
    specific_assistant = False
    requested_assistant_info = am.get_requested_assistant_info(transcription)
    if len(requested_assistant_info) == 0:
        specific_assistant = False
    else:
        requested_assistant = next(iter(requested_assistant_info.keys()))
        if requested_assistant != "":
            specific_assistant = True
    return specific_assistant
    
def generate_conversation_id():
    # Generate a random URL-safe string
    random_urlsafe = secrets.token_urlsafe(12)
    return(random_urlsafe)

# take apart utterance in case there is a reference to an assistant and carrier phrase
# so if the user says "i need to ask ovon auto if my car needs and oil change", that will
# become "if my car needs an oil change" with "ovon_auto" as the assistant
def deconstruct(transcription):
    deconstructed_utterance = {}
    assistant_name = ""
    user_request = transcription
    user_request = user_request.lower()
    if specific_assistant_request(user_request):
        assistant_name = request_assistant(transcription)
        user_request = user_request.replace(assistant_name, "")
        deconstructed_utterance["assistant_name"] = assistant_name
    print(am.request_for_assistant_set)
    for carrier in am.request_for_assistant_set:
        if carrier in user_request:
            user_request = user_request.replace(carrier,"")
            break
    user_request = user_request.strip()
    deconstructed_utterance["user_request"] = user_request
    return(deconstructed_utterance)

    
