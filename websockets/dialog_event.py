import yaml
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from jsonpath_ng import jsonpath, parse

# standard element names
ELMNT_SPEAKER_ID='speaker-id'
ELMNT_ID='id'
ELMNT_PREV_ID='previous-id'
ELMNT_FEATURES='features'
ELMNT_MIME_TYPE='mimeType'
ELMNT_LANG='lang'
ELMNT_ENCODING='encoding'
ELMNT_TOKENS='tokens'
ELMNT_VALUE='value'
ELMNT_VALUE_URL='value-url'
ELMNT_LINKS='links'
ELMNT_CONFIDENCE='confidence'
ELMNT_HISTORY='history'  
ELMNT_START='start-time'
ELMNT_START_OFFSET='start-offset'
ELMNT_END='end-time'
ELMNT_END_OFFSET='end-offset'
ELMNT_SPAN='span'

class DialogPacket():
    '''class variables'''
    _feature_class_map={}
    _value_class_map={}

    '''Construct a packet'''
    def __init__(self,p={}):
        #print(f'p: {p}')
        self._packet={}
        #print(f'A1: {self.packet}')

    ### Getters and Setters ###
    # property: packet
    @property
    def packet(self):
        return self._packet

    @packet.setter
    def packet(self,p):
        self._packet=p

    @classmethod
    # return the feature class for the mimeType
    def add_feature_class(cls,mime_type,feature_class):
        cls._feature_class_map['mime_type']=feature_class

    @classmethod
    def add_default_feature_classes(cls):
        cls.add_feature_class('text/plain',TextFeature)

    @classmethod
    # return the feature class for the mimeType
    def feature_class(cls,mime_type):
        try:
            return cls._feature_class_map['mime_type']
        except:
            return Feature    

    @classmethod
    # return the feature class for the mimeType
    def value_class(cls,mime_type):
        try:
            return cls._value_class_map['mime_type']
        except:
            return str  

    ### Built-Ins ###
    def __str__(self):
        return str(self._packet)

    def __repr__(self):
        return repr(self._packet)

    ### Convert to/from JSON and YML ###
    '''Load the packet from a string or file handle. Also takes optional arguments for yaml.safe_load().'''
    def load_yml(self,s,**kwargs):
        self._packet=yaml.safe_load(s,**kwargs) 

    '''Convert the packet to YML and optionally save it to a file. Returns a string containing the YML. Also takes optional arguments for yaml.safe_dump().'''
    def dump_yml(self,file=None,**kwargs):
        if file:
            return yaml.safe_dump(self._packet,file,**kwargs)
        else:
            return yaml.safe_dump(self._packet,**kwargs)

    '''Load the packet from a string or file handle. Also takes optional arguments for yaml.safe_load().'''
    def load_json(self,s,**kwargs):
        self._packet=json.load(s,**kwargs) 

    '''Convert the packet to JSON and optionally save it to a file. Also takes optional arguments for json.dumps().'''
    def dump_json(self,file=None,**kwargs):
        kwargs.setdefault('default', str)
        kwargs.setdefault('indent', 4)
        
        s=json.dumps(self._packet,**kwargs)
        if file: file.write(s)
        return s

