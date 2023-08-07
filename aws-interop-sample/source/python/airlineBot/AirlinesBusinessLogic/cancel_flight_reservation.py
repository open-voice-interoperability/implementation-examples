
import dialogstate_utils as dialog
from prompts_responses import Prompts, Responses
import airline_system
from datetime import date, timedelta, datetime

def resolve_underspecified_date(flight_booking_date):
    flight_booking_date = datetime.strptime(
        flight_booking_date, '%Y-%m-%d').date()
    today = date.today()
    if flight_booking_date <= today:
        return flight_booking_date
    else:
        number_of_days_in_future = (flight_booking_date - today).days
        if number_of_days_in_future > 7:
            return flight_booking_date.replace(year=flight_booking_date.year-1)
        else:
            return flight_booking_date-timedelta(days=7)
            
def handler(intent_request):
    intent = dialog.get_intent(intent_request)
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    prompts = Prompts('cancel_flight_reservation')
    responses = Responses('cancel_flight_reservation')
    
    flight_confirmation_number = dialog.get_slot(
                                        'FlightConfirmationNumber', intent)
    passenger_last_name = dialog.get_slot('PassengerLastName', intent)
    passenger_last_name_spell_out = dialog.get_slot(
        'PassengerLastNameSpellOut', intent)
    dob = dialog.get_slot('DOB', intent)
    flight_booking_date = dialog.get_slot(
        'FlightBookingDate', intent, preference = 'interpretedValue')
    
    customer_id = dialog.get_session_attribute(intent_request, 'customer_id')
    
    if passenger_last_name_spell_out:
        passenger_last_name = passenger_last_name_spell_out
        dialog.set_slot(
            'PassengerLastName', passenger_last_name_spell_out, intent)
    
    if flight_confirmation_number and not customer_id:
        status, customer_id = airline_system.get_customer_id(
                                                flight_confirmation_number)
        if not status:
            dialog.set_slot('FlightConfirmationNumber', None, intent)
            prompt = prompts.get('InvalidFlightNumberPrompt')
            return dialog.elicit_slot(
                    'FlightConfirmationNumber', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
        else:
            dialog.set_session_attribute(
                intent_request, 'customer_id', customer_id)
                
    if passenger_last_name and not flight_booking_date:
        status = airline_system.check_last_name(
                                            passenger_last_name, customer_id)
        if not status:
            prompt = prompts.get('InvalidLastNamePrompt')
            return dialog.elicit_slot(
                    'PassengerLastNameSpellOut', active_contexts,
                    session_attributes, intent,
                    [{'contentType': 'PlainText', 'content': prompt}]
                    )
    
    # Confirmation & Fulfillment
    if flight_booking_date:
        flight_booking_date = resolve_underspecified_date(flight_booking_date)
        if intent['confirmationState'] == 'Confirmed':
            prompt = prompts.get(
                'FulfilmentResponse')
            return dialog.elicit_intent(
                active_contexts, session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
        elif intent['confirmationState'] == 'Denied':
            prompt = prompts.get('DeniedCancellation')
            return dialog.elicit_intent(
                active_contexts, session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
        else: 
            prompt = prompts.get(
                'Confirmation', flight_booking_date=flight_booking_date)
            return dialog.confirm_intent(
                active_contexts, session_attributes, intent,
                [{'contentType': 'PlainText', 'content': prompt}])
    
                    
    return dialog.delegate(active_contexts, session_attributes, intent)      