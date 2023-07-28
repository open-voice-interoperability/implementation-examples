
import random
from random import randint

import boto3
import time
import os
from boto3.dynamodb.conditions import Key, Attr

dynamodb = boto3.resource('dynamodb')
table_name = os.environ['dynamodb_tablename']
travel_hospitalitydb = dynamodb.Table(table_name)

def get_customer_id(flight_confirmation_number):
    try:
        flight_confirmation_number = flight_confirmation_number \
            and flight_confirmation_number.lower() 
        customers = travel_hospitalitydb.scan(
            FilterExpression=Attr('record_type').eq('flight_booking') and
            Attr("flight_confirmation_number").eq(flight_confirmation_number))
        if len(customers.get('Items')) <= 0:
            return None, 'Null'
        customer_id = customers.get('Items')[0]['customer_id']
        return True, customer_id
    except:
        return None, 'Null'


def check_passenger_last_name(passenger_last_name, customer_id):
    try:
        flight = travel_hospitalitydb.query(
            KeyConditionExpression=Key('customer_id').eq(customer_id),
            FilterExpression=Attr('record_type').eq('flight_details') &
            Attr('last_name').eq(passenger_last_name)
        )
        if len(flight.get('Items')) <= 0:
            return None
        return True
    except:
        return None

def check_last_name(passenger_last_name, customer_id):
    try:
        passenger_last_name = passenger_last_name and passenger_last_name.lower()
        flight = travel_hospitalitydb.query(
            KeyConditionExpression=Key('customer_id').eq(customer_id),
            FilterExpression=Attr('record_type').eq('flight_booking') &
            Attr('last_name').eq(passenger_last_name)
        )
        if len(flight.get('Items')) <= 0:
            return None
        return True
    except:
        return None
        
def get_reservation_details(
        customer_id, flight_confirmation_number, passenger_last_name):
    try:
        flight = travel_hospitalitydb.query(
            KeyConditionExpression=Key('customer_id').eq(customer_id),
            FilterExpression=Attr('record_type').eq('flight_booking') &
            Attr('last_name').eq(passenger_last_name) & 
            Attr('flight_confirmation_number').eq(flight_confirmation_number)
        )
        if len(flight.get('Items')) <= 0:
            return None, None
        passenger_details = flight.get('Items')[0]
        number_of_passenger = passenger_details.get('number_of_travellers')
        flight_number = passenger_details.get('flight_number')
        departure_airport = passenger_details.get('departure_airport')
        departure_date = passenger_details.get('departure_date')
        departure_time = passenger_details.get('departure_time')
        destination_airport = passenger_details.get('destination_airport')
        arriving_time = passenger_details.get('arriving_time')
        return {
            'number_of_passenger': number_of_passenger,
            'flight_number': flight_number,
            'departure_airport': departure_airport,
            'departure_date': departure_date,
            'departure_time': departure_time,
            'destination_airport': destination_airport, 
            'arriving_time': arriving_time
        }, True
    except:
        return None, None
        
def get_flight_details_by_number(flight_number):
    try:
        flight = travel_hospitalitydb.scan(
            FilterExpression=Attr('record_type').eq('flight_details') and
            Attr('flight_number').eq(flight_number)  
        )
        if len(flight.get('Items')) <= 0:
            return False, None
        flight_details = flight.get('Items')[0]
        return True, flight_details
    except:
        return False, None
        
def get_flight_details(departure_city, destination_city, departure_time):
    try:
        
        flight = travel_hospitalitydb.scan(
            FilterExpression=Attr('record_type').eq('flight_details') and
            Attr('departure_city').eq(departure_city) and
            Attr('destination_city').eq(destination_city) or
            Attr('departure_time').eq(departure_time)
        )
        if len(flight.get('Items')) <= 0:
            return None,"Null","Null","Null","Null",\
                "Null","Null","Null", "Null"
        flight_details = flight.get('Items')[0]
        departure_airport = flight_details.get('departure_airport')
        departure_date = flight_details.get('departure_date')
        departure_time = flight_details.get('departure_time')
        destination_airport = flight_details.get('destination_airport')
        arriving_date = flight_details.get('arriving_date')
        arriving_time = flight_details.get('arriving_time')
        departure_city = flight_details.get('departure_city')
        flight_number = flight_details.get('flight_number')
        return True, flight_number, departure_airport,departure_date,\
            departure_time,destination_airport, arriving_date,\
            arriving_time, departure_city
    except:
        return None
    
def get_available_flights(
        departure_city, destination_city, trip_type, 
        departure_date, return_date):
    delta = 0
    if trip_type == 'Round Trip':
        delta = 150
    return [
        {
            "onward": {
                "flight_number": "A123",
                "time": "5:30am",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "return": {
                "flight_number": "Z123",
                "estimated_start_time": "9:30pm",
                "estimated_arrival_time":"11:30pm",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "price": 100 + delta,
        },
        {
            "onward": {
                "flight_number": "B123",
                "time": "6:30am",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "return": {
                "flight_number": "Y123",
                "estimated_start_time": "8:30pm",
                "estimated_arrival_time":"10:30pm",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "price": 150 + delta,
        },
        {
            "onward": {
                "flight_number": "C123",
                "time": "6:45am",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "return": {
                "flight_number": "X123",
                "estimated_start_time": "9:45pm",
                "estimated_arrival_time":"11:45pm",
                "date": "01/01/2022",
                "departure_city":departure_city,
                "destination_city":destination_city,
                "departure_date":departure_date,
                "return_date":return_date
            },
            "price": 200 + delta,
        }
    ]
    
frequent_flyer_details=[
    {
    'frequent_flyer_number':'34567',
    'card_last4_digits':'3456'
    },
    {
    'frequent_flyer_number':'45678',
    'card_last4_digits':'1234'
    },
    {
    'frequent_flyer_number':'56789',
    'card_last4_digits':'5678'
    },
     {
    'frequent_flyer_number':'67891',
    'card_last4_digits':'4567'
    }
]

def is_valid_card(frequent_flyer_number, card_last4_digits):
    users = list(filter(lambda user_details: \
    user_details['frequent_flyer_number'] == frequent_flyer_number and \
    user_details['card_last4_digits'] == card_last4_digits, \
    frequent_flyer_details))
    if len(users)>0:
        return True
    return False
    
def is_valid_frequent_flyer(frequent_flyer_number):
    users = list(filter(lambda user_details: \
    user_details['frequent_flyer_number'] == \
    frequent_flyer_number, frequent_flyer_details))
    if len(users)>0:
        return True
    return False
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    