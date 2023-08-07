import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system
from datetime import date, timedelta, datetime
import json
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
    responses = Responses('book_a_flight')
    response = responses.get(
            'OnewayFlightDetails',
            departure_flight_number=onward.get('flight_number'),
            price=str(price), 
            departure_start_time=onward.get('time'))
    
    if trip_type=='Round Trip':
        response = responses.get(
            'RoundTripFlightDetails', 
            departure_flight_number=onward.get('flight_number'),
            departure_start_time=onward.get('time'),
            price=str(price),
            return_flight_number=_return.get('flight_number'),
            return_start_time=_return.get('estimated_start_time'),
            return_arrival_time=_return.get('estimated_arrival_time'))
    
    return response
    
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
    prompts = Prompts('book_a_flight')
    responses = Responses('book_a_flight')
    
    trip_type = dialog.get_slot('TripType', intent)
    departure_city = dialog.get_slot('DepartureCity', intent)
    destination_city = dialog.get_slot('DestinationCity', intent)
    departure_date = dialog.get_slot(
        'DepartureDate', intent, preference='interpretedValue')
    return_date = dialog.get_slot(
        'ReturnDate', intent, preference='interpretedValue')
    number_of_travellers = dialog.get_slot(
        'NumberOfTravellers', intent, preference='interpretedValue')
    number_of_travellers_in_words = dialog.get_slot(
        'NumberOfTravellersInWords', intent, preference='interpretedValue')
    preferred_departure_time = dialog.get_slot(
        'PreferredDepartureTime', intent)
    preferred_return_departure_time = dialog.get_slot(
        'PreferredReturnDepartureTime', intent)
    card_number = dialog.get_slot('CardNumber', intent)
    card_number_confirmation = dialog.get_slot(
        'CardNumberConfirmation', intent)
    frequent_flyer_number = dialog.get_slot('FrequentFlyerNumber', intent)
    card_last4_digits = dialog.get_slot('CardLast4Digits', intent)
    card_last4_digits_confirmation = dialog.get_slot(
        'CardLast4DigitsConfirmation', intent)
    flight_selected = dialog.get_slot('FlightSelected', intent)
    card_expiry_date = dialog.get_slot('CardExpiryDate', intent)
    security_code = dialog.get_slot('SecurityCode', intent)
    
    if frequent_flyer_number:
        if not airline_system.is_valid_frequent_flyer(frequent_flyer_number):
            prompt = prompts.get('InValidFFNumber')
            return dialog.elicit_slot(
                'FrequentFlyerNumber', active_contexts,
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
    
    if card_last4_digits:
        if not airline_system.is_valid_card(frequent_flyer_number, card_last4_digits):
            prompt = prompts.get('InValidCard')
            return dialog.elicit_slot(
                'CardLast4Digits', active_contexts,
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
        else:
            dialog.set_session_attribute(
                intent_request, 'CardLast4Digits', card_last4_digits)
        
    if departure_date and not return_date:
        if is_valid_date(departure_date, constraint='future_date'):
            if trip_type == 'Round Trip':
                prompt = prompts.get('ReturnDatePrompt')
                return dialog.elicit_slot(
                            'ReturnDate', active_contexts,
                            session_attributes, intent,
                            [{'contentType': 'PlainText', 'content': prompt}])
        else:
            prompt = prompts.get('PastDepartureDate')
            return dialog.elicit_slot(
                'DepartureDate', active_contexts,
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
    
    if return_date:
        if return_date < departure_date:
            prompt = prompts.get('PastReturnDate')
            return dialog.elicit_slot(
                'ReturnDate', active_contexts,
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
    
    if departure_date and not number_of_travellers_in_words:
        previous_slot_to_elicit = dialog.get_previous_slot_to_elicit(
            intent_request)
        if previous_slot_to_elicit == 'NumberOfTravellersInWords':
            prompt = prompts.get('NumberOfTravellers1')
            dialog.set_slot('NumberOfTravellersInWords','not required' , intent)
            return dialog.elicit_slot(
                'NumberOfTravellers', active_contexts, 
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
        else:
            prompt = prompts.get('NumberOfTravellersInWords')
            return dialog.elicit_slot(
                    'NumberOfTravellersInWords', active_contexts, 
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}])
            
    if number_of_travellers or number_of_travellers_in_words \
        and not preferred_departure_time:
        if not number_of_travellers:
            number_of_travellers = number_of_travellers_in_words
            prompt = prompts.get(
                'PreferredDepartureTime')
            return dialog.elicit_slot(
                'PreferredDepartureTime', active_contexts, 
                session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
                
    if preferred_departure_time and not preferred_return_departure_time:
        if trip_type == 'Round Trip':
            prompt = prompts.get('PreferredReturnDepartureTimePrompt')
            return dialog.elicit_slot(
                        'PreferredReturnDepartureTime', active_contexts,
                        session_attributes, intent,
                        [{'contentType': 'PlainText', 'content': prompt}]) 
                        
    got_one_way_trip_data = trip_type == 'One way' \
                            and preferred_departure_time \
                            and departure_city \
                            and departure_date \
                            and destination_city \
                            
    got_round_trip_data = trip_type == 'Round Trip' \
                            and preferred_departure_time \
                            and departure_city \
                            and departure_date \
                            and destination_city \
                            and preferred_return_departure_time \
                            and return_date
    
    if not flight_selected and (got_round_trip_data or got_one_way_trip_data):
        if intent['confirmationState'] == 'None':    
            flight_options = airline_system.get_available_flights(
                departure_city, destination_city, trip_type,
                departure_date, return_date)
            dialog.set_session_attribute(
                intent_request, 'flight_options', json.dumps(flight_options))
            if len(flight_options) > 0:
                # found flights
                best_option = flight_options[0]
                response = compose_flight_options_response(
                    best_option, trip_type)
                flight_options = json.loads(dialog.get_session_attribute(
                    intent_request, 'flight_options'))
                flight_options.pop(0)
                dialog.set_session_attribute(
                    intent_request, 'flight_options', 
                    json.dumps(flight_options))
                show_next_flight_context = list(filter(lambda x: x.get('name') == \
                                        'ShowNextFlight', active_contexts))
                if len(show_next_flight_context) == 0:
                    dialog.set_active_contexts(
                        intent_request, 'ShowNextFlight', 
                        {'trip_type': trip_type}, 120, 10)
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
            response = responses.get('BookingDenied')
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
    
    return dialog.delegate(active_contexts, session_attributes, intent)                    
    
   