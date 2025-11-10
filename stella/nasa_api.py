import requests
import re
from typing import Optional

# Parameters for the request
params = {
    "api_key": "wVnaajaqfHQIaOhSyc5SQWFecweOwKAe54OUSuZT",       # Replace with your own key from https://api.nasa.gov
    "hd": True                   # Optional: True to get HD image URL
}

# NASA APOD API endpoint
url = "https://api.nasa.gov/planetary/apod"


def _extract_url_from_text(text: str) -> Optional[str]:
    """Return the first https?:// URL found in text, or None."""
    if not text:
        return None
    # Remove common code-fence wrappers
    s = text.strip()
    # If the text contains a triple-backtick block, try to pull the inside
    fence_match = re.search(r"```(?:\w*\n)?(.*?)```", s, flags=re.DOTALL)
    if fence_match:
        s = fence_match.group(1).strip()

    # If the text begins with an HTTP method like 'GET ', remove it
    if s.upper().startswith("GET ") or s.upper().startswith("POST "):
        parts = s.split(None, 1)
        if len(parts) > 1:
            s = parts[1].strip()

    # Find first URL
    m = re.search(r"(https?://[^\s`'\"]+)", s)
    if m:
        return m.group(1).strip()

    # As a last resort, if the remaining string looks like a URL, return it
    if s.startswith("https://") or s.startswith("http://"):
        return s

    return None


def get_nasa(api_call: Optional[str] = None):
    """Fetch NASA data.

    - If api_call is None, call the default APOD endpoint with `params`.
    - If api_call is a string that includes a URL (for example, "GET https://..." or
      a code-fenced block returned by an LLM), extract the URL and call it.
    """
    if api_call is None:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # If caller passed a string that contains a URL or begins with 'GET ', extract the URL
    target = _extract_url_from_text(str(api_call))
    if target is None:
        # If we couldn't find a URL, try to call the string as-is (will raise helpful error)
        response = requests.get(str(api_call))
    else:
        response = requests.get(target)

    response.raise_for_status()
    return response.json()


def parse_nasa_data(nasa_data):
    explanation = nasa_data.get("explanation")
    url = nasa_data.get("url")
    return explanation, url


