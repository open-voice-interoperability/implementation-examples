import os
import sys
import datetime
import requests
import json
from nlp import *

scriptpath = "../../lib-interop/python/lib"
sys.path.append(os.path.abspath(scriptpath))
import dialog_event as de
remote_assistants = [{"name":"testassistant","url":"http://localhost:8766","protocols":["HTTP"]},{"name":"ovon_auto","url":"https://secondassistant.pythonanywhere.com","protocols":"[HTTP"}]
#remote_assistants = [{"name":"asteroute","url":"https://asteroute.com/ovontest","protocols":["HTTP"]},{"name":"OVON Auto Service","url":"https://secondassistant.pythonanywhere.com","protocols":"[HTTP"}]
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
        self.input_transcription = ""
        self.output_transcription = ""
        self.current_remote_assistant = ""
        self.current_remote_assistant_url = ""
        self.primary_assistant_response = ""
        self.name = assistant_name
        self.transfer = True
        
	# the primary assistant has 4 items to send back
    # 1. the transcription of the primary assistant's response, which will be displayed in the 
    #    browser and rendered with TTS
    # 2. the transcription of the secondary assistant's response, which will be displayed in the
    #    browser and rendered with TTS
    # 3. The input and output OVON messages, which will be displayed in the browser, but are
    #    not actually used by the client 
    def invoke_assistant(self,transcription):
        print("working on " + transcription)
        self.input_transcription = transcription
        # convert input to OVON
        #self.input_message = self.convert_to_dialog_event(transcription)
        self.input_message = self.convert_to_message(direction="input")
        print("input message is " + str(self.input_message))
        # handle locally?
        if self.handle_locally(transcription):
           print("handling locally with LLM")
           self.transfer = False
           self.output_transcription = self.decide_what_to_say(transcription)
           self.output_message = self.convert_to_message(direction="output")
        # if not handle locally:
        else:
            # should identify secondary assistant based on OVON message, not transcription
            self.identify_assistant(transcription)
            self.primary_assistant_response = self.notify_user_of_transfer()
            resultOVON = self.send_message_to_secondary_assistant()
            self.output_transcription = self.parse_dialog_event(resultOVON)
            #add the name of the secondary assistant
            self.output_transcription = "here's the answer from " + self.current_remote_assistant + ": " + self.output_transcription
            self.output_message = resultOVON
        # log result
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
        '''
        for apology in give_up:
            print(apology)
            print(local_result)
            if apology in local_result:
                handle_locally = False
                break
        '''
        print(local_processing)
        return(local_processing)
    
# if it can't be handled locally, find a remote assistant that can help
# use pythonanywhere server if the user asks for it
    def identify_assistant(self,transcription):
        print(transcription)
        if "ovon auto service" in transcription.lower():
            remote_assistant = remote_assistants[1]
        else:
            remote_assistant  = remote_assistants[0]
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
        print('Response status code:', response.status_code)
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
        print("direction is " + direction)
        #prepare the dialog event
        dialog_event = self.assemble_dialog_event(direction)
        #prepare the utterance event
        utterance_event = {"eventType" : "utterance"}
        utterance_parameters = {}
        utterance_parameters["dialogEvent"] = dialog_event
        utterance_event["parameters"] = utterance_parameters
        print("direction is " + direction)
        #prepare invite event
        invite_event = self.assemble_invite_event(direction)
       
        #assemble event list
        events = []
        events.append(invite_event)
        events.append(utterance_event)
        #add "bye" event if system is speaking
        
        if direction == "output":
            return_event = {"eventType" : "bye"}
            events.append(return_event)
            
        #prepare the message envelope
        schema = {}
        schema["url"] = "https://ovon/conversation/pre-alpha-1.0.1"
        schema["version"] = "1.0"
        from_url = self.server_url
        sender = {}
        sender["from"] = from_url
        ovon = {}
        ovon["schema"] = schema
        conversation = {}
        conversation["id"] = "WebinarDemo137"
        ovon["conversation"] = conversation
        ovon["sender"] = sender
        ovon["responseCode"] = 200
        ovon["events"] = events
        
        final = {}
        final["ovon"] = ovon
        return(final)
    
    #not used right now
    def convert_to_dialog_event(self,transcription):
        d=de.DialogEvent()
        d.id='user-utterance-45'
        d.speaker_id="user1234"
        d.previous_id='user-utterance-44'
        d.add_span(de.Span(start_time=datetime.datetime.now().isoformat(),end_offset_msec=1045))

        #   Add an Audio Feature
        f1=de.AudioWavFileFeature()
        d.add_feature('userRequestAudio',f1)
        f1.add_token(value_url='http://localhost:8080/ab78h50ef.wav')

        #Now add a text feature
        f2 = self.format_text_feature()
        #f2=de.TextFeature(lang='en',encoding='utf-8')
        #d.add_feature('userRequestText',f2)
        #f2.add_token(value= transcription,confidence=0.99,start_offset_msec=8790,end_offset_msec=8845,links=["$.user-request-audio.tokens[0].value-url"])
        print(" output event is " +str(f2))
        d.add_feature('features',f2)
        print(f'dialog packet: {d.packet}')

        #Now save the dialog event to YML and JSON
        #with open("../sample-json/utterance0.json", "w") as file: d.dump_json(file)
        #with open("../sample-yaml/utterance0.yml", "w")  as file: d.dump_yml(file)
        return(d.packet)
    
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
        
