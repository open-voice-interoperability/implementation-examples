from simplejsondb import Database

# this NLP does not use an LLM, just keyword spotting with a simple database for information

# loads the previously saved vehicle maintenance database
vehicle = Database('vehicle.json')
intents = ["oil change", "tire rotation", "state inspection"]
oil_change_texts = ["oil change", "change oil","change my oil", "change the oil"]
tire_rotation_texts = ["tire rotation", "rotate my tires","rotated","rotate"]
state_inspection_texts = ["inspection","state inspection","inspected"]

class NLPDB:
    def __init__(self):
        self.current_result = ""
        self.current_intent = "unknown"
        
    def answer_question(self,intent):
        print("intent is " + intent)
        result = vehicle.data[intent]
        print("result is " + result)
        print(result)
        self.current_result = result
        self.current_intent = intent
       
    def can_handle(self,text):
        can_handle = False
        intent = self.get_intent(text)
        if intent != "unknown":
            can_handle = True
        return(can_handle)
     
    def get_intent(self,text):
        intent = "unknown"
        for oil_change_text in oil_change_texts:
            if oil_change_text in text:
                intent = "oil change"
                break
        for tire_rotation_text in tire_rotation_texts:
            if tire_rotation_text in text:
                intent = "tire rotation"
                break
        for state_inspection_text in state_inspection_texts:
            if state_inspection_text in text:
                intent = "state inspection"
                break
        self.current_intent = intent
        
    def get_current_result(self):
        return(self.current_result)
        
    def get_current_intent(self):
        return(self.current_intent)

