# Manage all the known Assistants


assistant_table = 

  {
    "wizard": {
      "url": "https://www.asteroute.com/ovontest",
      "contentType": "application/json"
    },
    "ovon_auto": {
      "url: "https://secondAssistant.pythonanywhere.com",
      authCode: "69jjg45cf0",
      contentType: "application/json"
    },
    "buerokratt": {
     "url": "https://dev.buerokratt.ee/ovonr/chat/rasa/ovon",
      "contentType": "application/json"
    },
    "library": {
     "url": "https://ovon.xcally.com/smartlibrary",
     "contentType": "application/json"
    }
  }

# different ways that the user could refer to the assistants we know about
assistant_set = {"wizard","asteroute","ovon auto","ovon auto service","smart library", "library","buerokratt"}

def utterance_has_assistant_name(utterance):
    assistant_name = ""
    for assistant in assistant_set:
        if assistant in utterance:
            assistant_name = assistant
   return(assistant_name)
   
synonyms_dict = {
    "wizard": "wizard",
    "asteroute": "wizard",
    "ovon auto service": "ovon_auto",
    "ovon auto": "ovon_auto",
    "smart_library":"library"
    "library":"library"
    "buerokratt":"buerokratt"
}

def get_canonical_value(input_string):
    return synonyms_dict.get(input_string, input_string)

request_for_assistant_set = {
"can I talk to ","i need to talk to ", "can i get some help from "}
