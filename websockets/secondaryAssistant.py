import os
import sys
import datetime
import requests
import json
from nlpDB import *

scriptpath = "../../lib-interop/python/lib"
sys.path.append(os.path.abspath(scriptpath))
import dialog_event as de
# if you copy Python dialog event library for convenience
#from dialog_event import *
nlp = NLPDB()
greeting = "Hi, this is OVON Auto Service, "

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
      
class SecondaryAssistant:
    def __init__(self):
        self.input_message = ""
        self.output_message = ""
        self.name = "ovon_auto"
        self.input_transcription = ""
        self.output_text = ""
        self.server_url = "https://secondassistant.pythonanywhere.com"
        self.cold_open = False
	
    def invoke_assistant(self,message):
        # self.parse_dialog_event(message)
        self.input_transcription = find_key(message,"value")
        if self.input_transcription == None:
            self.cold_open = True
            self.output_message = self.convert_to_message()
        else:
            # handle locally?
            if self.handle_locally(self.input_transcription):
                text_result = self.decide_what_to_say()
                print("text result is ")
                print(text_result)
                self.output_text = greeting + text_result
                self.output_message = self.convert_to_message()
                print("output message is:")
                print(self.output_message)
            # if not handle locally:
            else:
               #can't help
                self.output_message = self.convert_to_dialog_event("sorry, " + self.name + " cannot handle the request: " + self.get_transcription())
        return(self.output_message)

    # figure out if this assistant can help	
    def handle_locally(self,text):
        handle_locally = True
        print("checking for local handling")
        if not nlp.can_handle(text):
            handle_locally = False
        return(handle_locally)

    def decide_what_to_say(self):
        intent = nlp.get_current_intent()
        nlp.answer_question(intent)
        print("resulting answer is " + nlp.get_current_result())
        return(nlp.get_current_result())
        
    def convert_to_message(self):
        # prepare the event list
        events = []
        # right now we have only one response, then say "bye"
        return_event = {"eventType" : "bye"}
        events.append(return_event)
        # if we have an utterance (not cold open) we have a response to send back
        if not self.cold_open:
            #prepare the dialog event
            dialog_event = self.assemble_dialog_event("output")
            #prepare the utterance event
            utterance_event = {"eventType" : "utterance"}
            utterance_parameters = {}
            utterance_parameters["dialogEvent"] = dialog_event
            utterance_event["parameters"] = utterance_parameters
            events.append(utterance_event)
        # prepare the message envelope
        schema = {}
        schema["url"] = "https://ovon/conversation/pre-alpha-1.0.1"
        schema["version"] = "1.0"
        from_url = self.server_url
        sender = {}
        sender["from"] = from_url
        conversation = {}
        conversation["id"] = "WebinarDemo137"
        ovon = {}
        ovon["conversation"] = conversation
        ovon["schema"] = schema
        ovon["sender"] = sender
        ovon["responseCode"] = 200
        ovon["events"] = events
        final = {}
        final["ovon"] = ovon
        return(final)
        
    def convert_to_dialog_event(self,text):
        print("converting ")
        print(text)
        d=de.DialogEvent()
        d.id='user-utterance-45'
        d.speaker_id = self.name
        # d.previous_id='user-utterance-44'
        d.add_span(de.Span(start_time=datetime.datetime.now().isoformat(),end_offset_msec=1045))
        #Now add a text feature
        f2 = self.format_text_feature()
        print(" output event is " +str(f2))
        d.add_feature('features',f2)
        #f2.add_token(value=text,confidence=0.99,start_offset_msec=8790,end_offset_msec=8845,links=["$.user-request-audio.tokens[0].value-url"])
        print(f'dialog packet: {d.packet}')
        return(d.packet)
    
    def parse_dialog_event(self,message):
        dIn = de.DialogEvent()
        print(dIn)
        # library method is for files
        #dIn.load_json(message)
        self.my_load_json(dIn,message)
        print("incoming packet is")
        print(dIn)
        #self._packet=json.load(s,**kwargs)
        #next line is old        
        #self.input_transcription = dIn.get_feature('user-request-text').get_token().value
        #self.input_transcription = dIn.get_feature('text').get_tokens()[0].value
        #confidence1 = dIn.get_feature('user-request-text').get_token().confidence
        #dIn.get_feature('user-request-text').get_token(1)
        #l1=dIn.get_feature('user-request-text').get_token().linked_values(dIn)

        #Look at some of the variables
        # print(f'text packet: {f2.packet}')
        # print(f'text1: {text1} confidence1: {confidence1}')
        # print(f'text2: {t2.value} confidence1: {t2.confidence}')
        # print(f'l1: {l1}')
        transcription = find_key(message, 'value')
        print("transcription is ")
        print(transcription)
    
    # create the "text" feature of a dialog event
    def format_text_feature(self):
        text_value = self.output_text
        value = {}
        value["value"] = text_value
        tokens = []
        tokens.append(value)
        text = {}
        text["mimeType"] = "text/plain"
        text["tokens"] = tokens
        return text
        
    def my_load_json(self,de,message):
        stringMessage = json.dumps(message)
        de._packet = json.loads(stringMessage) 
    
    def get_input_message(self):
        print("here's the input" + str(self.input_message))
        return(self.input_message)
    
    def get_output_message(self):
        return(self.output_message)
        
    def get_transcription(self):
        return(self.input_transcription)
        
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
            text = self.format_text_feature()
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
        