class Span(DialogPacket):
    ### Constructor ###
    '''Construct an empty dialog event'''
    def __init__(self,start_time=None,start_offset=None,end_time=None,end_offset=None,end_offset_msec=None,start_offset_msec=None):
        super().__init__()
        if start_time is not None: 
           self.start_time=start_time
        if self.start_offset is not None:
           self.start_offset=start_offset
        if start_offset_msec is not None:
           self.start_offset=f'PT{round(start_offset_msec/1000,6)}'
        if end_time is not None: 
           self.end_time=end_time
        if end_offset is not None:
            self.end_offset=end_offset   
        if end_offset_msec is not None:
           self.end_offset=f'PT{round(end_offset_msec/1000,6)}'

    # property: start_time
    @property
    def start_time(self):
        return self._packet.get(ELMNT_START,None)

    @start_time.setter
    def start_time(self,s):
        self._packet[ELMNT_START]=s

    # property: end_time
    @property
    def end_time(self):
        return self._packet.get(ELMNT_END,None)

    @end_time.setter
    def end_time(self,s):
        self._packet[ELMNT_END]=s

    # property: start-offset
    @property
    def start_offset(self):
        return self._packet.get(ELMNT_START_OFFSET,None)

    @start_offset.setter
    def start_offset(self,s):
        self._packet[ELMNT_START_OFFSET]=s

    # property: end-offset
    @property
    def end_offset(self):
        return self._packet.get(ELMNT_END_OFFSET,None)

    @end_offset.setter
    def end_offset(self,s):
        self._packet[ELMNT_END_OFFSET]=s

class DialogEvent(DialogPacket):
    ### Constructor ###
    '''Construct an empty dialog event'''
    def __init__(self):
       super().__init__()

    # property: speeaker_id
    @property
    def speaker_id(self):
        return self._packet.get(ELMNT_SPEAKER_ID,None)

    @speaker_id.setter
    def speaker_id(self,s):
        self._packet[ELMNT_SPEAKER_ID]=s

    # property: id
    @property
    def id(self):
        return self._packet.get(ELMNT_ID,None)

    @id.setter
    def id(self,s):
        self._packet[ELMNT_ID]=s

    # property: prevous_id
    @property
    def previous_id(self):
        return self._packet.get(ELMNT_PREV_ID,None)

    @previous_id.setter
    def previous_id(self,s):
        self._packet[ELMNT_PREV_ID]=s

    # property: features
    @property
    def features(self):
        return self._packet.get(ELMNT_FEATURES,None)

    @features.setter
    def features(self,s):
        self._packet[ELMNT_FEATURES]=s

    # property: span
    @property
    def span(self):
        return self._packet.get(ELMNT_SPAN,None)

    @span.setter
    def span(self,s):
        self._packet[ELMNT_SPAN]=s
        print(f'self._packet[ELMNT_SPAN]: {self._packet[ELMNT_SPAN]}')

    ### Add/Get span
    def add_span(self,span):
        if self.span is None:
            self.span={}    
        self.span=span.packet
        print(f'self.span:{self.span}')
        return span  

    ### Add/Get Features ###
    def add_feature(self,feature_name,feature):
        if self.features is None:
            self.features={}
        
        self.features[feature_name]=feature.packet
        return feature

    def get_feature(self,feature_name):
        print(self)
        print(self.features)
        print("getting " + feature_name)
        fpacket=self.features.get(feature_name,None)
        
        if fpacket is not None: 
            feature=self.feature_class(fpacket.get(ELMNT_MIME_TYPE,None))()
            feature.packet=fpacket
            return feature
        else:
            return None

class Feature(DialogPacket):
    ### Constructor ###

    '''Construct a dialog event feature'''
    def __init__(self,mime_type=None,lang=None,encoding=None,p={},**kwargs):
        #print(f'Feature() kwargs: {kwargs}')
        super().__init__(**kwargs)        
        #print(f'A2: {self.packet}')
        self._token_class=Token
        
        if mime_type is not None: 
            self._packet[ELMNT_MIME_TYPE]=mime_type
        if lang is not None:
            self._packet[ELMNT_LANG]=lang
        if encoding is not None:
                self._packet[ELMNT_ENCODING]=encoding
        
        #Create the empty array of arrays for the tokens.
        self._packet[ELMNT_TOKENS]=[]

    def add_token(self, **kwargs):
        my_token=self._token_class(**kwargs)
        self.tokens.append(my_token.packet)
        return my_token

    def get_token(self,token_ix=0):
        try:
            token=self._token_class()
            token.packet=self.tokens[token_ix]
        except:
            token=None
        return token

    ### Getters and Setters ###
    # property: mime_type
    @property
    def mime_type(self):
        return self._packet.get(ELMNT_MIME_TYPE,None)

    # property: lang
    @property
    def lang(self):
        return self._packet.get(ELMNT_LANG,None)

    # property: encoding
    @property
    def encoding(self):
        return self._packet.get(ELMNT_ENCODING,None)

    # property: tokens
    @property
    def tokens(self):
        return self._packet.get(ELMNT_TOKENS,None)
    
