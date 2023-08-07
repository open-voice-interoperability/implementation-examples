"""
 This code sample demonstrates an implementation of the Lex Code Hook Interface
 in order to serve a bot which manages banking account services. Bot, Intent, 
 and Slot models which are compatible with this sample can be found in the Lex 
 Console as part of the 'AccountServices' template.
"""
import json
import time
import os
import logging
import dialogstate_utils as dialog
import fallback
# import repeat
import show_flight_details
import book_a_flight
import get_flight_status
import reschedule_trip
import cancel_flight_reservation
import get_flight_reservation_receipt
import check_reservation_details

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
    
# --- Main handler & Dispatch ---

def dispatch(intent_request):
    """
    Route to the respective intent module code
    """
    
    intent = dialog.get_intent(intent_request)
    intent_name = intent['name']
    active_contexts = dialog.get_active_contexts(intent_request)
    session_attributes = dialog.get_session_attributes(intent_request)
    
    customer_id = dialog.get_session_attribute(intent_request, 'customer_id')
    
    if customer_id and customer_id[0] == '.':
        dialog.set_session_attribute(
            intent_request, 'customer_id', customer_id[1:])
        

    
    # Default dialog state is set to delegate
    next_state = dialog.delegate(active_contexts, session_attributes, intent)
    
    # Dispatch to in-built Lex intents
    if intent_name == 'FallbackIntent':
        next_state = fallback.handler(intent_request)
    # if intent_name == 'Repeat':
    #     next_state = repeat.handler(intent_request)
    
    # Dispatch to the respective intent's handler
    if intent_name == 'BookAFlight':
        next_state = book_a_flight.handler(intent_request)
    if intent_name == 'GetFlightStatus':
        next_state = get_flight_status.handler(intent_request)
    if intent_name == 'RescheduleTrip':
        next_state = reschedule_trip.handler(intent_request)
    if intent_name == 'CancelFlightReservation':
        next_state = cancel_flight_reservation.handler(intent_request)
    if intent_name == 'GetFlightReservationReceipt':
        next_state = get_flight_reservation_receipt.handler(intent_request)
    if intent_name == 'CheckReservationDetails':
        next_state = check_reservation_details.handler(intent_request)
    if intent_name == 'ShowFlightDetails':
        next_state = show_flight_details.handler(intent_request)
    return next_state


def lambda_handler(event, context):
    """
    Route the incoming request based on intent.
    The JSON body of the request is provided in the event slot.
    """
    # By default, treat the user request as coming from the America/New_York time zone.
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    logger.debug(event)

    return dispatch(event)
