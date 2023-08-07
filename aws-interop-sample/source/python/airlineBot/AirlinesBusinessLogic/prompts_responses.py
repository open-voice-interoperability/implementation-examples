import json

class Prompts():
    def __init__(self, intent_name):
        print('intent: ', intent_name)
        f = open('prompts_responses/'+intent_name+'.json')
        self.data = json.load(f)
        
    def get(self, messageid, **attributes):
        if not self.data.get(messageid):
            raise Exception("Prompt not associated for the id: ", messageid)
        return self.data.get(messageid).format(**attributes)
        
class Responses():
    def __init__(self, intent_name):
        print('intent: ', intent_name)
        f = open('prompts_responses/'+intent_name+'.json')
        self.data = json.load(f)
        
    def get(self, messageid, **attributes):
        if not self.data.get(messageid):
            raise Exception("Response not associated for the id: ", messageid)
        return self.data.get(messageid).format(**attributes)
