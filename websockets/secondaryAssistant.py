import os
import sys
import datetime
import requests
import json

scriptpath = "../../lib-interop/python/lib"
sys.path.append(os.path.abspath(scriptpath))
import dialog_event as de

class SecondaryAssistant:
    def __init__(self):
        self.input_message = ""
        self.output_message = ""
        self.name = "test-assistant1"
        self.input_transcription = ""
	
    def invoke_assistant(self,message):
        self.input_message = message
        print(self.input_message)
        # handle locally?
        if self.handle_locally(message):
            final_result = self.decide_what_to_say(message)
        # if not handle locally:
        else:
           #can't help
            result = self.convert_to_dialog_event("sorry, " + self.name + " cannot handle this request")
            print(result)
        # log result
        return(result)

    # figure out if this assistant can help	
    def handle_locally(self,message):
        return(False)

    def decide_what_to_say(self,transcription):
        return(transcription)
    
    def convert_to_dialog_event(self,transcription):
        d=de.DialogEvent()
        d.id='user-utterance-45'
        d.speaker_id= self.name
        d.previous_id='user-utterance-44'
        d.add_span(de.Span(start_time=datetime.datetime.now().isoformat(),end_offset_msec=1045))
        '''
        #   Add an Audio Feature
        f1=de.AudioWavFileFeature()
        d.add_feature('user-request-audio',f1)
        f1.add_token(value_url='http://localhost:8080/ab78h50ef.wav')
        '''

        #Now add a text feature
        f2=de.TextFeature(lang='en',encoding='utf-8')
        d.add_feature('user-request-text',f2)
        f2.add_token(value= transcription,confidence=0.99,start_offset_msec=8790,end_offset_msec=8845,links=["$.user-request-audio.tokens[0].value-url"])
   
        print(f'dialog packet: {d.packet}')

        #Now save the dialog event to YML and JSON
        #with open("../sample-json/utterance0.json", "w") as file: d.dump_json(file)
        #with open("../sample-yaml/utterance0.yml", "w")  as file: d.dump_yml(file)
        return(d.packet)
    
    def parse_dialog_event(self,event):
        #Now interrogate this object
        self.input_transcription = d.get_feature('user-request-text').get_token().value
        confidence1=d.get_feature('user-request-text').get_token().confidence
        t2=d.get_feature('user-request-text').get_token(1)
        l1=d.get_feature('user-request-text').get_token().linked_values(d)

        #Look at some of the variables
        # print(f'text packet: {f2.packet}')
        # print(f'text1: {text1} confidence1: {confidence1}')
        # print(f'text2: {t2.value} confidence1: {t2.confidence}')
        # print(f'l1: {l1}')
    
    def get_input_message(self):
        print("here's the input" + str(self.input_message))
        return(self.input_message)
    
    def get_output_message(self):
        return(self.output_message)
        