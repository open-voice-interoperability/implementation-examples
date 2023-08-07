import dialogstate_utils as dialog
import json
from prompts_responses import Prompts, Responses
import random as random

def compose_fulfilment_response(option, trip_type):
    onward = option.get('onward')
    _return = option.get('return')
    price = option.get('price')
    responses = Responses('book_a_flight')
    confirmation_number = random.randint(9999, 100000)
    response = responses.get(
            'OneWayFulfilment',
            departure_flight_number=onward.get('flight_number'),
            price=str(price), 
            departure_start_time=onward.get('time'),
            departure_city=onward.get('departure_city'),
            destination_city=onward.get('destination_city'),
            departure_date=onward.get('departure_date'),
            return_date=onward.get('return_date'),
            confirmation_number=confirmation_number)
    
    if trip_type=='Round Trip':
        response = responses.get(
            'RoundTripFulfilment', 
            departure_flight_number=onward.get('flight_number'),
            departure_start_time=onward.get('time'),
            price=str(price),
            return_flight_number=_return.get('flight_number'),
            return_start_time=_return.get('estimated_start_time'),
            return_arrival_time=_return.get('estimated_arrival_time'),
            departure_city=onward.get('departure_city'),
            destination_city=onward.get('destination_city'),
            departure_date=onward.get('departure_date'),
            return_date=onward.get('return_date'),
            confirmation_number=confirmation_number)
    
    return response

def compose_flight_options_response(option, trip_type):
    onward = option.get('onward')
    _return = option.get('return')
    price = option.get('price')
    responses = Responses('show_flight_details')
    response = responses.get(
            'OnewayFlightDetails',
            departure_flight_number=onward.get('flight_number'),
            price=str(price), 
            departure_start_time=onward.get('time'),
            departure_city=onward.get('departure_city'),
            destination_city=onward.get('destination_city'),
            departure_date=onward.get('departure_date'),
            return_date=onward.get('return_date'))
    
    if trip_type=='Round Trip':
        response = responses.get(
            'RoundTripFlightDetails', 
            departure_flight_number=onward.get('flight_number'),
            departure_start_time=onward.get('time'),
            price=str(price),
            return_flight_number=_return.get('flight_number'),
            return_start_time=_return.get('estimated_start_time'),
            return_arrival_time=_return.get('estimated_arrival_time'),
            departure_city=onward.get('departure_city'),
            destination_city=onward.get('destination_city'),
            departure_date=onward.get('departure_date'),
            return_date=onward.get('return_date'))
    
    return response

