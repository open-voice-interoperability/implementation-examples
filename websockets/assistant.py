import os
import sys
import datetime
import requests
import json


scriptpath = "../../lib-interop/python/lib"
sys.path.append(os.path.abspath(scriptpath))
import dialog_event as de
remote_assistants = [{"name":"test-assistant1","url":"http://localhost:8766"},{"name":"test-assistant2","url":"https://secondassistant.pythonanywhere.com"}]
assistant_name = "primary-assistant" 

class Assistant:
    def __init__(self):
        self.input_message = ""
        self.output_message = ""
        self.output_transcription = ""
        self.current_remote_assistant = ""
        self.current_remote_assistant_url = ""
        self.primary_assistant_response = ""
        self.transfer = True
	# the primary assistant has 4 items to send back
    # 1. the transcription of the primary assistant's response, which will be displayed in the 
    #    browser and rendered with TTS
    # 2. the transcription of the secondary assistant's response, which will be displayed in the
    #    browser and rendered with TTS
    # 3. The input and output OVON messages, which will be displayed in the browser, but are
    #    not actually used by the client 
    def invoke_assistant(self,transcription):
        # convert input to OVON
        self.input_message = self.convert_to_dialog_event(transcription)
        # handle locally?
        if self.handle_locally(transcription):
           self.transfer = False
           final_result = self.decide_what_to_say(transcription)
        # if not handle locally:
        else:
            # should identify secondary assistant based on OVON message, not transcription
            self.identify_assistant(transcription)
            self.primary_assistant_response = self.notify_user_of_transfer()
            resultOVON = self.send_message_to_secondary_assistant()
            self.output_transcription = self.parse_dialog_event(resultOVON)
            self.output_message = resultOVON
        # log result
        print(self.output_transcription)
        return(self.primary_assistant_response)

    # figure out if the local assistant can help	
    def handle_locally(self,transcription):
        return(False)
    
# if it can't be handled locally, find a remote assistant that can help
# use pythonanywhere server if the user asks for it
    def identify_assistant(self,transcription):
        print(transcription)
        if "ask test assistant number 2" in transcription.lower():
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
        # Send an HTTP POST request to the remote server
        response = requests.post(url, json = payload)
        # Print the HTTP response status code
        print('Response status code:', response.status_code)
        # Print the response content
        print('Response content:', response.text)
        return(response.text)

    def decide_what_to_say(self,transcription):
        return(transcription)
        
    def notify_user_of_transfer(self):
        message_to_user = "I don't know the answer, I will ask " + self.current_remote_assistant
        return(message_to_user)
    
    def convert_to_dialog_event(self,transcription):
        d=de.DialogEvent()
        d.id='user-utterance-45'
        d.speaker_id="user1234"
        d.previous_id='user-utterance-44'
        d.add_span(de.Span(start_time=datetime.datetime.now().isoformat(),end_offset_msec=1045))

        #   Add an Audio Feature
        f1=de.AudioWavFileFeature()
        d.add_feature('user-request-audio',f1)
        f1.add_token(value_url='http://localhost:8080/ab78h50ef.wav')

        #Now add a text feature
        f2=de.TextFeature(lang='en',encoding='utf-8')
        d.add_feature('user-request-text',f2)
        f2.add_token(value= transcription,confidence=0.99,start_offset_msec=8790,end_offset_msec=8845,links=["$.user-request-audio.tokens[0].value-url"])
   
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
        text1 = d.get_feature('user-request-text').get_token().value
        confidence1=d.get_feature('user-request-text').get_token().confidence
        t2=d.get_feature('user-request-text').get_token(1)
        l1=d.get_feature('user-request-text').get_token().linked_values(d)

        #Look at some of the variables
        #print(f'text packet: {f2.packet}')
        #print(f'text1: {text1} confidence1: {confidence1}')
        #print(f'text2: {t2.value} confidence1: {t2.confidence}')
        #print(f'l1: {l1}')
        return(text1)
    
    def get_input_message(self):
        print("here's the input" + str(self.input_message))
        return(self.input_message)
    
    def get_output_message(self):
        return(self.output_message)
        
    def get_output_transcription(self):
        return(self.output_transcription)
    
    def get_primary_assistant_response(self):
        return(self.primary_assistant_response)
        
        
