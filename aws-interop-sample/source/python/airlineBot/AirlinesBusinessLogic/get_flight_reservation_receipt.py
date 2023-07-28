

import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system

def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('get_flight_reservation_receipt')
    responses = Responses('get_flight_reservation_receipt')
    
    flight_confirmation_number = dialog.get_slot(
                                        'FlightConfirmationNumber', intent)
    passenger_last_name = dialog.get_slot('PassengerLastName', intent)
    passenger_last_name_spell_out = dialog.get_slot('PassengerLastNameSpellOut', intent)
    receipt_delivery_channel = dialog.get_slot('ReceiptDeliveryChannel', intent)
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
        
    passenger_last_name_from_session = dialog.get_session_attribute(
        intent_request, 'passenger_last_name')
        
    if passenger_last_name_from_session: 
        dialog.set_slot(
            'PassengerLastName', passenger_last_name_from_session, intent)
        passenger_last_name = passenger_last_name_from_session
        
    if flight_confirmation_number and not passenger_last_name:
        previous_slot_to_elicit = dialog.get_previous_slot_to_elicit(
            intent_request)
        if previous_slot_to_elicit == 'PassengerLastName': 
            prompt = prompts.get('PassengerLastNameSpellOut')
            return dialog.elicit_slot(
                'PassengerLastNameSpellOut', active_contexts, 
                session_attributes, intent, 
                [{'contentType': 'PlainText', 'content': prompt}])
        else:
            prompt = prompts.get('PassengerLastName')
            return dialog.elicit_slot(
                    'PassengerLastName', active_contexts, 
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
                
    if passenger_last_name_spell_out:
        passenger_last_name = passenger_last_name_spell_out
        dialog.set_slot(
            'PassengerLastName', passenger_last_name_spell_out, intent)
    
    if passenger_last_name and not customer_id:
        status, customer_id = airline_system.get_customer_id(
                                                flight_confirmation_number)
        print('customer_id : ',customer_id)
        if not status:
            dialog.set_slot('FlightConfirmationNumber', None, intent)
            dialog.set_session_attribute(
                intent_request, "flight_confirmation_number", None)
            prompt = prompts.get('InvalidFlightNumberPrompt')
            return dialog.elicit_slot(
                    'FlightConfirmationNumber', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
        else:
            dialog.set_session_attribute(
                intent_request, 'customer_id', customer_id)
                    
    if customer_id and not receipt_delivery_channel:
        status = airline_system.check_last_name(
            passenger_last_name, customer_id)
        if not status:
            prompt = prompts.get('InvalidLastNamePrompt')
            return dialog.elicit_slot(
                    'PassengerLastNameSpellOut', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
        else:
            prompt = prompts.get('ReceiptDeliveryChannel')
            return dialog.elicit_slot(
                    'ReceiptDeliveryChannel', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
    
    if receipt_delivery_channel:
        response = responses.get(
            'Response', receipt_delivery_channel=receipt_delivery_channel)
        return dialog.elicit_intent(
            active_contexts, session_attributes, intent,
            [{'contentType': 'PlainText', 'content': response}])
                    
    return dialog.delegate(active_contexts, session_attributes, intent)