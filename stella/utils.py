from datetime import datetime
import dateparser
import re
from dateutil import parser, relativedelta

def extract_and_convert_datetime(text):
    found_date = parse_date(text)
    print(found_date)
    formatted_date = format_date(found_date)
    return formatted_date

# Function to parse input date from text
def parse_date(input_text):
    date_match = re.search(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b', input_text, re.IGNORECASE)
    if date_match:
        parsed_datetime = dateparser.parse(date_match.group(), settings={'PREFER_DATES_FROM': 'past', 'TIMEZONE': 'UTC'})
    else:
        parsed_datetime = dateparser.parse(input_text, settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.now(), 'TIMEZONE': 'UTC'})
    
    if parsed_datetime is None:
        try:
            parsed_datetime = parser.parse(input_text, fuzzy=True)
        except ValueError:
            return None
    
    if parsed_datetime and parsed_datetime > datetime.now():
        parsed_datetime = parsed_datetime - relativedelta.relativedelta(weeks=1)
    
    return parsed_datetime


def format_date(parsed_datetime):
    if parsed_datetime:
        return parsed_datetime.strftime('%Y-%m-%d')
    else:
        return None


# Test cases with both absolute and relative dates
examples = [
    "The meeting is on January 1, 2024.",
    "Let's catch up next Friday.",
    "It happened yesterday",
    "We met on March 5th, 2023."
    "We met last Monday.",              # Date for the previous Monday
    "See you this Wednesday."          # Date for the upcoming Wednesday

]

# Print the results
for text in examples:
    print(f"Input: {text}")
    print(f"Output: {extract_and_convert_datetime(text)}")
    print("---")
