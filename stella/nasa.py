import requests

# NASA API Key
nasa_api_key = wVnaajaqfHQIaOhSyc5SQWFecweOwKAe54OUSuZT

# Construct the GET request URL
nasa_url = f"https://api.nasa.gov/planetary/apod?api_key={nasa_api_key}"

# Make the API call
response = requests.get(nasa_url)

# Check the response
if response.status_code == 200:
    print("Response received successfully:")
    print(response.json())  # Prints the JSON response from NASA
else:
    print(f"Error: {response.status_code}")
    print(response.text.explanation)
    print(response.text.url)
