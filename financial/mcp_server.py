import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY")
print("Finnhub key loaded:", FINNHUB_KEY is not None)

# ---------------------------
# TOOL: STOCK QUOTE
# ---------------------------
def get_stock_quote(symbol):
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_KEY}"
    r = requests.get(url)
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
    url = f"https://finnhub.io/api/v1/stock/earnings?symbol={symbol}&token={FINNHUB_KEY}"
    r = requests.get(url)
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

    try:
        if tool == "get_stock_quote":
            result = get_stock_quote(args["symbol"])
        elif tool == "get_earnings":
            result = get_earnings(args["symbol"])
        else:
            return jsonify({"error": "Unknown tool"}), 400

        return jsonify({"result": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("MCP server running on http://127.0.0.1:8000")
    app.run(port=8000)