import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system
from datetime import date, timedelta, datetime

def is_valid_date(date, **kwargs):
    if kwargs.get('constraint') and kwargs.get('constraint') == 'future_date':
        date = datetime.strptime(date, '%Y-%m-%d').date()
        today = date.today()
        if date < today:
            return False
    return True

def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('reschedule_trip')
    responses = Responses('reschedule_trip')
    
    flight_confirmation_number = dialog.get_slot(
                                        'FlightConfirmationNumber', intent)
    passenger_last_name = dialog.get_slot('PassengerLastName', intent)
    passenger_last_name_spell_out = dialog.get_slot(
        'PassengerLastNameSpellOut', intent)
    new_departure_date = dialog.get_slot(
        'NewDepartureDate', intent, preference='interpretedValue')
    customer_id = dialog.get_session_attribute(intent_request, 'customer_id')
    
    if flight_confirmation_number:
        dialog.set_session_attribute(
                intent_request, 'flight_confirmation_number', 
                flight_confirmation_number)
        session_attributes = dialog.get_session_attributes(intent_request)
        
    flight_confirmation_number_from_session = dialog.get_session_attribute(
        intent_request, 'flight_confirmation_number')
        
    if flight_confirmation_number_from_session: 
        dialog.set_slot(
            'FlightConfirmationNumber', 
            flight_confirmation_number_from_session, intent)
        flight_confirmation_number = flight_confirmation_number_from_session
        
    if passenger_last_name:
        dialog.set_session_attribute(
            intent_request, 'passenger_last_name', passenger_last_name)
        session_attributes = dialog.get_session_attributes(intent_request)
        
    # passenger_last_name_from_session = dialog.get_session_attribute(
    #     intent_request, 'passenger_last_name')
        
    # if passenger_last_name_from_session: 
    #     dialog.set_slot(
    #         'PassengerLastName', passenger_last_name_from_session, intent)
    #     passenger_last_name = passenger_last_name_from_session
        
    if passenger_last_name_spell_out:
        passenger_last_name = passenger_last_name_spell_out
        dialog.set_slot(
            'PassengerLastName', passenger_last_name_spell_out, intent)
    
    if flight_confirmation_number and not customer_id:
        status, customer_id = airline_system.get_customer_id(
                                                flight_confirmation_number)
        if not status:
            dialog.set_slot('FlightConfirmationNumber', None, intent)
            dialog.set_session_attribute(
                intent_request, "flight_confirmation_number", None)
            prompt = prompts.get('InvalidFlightNumberPrompt')
            return dialog.elicit_slot(
                    'FlightConfirmationNumber', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
        else:
            dialog.set_session_attribute(
                intent_request, 'customer_id', customer_id)
                    
    if passenger_last_name and not intent['state'] == 'Fulfilled':
        status = airline_system.check_last_name(
                                            passenger_last_name, customer_id)
        if not status:
            prompt = prompts.get('InvalidLastNamePrompt')
            return dialog.elicit_slot(
                    'PassengerLastNameSpellOut', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
    
    if new_departure_date:
        if not is_valid_date(new_departure_date, constraint='future_date'):
            prompt = prompts.get('NewDepartureDateFromPast')
            return dialog.elicit_slot(
                        'NewDepartureDate', active_contexts,
                        session_attributes, intent,
                        [{'contentType': 'PlainText', 'content': prompt}])
    
    # by default delegate the to lex
    return dialog.delegate(active_contexts, session_attributes, intent)        