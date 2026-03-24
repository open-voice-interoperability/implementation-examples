#!/usr/bin/env python3
"""
Utterance Handler - Financial Agent

Processes natural language queries about stock prices and earnings.
Routes requests to the Finnhub MCP server running on port 8000.

MCP server must be running:
    python mcp_server.py   (starts on http://127.0.0.1:8000)
"""

import re
import logging
import requests

logger = logging.getLogger(__name__)

MCP_URL = "http://127.0.0.1:8000/call_tool"

# Map of company names / aliases → ticker symbols
COMPANY_TO_TICKER = {
    "nvidia": "NVDA",
    "nvda": "NVDA",
    "apple": "AAPL",
    "aapl": "AAPL",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "googl": "GOOGL",
    "goog": "GOOG",
    "amazon": "AMZN",
    "amzn": "AMZN",
    "microsoft": "MSFT",
    "msft": "MSFT",
    "tesla": "TSLA",
    "tsla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "nflx": "NFLX",
    "intel": "INTC",
    "intc": "INTC",
    "amd": "AMD",
    "advanced micro": "AMD",
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "jpm": "JPM",
    "bank of america": "BAC",
    "bac": "BAC",
    "disney": "DIS",
    "dis": "DIS",
    "salesforce": "CRM",
    "crm": "CRM",
    "oracle": "ORCL",
    "orcl": "ORCL",
    "ibm": "IBM",
    "qualcomm": "QCOM",
    "qcom": "QCOM",
    "broadcom": "AVGO",
    "avgo": "AVGO",
    "paypal": "PYPL",
    "pypl": "PYPL",
    "uber": "UBER",
    "lyft": "LYFT",
    "shopify": "SHOP",
    "shop": "SHOP",
    "palantir": "PLTR",
    "pltr": "PLTR",
    "coinbase": "COIN",
    "coin": "COIN",
    "visa": "V",
    "mastercard": "MA",
    "goldman": "GS",
    "goldman sachs": "GS",
    "gs": "GS",
    "s&p": "SPY",
    "spy": "SPY",
    "sp500": "SPY",
}

# Standalone capital-letter ticker pattern (2–5 uppercase letters)
TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')


def _extract_ticker(text: str) -> str | None:
    """
    Attempt to extract a stock ticker from natural-language text.

    Checks company name aliases first, then looks for all-caps tokens.
    Returns the best matching ticker or None.
    """
    lower = text.lower()

    # Company name matching (longest match first so "goldman sachs" beats "goldman")
    for alias in sorted(COMPANY_TO_TICKER, key=len, reverse=True):
        if alias in lower:
            return COMPANY_TO_TICKER[alias]

    # Explicit all-caps token that looks like a ticker
    for match in TICKER_RE.finditer(text):
        candidate = match.group(1)
        if candidate in {v for v in COMPANY_TO_TICKER.values()}:
            return candidate

    return None


def _has_earnings_intent(text: str) -> bool:
    """Return True if the query appears to be about earnings/revenue/EPS."""
    keywords = ["earning", "eps", "revenue", "profit", "income", "quarterly", "annual report"]
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _call_mcp_tool(tool: str, arguments: dict) -> dict:
    """
    Call a tool on the Finnhub MCP server.

    Args:
        tool: Tool name ("get_stock_quote" or "get_earnings")
        arguments: Dict of arguments (e.g. {"symbol": "NVDA"})

    Returns:
        Result dict from MCP server, or dict with "error" key on failure.
    """
    try:
        response = requests.post(
            MCP_URL,
            json={"tool": tool, "arguments": arguments},
            timeout=10
        )
        if not response.ok:
            try:
                error_payload = response.json()
                if isinstance(error_payload, dict):
                    error_message = error_payload.get("error") or str(error_payload)
                else:
                    error_message = str(error_payload)
            except ValueError:
                error_message = response.text or f"HTTP {response.status_code}"

            logger.error(
                "MCP server returned %s for tool %s: %s",
                response.status_code,
                tool,
                error_message
            )
            return {"error": f"MCP error ({response.status_code}): {error_message}"}

        payload = response.json()
        return payload.get("result", payload)
    except requests.exceptions.ConnectionError:
        logger.error("Cannot reach MCP server at %s", MCP_URL)
        return {"error": "MCP server is not running. Please start mcp_server.py first."}
    except requests.exceptions.Timeout:
        logger.error("MCP server request timed out")
        return {"error": "The data request timed out. Please try again."}
    except Exception as e:
        logger.exception("Unexpected error calling MCP tool %s", tool)
        return {"error": str(e)}


def _format_quote_response(result: dict) -> str:
    if "error" in result:
        return f"Sorry, I couldn't retrieve the stock data: {result['error']}"

    symbol = result.get("symbol", "?")
    price = result.get("current_price")
    change = result.get("change_percent")

    if price is None:
        return f"I retrieved data for {symbol}, but the price wasn't available."

    price_str = f"${price:,.2f}"

    if change is not None:
        direction = "up" if change >= 0 else "down"
        change_str = f"{abs(change):.2f}%"
        return f"{symbol} is currently trading at {price_str}, {direction} {change_str} today."
    else:
        return f"{symbol} is currently trading at {price_str}."


def _format_earnings_response(result: dict) -> str:
    if "error" in result:
        return f"Sorry, I couldn't retrieve earnings data: {result['error']}"

    if not result:
        return "No earnings data was found for that ticker."

    symbol = result.get("symbol", "?")
    eps = result.get("eps")
    growth = result.get("revenue_growth")

    parts = [f"Latest earnings for {symbol}:"]

    if eps is not None:
        parts.append(f"EPS of ${eps:.2f}")
    if growth is not None:
        pct = growth * 100 if abs(growth) < 10 else growth
        parts.append(f"revenue growth of {pct:.1f}%")

    if len(parts) == 1:
        return f"Earnings data for {symbol} is available but contained no figures."

    return " ".join(parts) + "."


_HELP_TEXT = (
    "I can look up stock prices and earnings data for publicly traded companies. "
    "Try asking something like: 'What is the price of NVDA?' or "
    "'Show me Apple earnings.' or 'How is Tesla doing today?'"
)


def process_utterance(user_text: str, agent_name: str = "FinancialAgent") -> str:
    """
    Main entry point called by template_agent.py.

    Args:
        user_text: The text input from the user.
        agent_name: This agent's conversational name (unused here, kept for interface parity).

    Returns:
        A plain-text response string.
    """
    if not user_text or not user_text.strip():
        return _HELP_TEXT

    lower = user_text.lower()

    # Help / greeting
    if any(w in lower for w in ["help", "hello", "hi ", "hey", "what can you"]):
        return _HELP_TEXT

    ticker = _extract_ticker(user_text)

    if ticker is None:
        return (
            "I'm not sure which stock you're asking about. "
            "Please include a ticker symbol (like NVDA or AAPL) or a company name."
        )

    if _has_earnings_intent(user_text):
        logger.info("Fetching earnings for %s", ticker)
        result = _call_mcp_tool("get_earnings", {"symbol": ticker})
        return _format_earnings_response(result)
    else:
        logger.info("Fetching stock quote for %s", ticker)
        result = _call_mcp_tool("get_stock_quote", {"symbol": ticker})
        return _format_quote_response(result)
