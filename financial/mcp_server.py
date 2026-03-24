import os
import logging
from pathlib import Path
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load .env from the same directory as this script
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)
logger.info(f"Loading .env from: {env_path}")

app = Flask(__name__)
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")
logger.info(f"Finnhub key loaded: {FINNHUB_KEY is not None}")
if not FINNHUB_KEY:
    logger.warning("FINNHUB_API_KEY is not set in environment variables")

# ---------------------------
# TOOL: STOCK QUOTE
# ---------------------------
def get_stock_quote(symbol):
    logger.debug(f"get_stock_quote called with symbol={symbol}, key={FINNHUB_KEY is not None}")
    if not FINNHUB_KEY:
        raise ValueError("FINNHUB_API_KEY environment variable is not set")
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
    logger.debug(f"Requesting: {url}")
    r = requests.get(url)
    logger.debug(f"Response status: {r.status_code}")
    r.raise_for_status()
    data = r.json()

    return {
        "symbol": symbol,
        "current_price": data.get("c"),
        "change_percent": data.get("dp")
    }

# ---------------------------
# TOOL: EARNINGS
# ---------------------------
def get_earnings(symbol):
    logger.debug(f"get_earnings called with symbol={symbol}, key={FINNHUB_KEY is not None}")
    if not FINNHUB_KEY:
        raise ValueError("FINNHUB_API_KEY environment variable is not set")
    url = f"https://finnhub.io/api/v1/stock/earnings?symbol={symbol}&token={FINNHUB_KEY}"
    logger.debug(f"Requesting: {url}")
    r = requests.get(url)
    logger.debug(f"Response status: {r.status_code}")
    r.raise_for_status()
    data = r.json()

    if not data:
        return {}

    latest = data[-1]
    return {
        "symbol": symbol,
        "revenue_growth": latest.get("revenueGrowth"),
        "eps": latest.get("eps")
    }

# ---------------------------
# MCP ENDPOINT
# ---------------------------
@app.route("/call_tool", methods=["POST"])
def call_tool():
    payload = request.json
    tool = payload.get("tool")
    args = payload.get("arguments", {})

    logger.debug(f"Received request: tool={tool}, args={args}")

    try:
        if tool == "get_stock_quote":
            result = get_stock_quote(args["symbol"])
        elif tool == "get_earnings":
            result = get_earnings(args["symbol"])
        else:
            return jsonify({"error": "Unknown tool"}), 400

        return jsonify({"result": result})

    except KeyError as e:
        logger.error(f"Missing argument: {e}")
        return jsonify({"error": f"Missing argument: {e}"}), 400
    except Exception as e:
        logger.exception(f"Error calling tool {tool}: {e}")
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("MCP server running on http://127.0.0.1:8000")
    logger.info("=" * 60)
    app.run(port=8000)