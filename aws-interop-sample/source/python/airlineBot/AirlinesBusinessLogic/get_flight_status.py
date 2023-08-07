
import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system


def get_status_by_flight_number(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('get_flight_status')
    responses = Responses('get_flight_status')
    flight_number = dialog.get_slot('FlightNumber', intent)
    departure_time = dialog.get_slot('DepartureTime', intent)
    destination_city = dialog.get_slot('DestinationCity', intent)
    
    if not flight_number:
        prompt = prompts.get('FlightNumberPrompt')
        return dialog.elicit_slot(
                'FlightNumber', active_contexts,
                session_attributes, intent,
                [{'contentType': 'SSML', 'content': prompt}]
                )
    if flight_number and not intent['confirmationState'] == 'Fulfilled':
        status, flight_details = \
                airline_system.get_flight_details_by_number(flight_number)
        if status:
            response = responses.get('FulfilmentPrompt',
                        flight_number = flight_details.get('flight_number'),
                        departure_airport = flight_details.get('departure_airport'),
                        departure_date = flight_details.get('departure_date'),
                        departure_time = flight_details.get('departure_time'),
                        destination_airport = flight_details.get('destination_airport'),
                        arriving_date = flight_details.get('arriving_date'),
                        arriving_time = flight_details.get('arriving_time'),
                        departure_city = flight_details.get('departure_city'),
                        destination_city=flight_details.get('destination_city'))
            return dialog.elicit_intent(active_contexts, 
                        session_attributes, intent, 
                        [{'contentType': 'SSML', 'content': response}],
                    )
        else:
            response = responses.get('NoMatch')
            return dialog.elicit_intent(active_contexts, 
                        session_attributes, intent, 
                        [{'contentType': 'SSML', 'content': response}],
                    )
    return dialog.delegate(active_contexts, session_attributes, intent)

def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('get_flight_status')
    responses = Responses('get_flight_status')
    
    flight_number_confirmation = dialog.get_slot('FlightNumberConfirmation', intent)
    flight_number = dialog.get_slot('FlightNumber', intent)
    departure_city = dialog.get_slot('DepartureCity', intent)
    departure_time = dialog.get_slot('DepartureTime', intent)
    destination_city = dialog.get_slot('DestinationCity', intent)
    
    if flight_number_confirmation and not departure_city:
        if flight_number_confirmation == 'Yes':
            return get_status_by_flight_number(intent_request)
            
        elif flight_number_confirmation == 'No':
            prompt = prompts.get('DepartureCityPrompt')
            return dialog.elicit_slot(
                    'DepartureCity', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
        else: 
            prompt = prompts.get('ReElicitFlightNumber')
            return dialog.elicit_slot(
                    'FlightNumberConfirmation', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
    if flight_number_confirmation == 'No' and departure_time:
        
        status, flight_number,departure_airport,departure_date,\
        departure_time1,destination_airport, arriving_date, \
        arriving_time,departure_city = airline_system.get_flight_details(
                            departure_city, destination_city, departure_time)
        if status:
            if departure_time == "05:00":
                response = responses.get('FulfilmentPrompt1',
                    departure_time = departure_time,
                    flight_number = flight_number,
                    departure_airport = departure_airport,
                    departure_time1 = departure_time1,
                    destination_airport = destination_airport,
                    destination_city=destination_city,
                    departure_city = departure_city)
                return dialog.elicit_intent(active_contexts, 
                            session_attributes, intent, 
                            [{'contentType': 'SSML', 'content': response}],
                        )
            elif departure_time == "23:00":
                response = responses.get('FulfilmentPrompt2',
                    departure_time = departure_time,
                    flight_number = flight_number,
                    departure_airport = departure_airport,
                    departure_time1 = departure_time1,
                    destination_airport = destination_airport,
                    departure_city = departure_city,
                    destination_city=destination_city)
                return dialog.elicit_intent(active_contexts, 
                            session_attributes, intent, 
                            [{'contentType': 'SSML', 'content': response}],
                        )
            else:
                response = responses.get('NoMatch')
                return dialog.elicit_intent(active_contexts, 
                            session_attributes, intent, 
                            [{'contentType': 'SSML', 'content': response}],
                        )
        else:
            response = responses.get('NoMatch')
            return dialog.elicit_intent(active_contexts, 
                        session_attributes, intent, 
                        [{'contentType': 'SSML', 'content': response}],
                    )
    return dialog.delegate(active_contexts, session_attributes, intent)                