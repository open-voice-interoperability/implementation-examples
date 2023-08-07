
import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system


def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('check_reservation_details')
    responses = Responses('check_reservation_details')
    
    flight_confirmation_number = dialog.get_slot(
                            'FlightConfirmationNumber', intent)
    passenger_last_name = dialog.get_slot('PassengerLastName', intent)
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
    
    if flight_confirmation_number and not customer_id:
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
                    'PassengerLastName', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
        else:
            reservation_details, valid_reservation \
                = airline_system.get_reservation_details(
                    customer_id, flight_confirmation_number, passenger_last_name)
                                    
            if valid_reservation:
                number_of_passenger = reservation_details.get('number_of_passenger')
                flight_number = reservation_details.get('flight_number')
                departure_airport = reservation_details.get('departure_airport')
                departure_date = reservation_details.get('departure_date')
                departure_time = reservation_details.get('departure_time')
                destination_airport = reservation_details.get('destination_airport')
                arriving_time = reservation_details.get('arriving_time')
                
                response = responses.get('Fulfilment',
                    flight_confirmation_number = flight_confirmation_number,
                    number_of_passenger = number_of_passenger,
                    flight_number = flight_number,
                    departure_airport = departure_airport,
                    departure_date = departure_date,
                    departure_time = departure_time,
                    destination_airport = destination_airport,
                    arriving_time = arriving_time
                    )
                
                return dialog.elicit_intent(active_contexts, 
                            session_attributes, intent, 
                            [{'contentType': 'SSML', 'content': response}])
            else: 
                response = responses.get('ReservationDetailsNotAvailable')
                return dialog.elicit_intent(active_contexts, 
                            session_attributes, intent, 
                            [{'contentType': 'SSML', 'content': response}])
            
    return dialog.delegate(active_contexts, session_attributes, intent)        