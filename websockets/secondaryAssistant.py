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

class SecondaryAssistant:
    def __init__(self):
        self.input_message = ""
        self.output_message = ""
        self.name = "Superior Auto Service"
        self.input_transcription = ""
        self.output_text = ""
	
    def invoke_assistant(self,message):
        self.parse_dialog_event(message)
        print(self.input_message)
        # handle locally?
        if self.handle_locally(self.input_transcription):
            text_result = self.decide_what_to_say()
            print("text result is ")
            print(text_result)
            self.output_message = self.convert_to_dialog_event(text_result)
            print("output message is:")
            print(self.output_message)
        # if not handle locally:
        else:
           #can't help
            self.output_message = self.convert_to_dialog_event("sorry, " + self.name + " cannot handle the request: " + self.get_transcription())
            
        # should also log result
        print(self.output_message)
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
    
    def convert_to_dialog_event(self,text):
        print("converting ")
        print(text)
        d=de.DialogEvent()
        d.id='user-utterance-45'
        d.speaker_id = self.name
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
        f2.add_token(value=text,confidence=0.99,start_offset_msec=8790,end_offset_msec=8845,links=["$.user-request-audio.tokens[0].value-url"])
   
        print(f'dialog packet: {d.packet}')

        #Now save the dialog event to YML and JSON
        #with open("../sample-json/utterance0.json", "w") as file: d.dump_json(file)
        #with open("../sample-yaml/utterance0.yml", "w")  as file: d.dump_yml(file)
        return(d.packet)
    
    def parse_dialog_event(self,message):
        dIn = de.DialogEvent()
        print(dIn)
        # library method is for files
        #dIn.load_json(message)
        self.my_load_json(dIn,message)
        #self._packet=json.load(s,**kwargs) 
        self.input_transcription = dIn.get_feature('user-request-text').get_token().value
        confidence1 = dIn.get_feature('user-request-text').get_token().confidence
        dIn.get_feature('user-request-text').get_token(1)
        l1=dIn.get_feature('user-request-text').get_token().linked_values(dIn)

        #Look at some of the variables
        # print(f'text packet: {f2.packet}')
        # print(f'text1: {text1} confidence1: {confidence1}')
        # print(f'text2: {t2.value} confidence1: {t2.confidence}')
        # print(f'l1: {l1}')
    
        
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
        