#Note need to debug default argument overrides.
class TextFeature(Feature):
    def __init__(self,**kwargs):
        #print(f'Text Feature() kwargs: {kwargs}')
        super().__init__(mime_type='text/plain',**kwargs)
        #print(f'A3: {self.packet}')
        self._token_class=Token

class AudioWavFileFeature(Feature):
    def __init__(self,**kwargs):
        #print(f'Text Feature() kwargs: {kwargs}')
        super().__init__(mime_type='audio/wav',**kwargs)
        #print(f'A3: {self.packet}')
        self._token_class=Token

class Token(DialogPacket):
    ### Constructor ###
    '''Construct a dialog event token.'''
    def __init__(self,value=None,value_url=None,links=None,confidence=None,start_time=None,start_offset=None,end_time=None,end_offset=None,end_offset_msec=None,start_offset_msec=None):
        super().__init__()

        if value is not None: 
            self.value=value
        if value_url is not None:
            self._packet[ELMNT_VALUE_URL]=value_url
        if links is not None:
            self._packet[ELMNT_LINKS]=links
        if confidence is not None:
            self._packet[ELMNT_CONFIDENCE]=confidence   
        if start_time is not None or start_offset is not None or end_time is not None or end_offset is not None or end_offset_msec is not None or start_offset_msec is not None:
            self.add_span(Span(start_time=start_time,start_offset=start_offset,end_time=end_time,end_offset=end_offset,end_offset_msec=end_offset_msec,start_offset_msec=start_offset_msec))
    
    ### Getters and Setters ###
    @property
    def value(self):
        return self._packet.get(ELMNT_VALUE,None)

    @value.setter
    def value(self,value):
        self._packet[ELMNT_VALUE]=value   

    @property    
    def confidence(self):
        return self._packet.get(ELMNT_CONFIDENCE,None)

    @confidence.setter
    def confidence(self,confidence):
        self._packet[ELMNT_CONFIDENCE]=confidence  

    # property: span
    @property
    def span(self):
        return self._packet.get(ELMNT_SPAN,None)

    @span.setter
    def span(self,s):
        self._packet[ELMNT_SPAN]=s
        print(f'self._packet[ELMNT_SPAN]: {self._packet[ELMNT_SPAN]}')

    @property
    def links(self):
        return self._packet.get(ELMNT_LINKS,None)

    @links.setter
    def links(self,links):
        self._packet[ELMNT_LINKS]=links   

    ### Add/Get span
    def add_span(self,span):
        if self.span is None:
            self.span={}    
        self.span=span.packet
        print(f'self.span:{self.span}')
        return span  
    
    ### Get linked values
    def linked_values(self,dialog_event):
        values=[]
        for l in self.links:
            print(f'l: {l}')
            jsonpath_expr = parse(l)
            for match in jsonpath_expr.find(dialog_event.features):
                if match:
                    values.append([match.full_path,match.value])
        return values

class History(DialogPacket):
    ### Constructor ###
    '''Construct a dialog history object token.'''
    def __init__(self):
        super().__init__()
        
        #Create the empty array of dialog events
        self._packet[ELMNT_HISTORY]=[]

    def add_event(self, dialog_event):
        self._packet[ELMNT_HISTORY].append(dialog_event)
        return dialog_event

    def get_event(self,ix=0):
        try:
            event=DialogEvent()
            event.packet=self._packet[ELMNT_TOKENS][ix]
        except:
            event=None
        return event