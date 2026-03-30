# complete_mcp_stock_server.py

import asyncio
import json
import os
import logging
from pathlib import Path
from datetime import datetime
import requests
import websockets
from dotenv import load_dotenv
from utterance_handler import parse_query, parse_time_range, extract_time_text


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# ---------------------------
# 1. Finnhub API token
# ---------------------------
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

# ---------------------------
# 6. Finnhub API routing
# ---------------------------
def query_finnhub(intent, stock, time_text=None):
    if not FINNHUB_API_KEY:
        return {"error": "FINNHUB_API_KEY is not set. Add it to financial/.env."}

    base_url = "https://finnhub.io/api/v1"
    url = None

    if time_text:
        from_ts, to_ts = parse_time_range(time_text)
    else:
        from_ts, to_ts = 1679635200, 1701177600  # fallback 1 year

    if intent == "PRICE_QUERY":
        url = f"{base_url}/quote?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "PROFILE_QUERY":
        url = f"{base_url}/stock/profile2?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "FINANCIAL_QUERY":
        url = f"{base_url}/stock/financials-reported?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "NEWS_QUERY":
        url = f"{base_url}/company-news?symbol={stock}&from={datetime.utcfromtimestamp(from_ts).strftime('%Y-%m-%d')}&to={datetime.utcfromtimestamp(to_ts).strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
    elif intent == "EARNINGS_QUERY":
        url = f"{base_url}/stock/earnings?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "DIVIDEND_QUERY":
        url = f"{base_url}/stock/dividend?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "RECOMMENDATIONS_QUERY":
        url = f"{base_url}/stock/recommendation?symbol={stock}&token={FINNHUB_API_KEY}"
    elif intent == "HISTORY_QUERY":
        url = f"{base_url}/stock/candle?symbol={stock}&resolution=D&from={from_ts}&to={to_ts}&token={FINNHUB_API_KEY}"

    if url:
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            return response.json()

        details = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                details = payload.get("error") or payload.get("message") or str(payload)
            else:
                details = str(payload)
        except Exception:
            details = (response.text or "").strip()

        endpoint = url.split("?")[0]

        if response.status_code in (401, 403):
            detail_suffix = f" Details: {details}" if details else ""
            return {
                "error": (
                    f"Finnhub access denied ({response.status_code}) for endpoint {endpoint}. "
                    f"Check FINNHUB_API_KEY and plan permissions.{detail_suffix}"
                )
            }

        detail_suffix = f" Details: {details}" if details else ""
        return {"error": f"Finnhub API error: {response.status_code} ({endpoint}).{detail_suffix}"}
    return {"error": "No URL for intent"}

# ---------------------------
# 7. MCP WebSocket server
# ---------------------------
async def handler(websocket):
    async for message in websocket:
        try:
            data = json.loads(message)
            user_text = data.get("text", "")

            intent = data.get("intent")
            stock = data.get("stock")
            time_text = data.get("time_text")

            if not time_text and user_text:
                time_text = extract_time_text(user_text)

            if (not intent or not stock) and user_text:
                parsed = parse_query(user_text)
                stock = stock or parsed.get("stock")
                intent = intent or parsed.get("intent")

            # Guardrail: recommendation/rating language should route to recommendations endpoint.
            lower_text = (user_text or "").lower()
            recommendation_keywords = ("recommendation", "recommendations", "rating", "ratings", "analyst", "analysts", "sentiment")
            if any(keyword in lower_text for keyword in recommendation_keywords):
                intent = "RECOMMENDATIONS_QUERY"

            if intent and stock:
                finn_data = query_finnhub(intent, stock, time_text=time_text)
                response = {"intent": intent, "stock": stock, "data": finn_data}
            else:
                response = {"error": "Could not parse intent or stock"}

        except Exception as exc:
            logger.exception("Error handling MCP websocket message")
            response = {"error": f"MCP handler error: {exc}"}

        await websocket.send(json.dumps(response))

# ---------------------------
# 8. Run server
# ---------------------------
async def main():
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY is not set. Requests to Finnhub will fail until it is configured.")
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("MCP Stock Server running on ws://0.0.0.0:8765")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())