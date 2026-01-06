import json

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

assistant_instance_dict = {}

# after processing input, remove or update assistant_instance_dict
def finalize_conversation(message,assistant_instance):
    conversation_id = get_conversation_id(message)
    # if the message contains a "bye" event, we can remove the conversation
    if contains_specific_event("bye",message):
       remove_assistant_instance(conversation_id)
    # otherwise, if this is a new conversation (contains "invite"), we can add it to the assistant_instance_dict
    # if this is an utterance in a continuing conversation, we can update the assistant_instance
    else:
        add_assistant_instance(conversation_id,assistant_instance)


def get_conversation_id(message):
    return find_key(message,"id")

def get_conversation_instance(conversation_id):
    assistant_instance = get_assistant_instance(conversation_id)
    if assistant_instance is not None:
        return assistant_instance
    else:
        return "not_found"

def add_assistant_instance(conversation_id, assistant_instance):
    assistant_instance_dict[conversation_id] = assistant_instance

def get_assistant_instance(conversation_id):
    if conversation_id in assistant_instance_dict:
        return assistant_instance_dict[conversation_id]
    else:
        return None

def remove_assistant_instance(conversation_id):
    del assistant_instance_dict[conversation_id]

def contains_specific_event(event_type,message):
    contains_event = False
    ovon = message.get("ovon")
    print(ovon)
    events = ovon.get("events")
    for event in events:
        event_value = event.get("eventType",event)
        if event_value == event_type:
            contains_event = True
            break
    return contains_event
        
    