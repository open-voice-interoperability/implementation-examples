#!/usr/bin/env python3
"""
Utterance Handler - World Time Agent

This module handles time-related queries for major cities worldwide.

The process_utterance function receives:
- user_text: The text message from the user
- agent_name: Optional display name for the agent

And returns:
- response_text: The text response to send back

All OpenFloor event parsing and envelope construction is handled by template_agent.py.
"""

from datetime import datetime
import pytz
import re


# Major cities and their timezones
CITY_TIMEZONES = {
    # Americas
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "toronto": "America/Toronto",
    "mexico city": "America/Mexico_City",
    "vancouver": "America/Vancouver",
    "san francisco": "America/Los_Angeles",
    "boston": "America/New_York",
    "miami": "America/New_York",
    "denver": "America/Denver",
    "seattle": "America/Los_Angeles",
    
    # Europe
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "rome": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "vienna": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "stockholm": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "dublin": "Europe/Dublin",
    "moscow": "Europe/Moscow",
    "athens": "Europe/Athens",
    
    # Asia
    "tokyo": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore",
    "seoul": "Asia/Seoul",
    "bangkok": "Asia/Bangkok",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "dubai": "Asia/Dubai",
    "tel aviv": "Asia/Tel_Aviv",
    "jakarta": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    
    # Oceania
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    
    # Africa
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    
    # South America
    "sao paulo": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "rio": "America/Sao_Paulo",
    "lima": "America/Lima",
    "santiago": "America/Santiago",
}


def process_utterance(user_text: str, agent_name: str = "TimeAgent") -> str:
    """
    Process user input and generate a time-related response.
    
    Args:
        user_text: The user's message (already extracted from OpenFloor event)
        agent_name: Display name for the agent
        
    Returns:
        response_text: The response message with time information, or None if query is not time-related
    """
    user_text_lower = user_text.lower().strip()
    
    # Check if query is time-related at all
    time_keywords = ["time", "clock", "timezone", "hour", "minute", "what time", "when is it"]
    city_found = any(city in user_text_lower for city in CITY_TIMEZONES.keys())
    has_time_keyword = any(keyword in user_text_lower for keyword in time_keywords)
    has_help_keyword = any(word in user_text_lower for word in ["help", "what can you do", "capabilities"])
    has_list_keyword = any(phrase in user_text_lower for phrase in ["list cities", "which cities", "what cities", "available cities"])
    
    # If query is not time-related, return None to send empty response
    if not (city_found or has_time_keyword or has_help_keyword or has_list_keyword):
        return None
    
    # Check for help requests
    if has_help_keyword:
        return _get_help_message(agent_name)
    
    # Check for list of cities request
    if has_list_keyword:
        return _list_available_cities()
    
    # Try to extract city name from the query
    city = _extract_city_from_query(user_text_lower)
    
    if city:
        return _get_time_for_city(city)
    
    # If no specific city found, check for general time request
    if has_time_keyword:
        return "I can tell you the current time in major cities worldwide. Which city are you interested in? (Or ask 'list cities' to see available cities)"
    
    # If we got here with time-related keywords but nothing matched, return None
    return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _extract_city_from_query(user_text: str) -> str:
    """
    Extract city name from user query.
    
    Args:
        user_text: User's input (lowercase)
        
    Returns:
        City name if found, empty string otherwise
    """
    # Check each known city
    for city in CITY_TIMEZONES.keys():
        if city in user_text:
            return city
    
    return ""


def _get_time_for_city(city: str) -> str:
    """
    Get current time for a specific city.
    
    Args:
        city: City name (lowercase)
        
    Returns:
        Formatted time information
    """
    timezone_str = CITY_TIMEZONES.get(city)
    
    if not timezone_str:
        return f"Sorry, I don't have time information for '{city}'. Try 'list cities' to see available cities."
    
    try:
        tz = pytz.timezone(timezone_str)
        current_time = datetime.now(tz)
        
        # Format: "Monday, January 12, 2026 at 3:45 PM EST"
        day_name = current_time.strftime("%A")
        month_day = current_time.strftime("%B %d, %Y")
        time_12h = current_time.strftime("%I:%M %p")
        tz_abbrev = current_time.strftime("%Z")
        
        city_display = city.title()
        
        return f"The current time in {city_display} is {day_name}, {month_day} at {time_12h} {tz_abbrev}"
        
    except Exception as e:
        return f"Sorry, I encountered an error getting the time for {city}: {str(e)}"


def _list_available_cities() -> str:
    """
    List all available cities organized by region.
    
    Returns:
        Formatted list of cities
    """
    regions = {
        "Americas": ["New York", "Los Angeles", "Chicago", "Toronto", "Mexico City", "Vancouver", "San Francisco", "Miami"],
        "Europe": ["London", "Paris", "Berlin", "Madrid", "Rome", "Amsterdam", "Moscow", "Athens"],
        "Asia": ["Tokyo", "Beijing", "Shanghai", "Hong Kong", "Singapore", "Seoul", "Dubai", "Mumbai"],
        "Oceania": ["Sydney", "Melbourne", "Auckland", "Brisbane"],
        "Africa": ["Cairo", "Johannesburg", "Lagos", "Nairobi"],
        "South America": ["São Paulo", "Buenos Aires", "Rio", "Lima", "Santiago"]
    }
    
    response = "I can provide time information for these major cities:\n\n"
    
    for region, cities in regions.items():
        response += f"{region}: {', '.join(cities)}\n"
    
    response += "\nJust ask 'what time is it in [city]?'"
    
    return response


def _get_help_message(agent_name: str) -> str:
    """
    Generate help message explaining agent capabilities.
    
    Args:
        agent_name: Display name of the agent
        
    Returns:
        Help message text
    """
    return f"""Hi, I'm {agent_name}! I can tell you the current time in major cities around the world.

Here's how to use me:
• "What time is it in Tokyo?"
• "Current time in London"
• "Time in New York"
• "List cities" - see all available cities

I support major cities in Americas, Europe, Asia, Oceania, Africa, and South America.
Just ask about any major city!"""