def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('show_flight_details')
    responses = Responses('show_flight_details')
    flight_options = json.loads(dialog.get_session_attribute(
        intent_request, 'flight_options'))
    card_number = dialog.get_slot('CardNumber', intent)
    card_number_confirmation = dialog.get_slot(
        'CardNumberConfirmation', intent)
    # card_last4_digits = dialog.get_slot('CardLast4Digits', intent)
    card_last4_digits_confirmation = dialog.get_slot(
        'CardLast4DigitsConfirmation', intent)
    card_expiry_date = dialog.get_slot('CardExpiryDate', intent)
    security_code = dialog.get_slot('SecurityCode', intent)
    flight_selected = dialog.get_slot('FlightSelected', intent)
    
    card_last4_digits = dialog.get_session_attribute(intent_request, 'CardLast4Digits')
    
    trip_type = dialog.get_context_attribute(
                active_contexts, 'ShowNextFlight', 'trip_type')    
    # dialog.set_slot('CardLast4Digits', card_last4_digits, intent)
    
    if not flight_selected:
        if intent['confirmationState'] == 'None':
            if len(flight_options) > 0:
                # found flights
                trip_type = dialog.get_context_attribute(
                    active_contexts, 'ShowNextFlight', 'trip_type')
                best_option = flight_options[0]
                response = compose_flight_options_response(best_option, trip_type)
                
                '''
                 extend the context by another 5 turns if exired
                '''
                show_next_flight_context = list(filter(lambda x: x.get('name') == \
                                            'ShowNextFlight', active_contexts))
                if len(show_next_flight_context) == 0:
                    dialog.set_active_contexts(
                            intent_request, 'ShowNextFlight', {}, 120, 10)
                flight_options.pop(0)
                dialog.set_session_attribute(
                    intent_request, 'flight_options', json.dumps(flight_options))
                return dialog.confirm_intent(
                    active_contexts, session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': response}])
            else:
                # no flights 
                response = responses.get('NoFlights')
                return dialog.elicit_intent(
                    active_contexts, session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': response}])
                    
        elif intent['confirmationState'] == 'Confirmed':
            dialog.set_slot('FlightSelected', 'Confirmed', intent)
            flight_selected = 'Confirmed'
                
        elif intent['confirmationState'] == 'Denied':
            if len(flight_options) > 0:
                response = responses.get('BookingDenied')
                return dialog.elicit_intent(
                    active_contexts, session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': response}])
            else:
                response = responses.get('NoFlights')
                return dialog.elicit_intent(
                    active_contexts, session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': response}])
    
    if flight_selected and not card_last4_digits_confirmation:
        previous_slot_to_elicit = dialog.get_previous_slot_to_elicit(
                                                                    intent_request)
        if previous_slot_to_elicit == 'CardLast4DigitsConfirmation':
            if intent['confirmationState'] == 'Confirmed':
                dialog.set_slot('CardLast4DigitsConfirmation', 'Confirmed',
                                    intent)
                card_last4_digits_confirmation = 'Confirmed'
                flight_options = json.loads(dialog.get_session_attribute(
                    intent_request, 'flight_options'))
                response = compose_fulfilment_response(flight_options[0], trip_type)
                return dialog.elicit_intent(
                    active_contexts, session_attributes, intent,
                    [{'contentType': 'SSML', 'content': response}])
            elif intent['confirmationState'] == 'Denied':
                dialog.set_slot('CardLast4DigitsConfirmation', 'Denied', intent)
                card_last4_digits_confirmation = 'Denied'
                prompt = prompts.get('CardNumber')
                return dialog.elicit_slot('CardNumber',
                            active_contexts,
                            session_attributes,
                            intent,
                            [{'contentType': 'PlainText', 'content': prompt}]
                            )
            else:
                prompt = prompts.get('CardLast4DigitsConfirmation1', card_last4_digits=card_last4_digits)
                return dialog.confirm_intent(active_contexts, 
                        session_attributes,
                        intent, 
                        [{'contentType': 'SSML', 'content': prompt}],
                        previous_dialog_action_type='elicit_slot',
                        previous_slot_to_elicit='CardLast4DigitsConfirmation')
        else:
            prompt = prompts.get(
                'CardLast4DigitsConfirmation', card_last4_digits = card_last4_digits)
            return dialog.confirm_intent(active_contexts, 
                        session_attributes,
                        intent, 
                        [{'contentType': 'SSML', 'content': prompt}],
                        previous_dialog_action_type='elicit_slot',
                        previous_slot_to_elicit='CardLast4DigitsConfirmation')        
    
            
    if card_number and not card_number_confirmation:
        previous_slot_to_elicit = dialog.get_previous_slot_to_elicit(
                                                                intent_request)
        if previous_slot_to_elicit == 'CardNumberConfirmation':
            if intent['confirmationState'] == 'Confirmed':
                dialog.set_slot('CardNumberConfirmation', 'Confirmed',
                                    intent)
                card_number_confirmation = 'Confirmed'
                prompt = prompts.get('CardExpiryDate')
                return dialog.elicit_slot(
                    'CardExpiryDate', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
            elif intent['confirmationState'] == 'Denied':
                dialog.set_slot('CardNumberConfirmation', 'Denied', intent)
                card_number_confirmation = 'Denied'
                prompt = prompts.get('CardNumberReElicitPrompt')
                return dialog.elicit_slot(
                    'CardNumber', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
            else:
                prompt = prompts.get(
                    'CardNumberConfirmation1', card_number = card_number)
                return dialog.confirm_intent(
                    active_contexts, session_attributes, intent, 
                    [{'contentType': 'SSML', 'content': prompt}],
                    previous_dialog_action_type='elicit_slot',
                    previous_slot_to_elicit='CardNumberConfirmation')                               
        else:
            prompt = prompts.get(
                'CardNumberConfirmation', card_number = card_number)
            return dialog.confirm_intent(
                active_contexts, session_attributes, intent, 
                [{'contentType': 'SSML', 'content': prompt}],
                previous_dialog_action_type='elicit_slot',
                previous_slot_to_elicit='CardNumberConfirmation')
    
    if card_expiry_date and not security_code:
        prompt = prompts.get('SecurityCode')
        return dialog.elicit_slot(
            'SecurityCode', active_contexts,
            session_attributes, intent,
            [{'contentType': 'PlainText', 'content': prompt}])
            
    if security_code:
        flight_options = json.loads(dialog.get_session_attribute(
                    intent_request, 'flight_options'))
        response = compose_fulfilment_response(flight_options[0], trip_type)
        return dialog.elicit_intent(
            active_contexts, session_attributes, intent,
            [{'contentType': 'SSML', 'content': response}])
    
    # by default delegate to lex
    return dialog.delegate(active_contexts, session_attributes, intent)
        