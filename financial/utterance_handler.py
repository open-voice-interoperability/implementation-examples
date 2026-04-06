#!/usr/bin/env python3
"""
Utterance Handler - Financial Agent

Processes natural language queries about stock prices and earnings.
Routes parsed requests to the Finnhub MCP websocket server.

MCP server must be running:
    python mcp_server.py   (starts on ws://127.0.0.1:8765)
"""

import re
import logging
import asyncio
import json
import importlib
from datetime import datetime, timedelta
import websockets

logger = logging.getLogger(__name__)

MCP_WS_URL = "ws://127.0.0.1:8765"


# ---------------------------
# NLP extraction (shared with mcp_server)
# ---------------------------
FORTUNE_100_STOCKS = {
    "WMT": "Walmart",
    "AMZN": "Amazon",
    "AAPL": "Apple",
    "UNH": "UnitedHealth Group",
    "BRK.B": "Berkshire Hathaway",
    "CVS": "CVS Health",
    "XOM": "Exxon Mobil",
    "GOOGL": "Alphabet",
    "MCK": "McKesson",
    "COR": "Cencora",
    "COST": "Costco Wholesale",
    "JPM": "JPMorgan Chase",
    "MSFT": "Microsoft",
    "CAH": "Cardinal Health",
    "CVX": "Chevron",
    "CI": "Cigna",
    "F": "Ford Motor",
    "BAC": "Bank of America",
    "GM": "General Motors",
    "ELV": "Elevance Health",
    "C": "Citigroup",
    "CNC": "Centene",
    "KR": "Kroger",
    "HD": "Home Depot",
    "MPC": "Marathon Petroleum",
    "WBA": "Walgreens Boots Alliance",
    "FNMA": "Fannie Mae",
    "CMCSA": "Comcast",
    "T": "AT&T",
    "META": "Meta Platforms",
    "VZ": "Verizon Communications",
    "VLO": "Valero Energy",
    "DELL": "Dell Technologies",
    "PSX": "Phillips 66",
    "TGT": "Target",
    "BA": "Boeing",
    "ADM": "Archer Daniels Midland",
    "FMCC": "Freddie Mac",
    "TSLA": "Tesla",
    "PG": "Procter & Gamble",
    "PEP": "PepsiCo",
    "JNJ": "Johnson & Johnson",
    "TSN": "Tyson Foods",
    "INTC": "Intel",
    "MET": "MetLife",
    "PRU": "Prudential Financial",
    "ACI": "Albertsons",
    "SYY": "Sysco",
    "FDX": "FedEx",
    "HUM": "Humana",
    "ET": "Energy Transfer",
    "CAT": "Caterpillar",
    "CSCO": "Cisco Systems",
    "PFE": "Pfizer",
    "LMT": "Lockheed Martin",
    "HCA": "HCA Healthcare",
    "GS": "Goldman Sachs",
    "MS": "Morgan Stanley",
    "AXP": "American Express",
    "NKE": "Nike",
    "BBY": "Best Buy",
    "CHTR": "Charter Communications",
    "MRK": "Merck",
    "UPS": "United Parcel Service",
    "ORCL": "Oracle",
    "WFC": "Wells Fargo",
    "MOH": "Molina Healthcare",
    "TJX": "TJX Companies",
    "GD": "General Dynamics",
    "DE": "Deere & Company",
    "PGR": "Progressive",
    "RTX": "RTX",
    "IP": "International Paper",
    "HON": "Honeywell",
    "COP": "ConocoPhillips",
    "EXC": "Exelon",
    "DG": "Dollar General",
    "TRV": "Travelers",
    "MMM": "3M",
    "NFLX": "Netflix",
    "QCOM": "Qualcomm",
    "USFD": "US Foods",
    "MDLZ": "Mondelez International",
    "MU": "Micron Technology",
    "NVDA": "NVIDIA",
    "ABBV": "AbbVie",
    "LLY": "Eli Lilly",
    "CRM": "Salesforce",
    "ADBE": "Adobe",
    "PYPL": "PayPal",
    "UBER": "Uber Technologies",
    "ABNB": "Airbnb",
    "KO": "Coca-Cola",
    "DIS": "Walt Disney",
    "IBM": "IBM",
    "MA": "Mastercard",
    "V": "Visa",
    "BMY": "Bristol Myers Squibb",
    "GILD": "Gilead Sciences",
    "CL": "Colgate-Palmolive",
}

COMPANY_SYNONYMS = {
    "Google": "GOOGL",
    "Facebook": "META",
    "Berkshire": "BRK.B",
    "Berkshire Hathaway": "BRK.B",
    "UnitedHealth": "UNH",
    "United Health": "UNH",
    "J and J": "JNJ",
    "J&J": "JNJ",
    "Johnson and Johnson": "JNJ",
    "P and G": "PG",
    "Procter and Gamble": "PG",
    "P&G": "PG",
    "Coke": "KO",
    "Coca Cola": "KO",
    "AT&T": "T",
    "ATT": "T",
    "Disney": "DIS",
    "Home Depot": "HD",
    "Boeing": "BA",
    "Nvidia": "NVDA",
    "JP Morgan": "JPM",
    "JPMorgan": "JPM",
    "Bank of America": "BAC",
    "MasterCard": "MA",
    "Walgreens": "WBA",
    "Costco": "COST",
    "Ford": "F",
    "GM": "GM",
}

MARKET_INDICES = {
    "^DJI": "Dow Jones Industrial Average",
    "^IXIC": "Nasdaq Composite",
    "^GSPC": "S&P 500",
    "^RUT": "Russell 2000",
    "^VIX": "CBOE Volatility Index",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX",
    "^FCHI": "CAC 40",
    "^STOXX50E": "EURO STOXX 50",
    "^STOXX600": "STOXX Europe 600",
}

INDEX_SYNONYMS = {
    "Dow": "^DJI",
    "Dow Jones": "^DJI",
    "Dow Jones Industrial Average": "^DJI",
    "Nasdaq": "^IXIC",
    "Nasdaq Composite": "^IXIC",
    "S&P 500": "^GSPC",
    "S and P 500": "^GSPC",
    "SP500": "^GSPC",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
    "FTSE": "^FTSE",
    "FTSE 100": "^FTSE",
    "UK market": "^FTSE",
    "British market": "^FTSE",
    "DAX": "^GDAXI",
    "German DAX": "^GDAXI",
    "German market": "^GDAXI",
    "CAC": "^FCHI",
    "CAC 40": "^FCHI",
    "French market": "^FCHI",
    "France market": "^FCHI",
    "Euro Stoxx 50": "^STOXX50E",
    "EURO STOXX 50": "^STOXX50E",
    "Eurozone market": "^STOXX50E",
    "Stoxx 600": "^STOXX600",
    "STOXX Europe 600": "^STOXX600",
    "European market": "^STOXX600",
    "Europe market": "^STOXX600",
}

INDEX_TRACKING_ETFS = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "DIA": "SPDR Dow Jones Industrial Average ETF Trust",
    "IWM": "iShares Russell 2000 ETF",
    "EWU": "iShares MSCI United Kingdom ETF",
    "EWG": "iShares MSCI Germany ETF",
    "EWQ": "iShares MSCI France ETF",
    "FEZ": "SPDR EURO STOXX 50 ETF",
    "VGK": "Vanguard FTSE Europe ETF",
}

INDEX_ETF_SYNONYMS = {
    "Nasdaq 100": "QQQ",
    "Nasdaq-100": "QQQ",
    "Dow ETF": "DIA",
    "S&P ETF": "SPY",
    "SP 500 ETF": "SPY",
    "Russell 2000 ETF": "IWM",
    "FTSE ETF": "EWU",
    "DAX ETF": "EWG",
    "CAC ETF": "EWQ",
    "Euro Stoxx ETF": "FEZ",
    "Europe ETF": "VGK",
}

INDEX_PROXY_INFO = {
    "DIA": {"index_name": "Dow", "multiplier": 100.0},
    "SPY": {"index_name": "S&P 500", "multiplier": 10.0},
    "QQQ": {"index_name": "Nasdaq-100", "multiplier": 40.0},
    "IWM": {"index_name": "Russell 2000", "multiplier": 10.0},
}

INDEX_SYMBOL_TO_PROXY_ETF = {
    "^DJI": "DIA",
    "^GSPC": "SPY",
    "^IXIC": "QQQ",
    "^RUT": "IWM",
    "^FTSE": "EWU",
    "^GDAXI": "EWG",
    "^FCHI": "EWQ",
    "^STOXX50E": "FEZ",
    "^STOXX600": "VGK",
}

TICKER_LOOKUP = {v.lower(): k for k, v in FORTUNE_100_STOCKS.items()}
TICKER_LOOKUP.update({alias.lower(): ticker for alias, ticker in COMPANY_SYNONYMS.items()})
TICKER_LOOKUP.update({v.lower(): k for k, v in MARKET_INDICES.items()})
TICKER_LOOKUP.update({alias.lower(): ticker for alias, ticker in INDEX_SYNONYMS.items()})
TICKER_LOOKUP.update({v.lower(): k for k, v in INDEX_TRACKING_ETFS.items()})
TICKER_LOOKUP.update({alias.lower(): ticker for alias, ticker in INDEX_ETF_SYNONYMS.items()})

_NLP_CONTEXT = None


def _get_nlp_context():
    global _NLP_CONTEXT
    if _NLP_CONTEXT is not None:
        return _NLP_CONTEXT

    spacy = importlib.import_module("spacy")
    matcher_module = importlib.import_module("spacy.matcher")
    Matcher = matcher_module.Matcher

    # Use a lightweight blank English pipeline and rule-based extraction only.
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
    ruler_patterns = []
    for ticker, name in FORTUNE_100_STOCKS.items():
        ruler_patterns.append({"label": "STOCK", "pattern": ticker})
        ruler_patterns.append({"label": "STOCK", "pattern": name})
    for ticker, name in MARKET_INDICES.items():
        ruler_patterns.append({"label": "STOCK", "pattern": ticker})
        ruler_patterns.append({"label": "STOCK", "pattern": name})
    for ticker, name in INDEX_TRACKING_ETFS.items():
        ruler_patterns.append({"label": "STOCK", "pattern": ticker})
        ruler_patterns.append({"label": "STOCK", "pattern": name})
    for alias in COMPANY_SYNONYMS:
        ruler_patterns.append({"label": "STOCK", "pattern": alias})
    for alias in INDEX_SYNONYMS:
        ruler_patterns.append({"label": "STOCK", "pattern": alias})
    for alias in INDEX_ETF_SYNONYMS:
        ruler_patterns.append({"label": "STOCK", "pattern": alias})
    ruler.add_patterns(ruler_patterns)

    matcher = Matcher(nlp.vocab)
    stock_entity = [{"ENT_TYPE": "STOCK"}]

    matcher.add("PRICE_QUERY", [
        [{"LOWER": {"IN": ["price", "quote", "trading"]}}, {"LOWER": {"IN": ["of", "for"]}, "OP": "?"}] + stock_entity,
        [{"LOWER": {"IN": ["get", "show", "fetch", "give"]}}, {"LOWER": "me", "OP": "?"}, {"LOWER": {"IN": ["current", "latest"]}, "OP": "*"}, {"LOWER": {"IN": ["price", "quote"]}}, {"LOWER": {"IN": ["of", "for"]}, "OP": "?"}] + stock_entity,
        [{"LOWER": {"IN": ["what", "what's", "whats"]}}, {"LOWER": {"IN": ["is", "s"]}, "OP": "?"}, {"LOWER": "a", "OP": "?"}, {"LOWER": {"IN": ["price", "quote", "value", "level"]}}, {"LOWER": {"IN": ["of", "for"]}, "OP": "?"}] + stock_entity,
    ])
    matcher.add("PROFILE_QUERY", [
        [{"LOWER": {"IN": ["company", "corporate"]}}, {"LOWER": {"IN": ["profile", "overview", "details"]}}] + stock_entity,
        [{"LOWER": {"IN": ["tell", "show", "give"]}}, {"LOWER": "me", "OP": "?"}, {"LOWER": {"IN": ["about", "details"]}}] + stock_entity,
    ])
    matcher.add("FINANCIAL_QUERY", [
        [{"LOWER": {"IN": ["financial", "financials"]}}, {"LOWER": {"IN": ["statements", "data", "reports"]}}] + stock_entity,
        [{"LOWER": {"IN": ["balance", "income", "cash"]}}, {"LOWER": {"IN": ["sheet", "statement", "flow"]}}] + stock_entity,
    ])
    matcher.add("NEWS_QUERY", [
        [{"LOWER": {"IN": ["news", "headlines", "articles"]}}, {"LOWER": {"IN": ["for", "about"]}, "OP": "?"}] + stock_entity,
        [{"LOWER": {"IN": ["recent", "latest"]}, "OP": "*"}, {"LOWER": {"IN": ["news", "updates"]}}, {"LOWER": {"IN": ["on", "for"]}, "OP": "?"}] + stock_entity,
    ])
    matcher.add("EARNINGS_QUERY", [
        [{"LOWER": "earnings"}, {"LOWER": {"IN": ["history", "reports", "data"]}}] + stock_entity,
        [{"LOWER": {"IN": ["show", "get"]}}, {"LOWER": "earnings"}] + stock_entity,
    ])
    matcher.add("DIVIDEND_QUERY", [
        [{"LOWER": {"IN": ["dividend", "dividends", "yield", "payout"]}}, {"LOWER": {"IN": ["for", "of"]}, "OP": "?"}] + stock_entity,
        [{"LOWER": {"IN": ["show", "get", "what"]}}, {"LOWER": "me", "OP": "?"}, {"LOWER": {"IN": ["latest", "current"]}, "OP": "*"}, {"LOWER": {"IN": ["dividend", "yield"]}}, {"LOWER": {"IN": ["for", "of"]}, "OP": "?"}] + stock_entity,
    ])
    matcher.add("RECOMMENDATIONS_QUERY", [
        [{"LOWER": {"IN": ["recommendation", "recommendations", "rating", "ratings"]}}, {"LOWER": {"IN": ["for", "on", "about"]}, "OP": "?"}] + stock_entity,
        [{"LOWER": {"IN": ["analyst", "analysts"]}}, {"LOWER": {"IN": ["recommendation", "recommendations", "rating", "ratings", "sentiment"]}}] + stock_entity,
        [{"LOWER": {"IN": ["show", "get", "give", "what"]}}, {"LOWER": "me", "OP": "?"}, {"LOWER": {"IN": ["analyst", "street"]}, "OP": "?"}, {"LOWER": {"IN": ["recommendations", "ratings", "sentiment"]}}, {"LOWER": {"IN": ["for", "on", "about"]}, "OP": "?"}] + stock_entity,
    ])
    matcher.add("HISTORY_QUERY", [
        [{"LOWER": {"IN": ["financial", "revenue", "profit"]}}, {"LOWER": {"IN": ["history", "performance", "trend"]}}] + stock_entity,
    ])

    _NLP_CONTEXT = {
        "nlp": nlp,
        "matcher": matcher,
    }
    return _NLP_CONTEXT

TIME_PHRASE_RE = re.compile(r"(from .+ to .+|last \d+ (days|months|years)|this month|this year|yesterday|today|on [a-z0-9,\-/ ]+)", re.IGNORECASE)


def parse_query(text: str) -> dict:
    context = _get_nlp_context()
    nlp = context["nlp"]
    matcher = context["matcher"]

    doc = nlp(text)
    matches = matcher(doc)
    result = {"intent": None, "stock": None}

    for ent in doc.ents:
        if ent.label_ == "STOCK":
            ent_text = ent.text.strip()
            mapped_symbol = TICKER_LOOKUP.get(ent_text.lower())
            result["stock"] = mapped_symbol or ent_text.upper()

    if matches:
        match_id, _start, _end = matches[0]
        result["intent"] = nlp.vocab.strings[match_id]

    return result


def get_stock_display_name(symbol: str) -> str:
    """Return a human-readable stock/index name for prompts."""
    if not symbol:
        return "that stock"

    normalized = symbol.upper()
    if normalized in FORTUNE_100_STOCKS:
        return FORTUNE_100_STOCKS[normalized]
    if normalized in MARKET_INDICES:
        return MARKET_INDICES[normalized]
    if normalized in INDEX_TRACKING_ETFS:
        return INDEX_TRACKING_ETFS[normalized]

    return normalized


def parse_time_range(text: str) -> tuple[int, int]:
    dateparser = importlib.import_module("dateparser")
    now = datetime.utcnow()
    default_from = now.replace(year=now.year - 1)
    default_to = now

    if text.lower().startswith("on "):
        specific_date = dateparser.parse(text[3:].strip(), settings={"RELATIVE_BASE": now})
        if specific_date:
            day_start = datetime(specific_date.year, specific_date.month, specific_date.day)
            day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
            return int(day_start.timestamp()), int(day_end.timestamp())

    if "from" in text.lower() and "to" in text.lower():
        parts = text.lower().split("to")
        start = dateparser.parse(parts[0].replace("from", "").strip())
        end = dateparser.parse(parts[1].strip())
        if start and end:
            return int(start.timestamp()), int(end.timestamp())

    relative = dateparser.parse(text, settings={"RELATIVE_BASE": now})
    if relative:
        return int(relative.timestamp()), int(now.timestamp())

    return int(default_from.timestamp()), int(default_to.timestamp())


def extract_time_text(text: str) -> str | None:
    match = TIME_PHRASE_RE.search(text)
    return match.group(0) if match else None


def _has_earnings_intent(text: str) -> bool:
    """Return True if the query appears to be about earnings/revenue/EPS."""
    keywords = ["earning", "eps", "revenue", "profit", "income", "quarterly", "annual report"]
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _has_dividend_intent(text: str) -> bool:
    """Return True if the query appears to be about dividends or yield."""
    keywords = ["dividend", "yield", "payout", "ex-dividend", "ex dividend", "distribution"]
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _has_recommendations_intent(text: str) -> bool:
    """Return True if the query appears to be about analyst recommendations or ratings."""
    keywords = ["recommendation", "recommendations", "rating", "ratings", "analyst", "analysts", "sentiment"]
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _has_price_intent(text: str) -> bool:
    """Return True if the query appears to ask for current quote/price/value."""
    keywords = ["price", "quote", "trading", "value", "level", "worth", "current", "latest"]
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _resolve_intent(user_text: str, parsed_intent: str | None) -> str | None:
    intent = parsed_intent

    if not intent:
        if _has_recommendations_intent(user_text):
            intent = "RECOMMENDATIONS_QUERY"
        elif _has_dividend_intent(user_text):
            intent = "DIVIDEND_QUERY"
        elif _has_earnings_intent(user_text):
            intent = "EARNINGS_QUERY"
        elif _has_price_intent(user_text):
            intent = "PRICE_QUERY"

    if _has_recommendations_intent(user_text):
        intent = "RECOMMENDATIONS_QUERY"

    return intent


async def _call_mcp_server_async(payload: dict) -> dict:
    try:
        async with websockets.connect(MCP_WS_URL) as websocket:
            await websocket.send(json.dumps(payload))
            response = await websocket.recv()
            return json.loads(response)
    except ConnectionRefusedError:
        logger.error("Cannot reach MCP websocket server at %s", MCP_WS_URL)
        return {"error": "MCP server is not running. Please start mcp_server.py first."}
    except OSError:
        logger.error("Cannot reach MCP websocket server at %s", MCP_WS_URL)
        return {"error": "MCP server is not running. Please start mcp_server.py first."}
    except Exception as e:
        logger.exception("Unexpected error calling MCP websocket server")
        return {"error": str(e)}


def _call_mcp_server(payload: dict) -> dict:
    return asyncio.run(_call_mcp_server_async(payload))


def _format_quote_response(result: dict, symbol: str = "?") -> str:
    if "error" in result:
        return f"Sorry, I couldn't retrieve the stock data: {result['error']}"

    # Finnhub /quote fields: c=current price, dp=percent change
    price = result.get("c")
    change = result.get("dp")

    if not price:
        return f"I retrieved data for {symbol}, but the price wasn't available."

    price_str = f"${price:,.2f}"
    proxy_info = INDEX_PROXY_INFO.get((symbol or "").upper())

    def _proxy_suffix() -> str:
        if not proxy_info:
            return ""
        implied_value = price * proxy_info["multiplier"]
        return (
            f", implying an approximate {proxy_info['index_name']} level of "
            f"{implied_value:,.0f}"
        )

    if change is not None:
        direction = "up" if change >= 0 else "down"
        change_str = f"{abs(change):.2f}%"
        if proxy_info:
            return (
                f"{symbol} ({proxy_info['index_name']} proxy) is currently trading at {price_str}, "
                f"{direction} {change_str} today{_proxy_suffix()}."
            )
        return f"{symbol} is currently trading at {price_str}, {direction} {change_str} today."
    else:
        if proxy_info:
            return (
                f"{symbol} ({proxy_info['index_name']} proxy) is currently trading at {price_str}"
                f"{_proxy_suffix()}."
            )
        return f"{symbol} is currently trading at {price_str}."


def _format_history_response(result: dict, symbol: str = "?", time_text: str | None = None) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve historical stock data: {result['error']}"

    if not isinstance(result, dict):
        return f"I couldn't understand the historical price response for {symbol}."

    closes = result.get("c") or []
    timestamps = result.get("t") or []
    status = result.get("s")

    if status != "ok" or not closes or not timestamps:
        if time_text:
            return f"I couldn't find historical price data for {symbol} {time_text}."
        return f"I couldn't find historical price data for {symbol}."

    close_price = closes[-1]
    ts = timestamps[-1]
    date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")

    if time_text:
        return f"{symbol} closed at ${close_price:,.2f} on {date_str} ({time_text})."
    return f"{symbol} closed at ${close_price:,.2f} on {date_str}."


def _format_profile_response(result: dict, symbol: str = "?") -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve company profile data: {result['error']}"

    if not isinstance(result, dict) or not result:
        return f"I couldn't find profile data for {symbol}."

    name = result.get("name") or symbol
    ticker = result.get("ticker") or symbol
    industry = result.get("finnhubIndustry")
    country = result.get("country")
    exchange = result.get("exchange")
    ipo = result.get("ipo")

    parts = [f"{name} ({ticker})"]
    if industry:
        parts.append(f"is in the {industry} industry")
    if country:
        parts.append(f"based in {country}")
    if exchange:
        parts.append(f"listed on {exchange}")
    if ipo:
        parts.append(f"with IPO date {ipo}")

    if len(parts) == 1:
        return f"I found profile data for {symbol}, but it had limited details."

    return " ".join(parts) + "."


def _format_financial_response(result: dict, symbol: str = "?") -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve financial report data: {result['error']}"

    if not isinstance(result, dict):
        return f"I couldn't understand the financial report data for {symbol}."

    reports = result.get("data") or []
    if not reports:
        return f"No recent financial reports were found for {symbol}."

    latest = reports[0]
    year = latest.get("year")
    quarter = latest.get("quarter")
    report = latest.get("report") or {}

    revenue = None
    net_income = None

    income_items = report.get("ic") or []
    for item in income_items:
        concept = str(item.get("concept", "")).lower()
        if revenue is None and ("revenue" in concept or concept == "us-gaap_revenues"):
            revenue = item.get("value")
        if net_income is None and ("netincome" in concept or "netincomeloss" in concept):
            net_income = item.get("value")

    period_label = f"Q{quarter} {year}" if quarter and year else "the latest period"
    parts = [f"For {symbol} in {period_label}:"]

    if revenue is not None:
        parts.append(f"revenue was ${revenue:,.0f}")
    if net_income is not None:
        parts.append(f"net income was ${net_income:,.0f}")

    if len(parts) == 1:
        return f"I found a financial report for {symbol} in {period_label}, but key figures weren't available."

    return " ".join(parts) + "."


def _format_news_response(result, symbol: str = "?") -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve news for {symbol}: {result['error']}"

    articles = result if isinstance(result, list) else []
    if not articles:
        return f"I couldn't find recent news for {symbol}."

    top = articles[:3]
    lines = [f"Top recent news for {symbol}:"]
    for article in top:
        headline = article.get("headline") or "(no headline)"
        source = article.get("source") or "Unknown source"
        lines.append(f"- {headline} ({source})")

    return "\n".join(lines)


def _format_earnings_response(result, symbol: str = "?") -> str:
    # Finnhub /stock/earnings returns a list of records
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve earnings data: {result['error']}"

    records = result if isinstance(result, list) else []
    if not records:
        return "No earnings data was found for that ticker."

    latest = records[0]
    actual = latest.get("actual")
    estimate = latest.get("estimate")
    period = latest.get("period", "recent period")
    surprise_pct = latest.get("surprisePercent")

    parts = [f"Latest earnings for {symbol} ({period}):"]

    if actual is not None:
        parts.append(f"EPS of ${actual:.2f}")
    if estimate is not None:
        parts.append(f"vs estimate of ${estimate:.2f}")
    if surprise_pct is not None:
        direction = "beat" if surprise_pct >= 0 else "missed"
        parts.append(f"{direction} estimates by {abs(surprise_pct):.2f}%")

    if len(parts) == 1:
        return f"Earnings data for {symbol} is available but contained no figures."

    return " ".join(parts) + "."


def _format_dividend_response(result, symbol: str = "?") -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve dividend data: {result['error']}"

    records = result if isinstance(result, list) else []
    if not records:
        return f"I couldn't find dividend history for {symbol}."

    latest = records[0]
    amount = latest.get("amount")
    ex_date = latest.get("exDate")
    pay_date = latest.get("paymentDate")
    record_date = latest.get("recordDate")
    declared_date = latest.get("declarationDate")
    freq = latest.get("frequency")

    parts = [f"Latest dividend for {symbol}:"]
    if amount is not None:
        parts.append(f"${amount:.4f} per share")
    if ex_date:
        parts.append(f"ex-dividend date {ex_date}")
    if pay_date:
        parts.append(f"payment date {pay_date}")
    if record_date:
        parts.append(f"record date {record_date}")
    if declared_date:
        parts.append(f"declared on {declared_date}")
    if freq:
        parts.append(f"frequency: {freq}")

    if len(parts) == 1:
        return f"Dividend data is available for {symbol}, but key fields were missing."

    return " ".join(parts) + "."


def _format_recommendations_response(result, symbol: str = "?") -> str:
    if isinstance(result, dict) and "error" in result:
        return f"Sorry, I couldn't retrieve analyst recommendations: {result['error']}"

    records = result if isinstance(result, list) else []
    if not records:
        return f"I couldn't find analyst recommendation data for {symbol}."

    latest = records[0] or {}
    period = latest.get("period") or "the latest reporting period"
    strong_buy = int(latest.get("strongBuy") or 0)
    buy = int(latest.get("buy") or 0)
    hold = int(latest.get("hold") or 0)
    sell = int(latest.get("sell") or 0)
    strong_sell = int(latest.get("strongSell") or 0)

    bullish_total = strong_buy + buy
    bearish_total = sell + strong_sell

    sentiment = "mixed"
    if bullish_total > bearish_total and bullish_total >= hold:
        sentiment = "mostly bullish"
    elif bearish_total > bullish_total and bearish_total >= hold:
        sentiment = "mostly bearish"
    elif hold > max(bullish_total, bearish_total):
        sentiment = "mostly neutral"

    return (
        f"Analyst recommendations for {symbol} in {period} are {sentiment}: "
        f"{strong_buy} strong buy, {buy} buy, {hold} hold, {sell} sell, and {strong_sell} strong sell."
    )


_HELP_TEXT = (
    "I can look up stock prices, earnings, and dividend data for publicly traded companies. "
    "Try asking something like: 'What is the price of NVDA?' or "
    "'Show me Apple earnings.' or 'What is Coca-Cola's latest dividend?' or 'What are analyst recommendations for NVDA?'"
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
        return ""

    lower = user_text.lower()

    # Finn should stay silent unless the user clearly asks about a stock/index with a supported intent.
    if any(w in lower for w in ["help", "hello", "hi ", "hey", "what can you"]):
        return ""

    parsed = parse_query(user_text)
    intent = _resolve_intent(user_text, parsed.get("intent"))
    stock = parsed.get("stock")
    time_text = extract_time_text(user_text)

    if not intent or not stock:
        logger.info("Ignoring Finn query without both intent and stock/index: intent=%s stock=%s", intent, stock)
        return ""

    lower_text = user_text.lower()
    if intent == "PRICE_QUERY" and time_text and any(word in lower_text for word in ["was", "on", "historical", "history", "closed"]):
        intent = "HISTORY_QUERY"

    # Free-tier fallback: map direct index symbols to liquid proxy ETFs.
    stock = INDEX_SYMBOL_TO_PROXY_ETF.get(stock, stock)

    mcp_payload = {
        "intent": intent,
        "stock": stock,
        "time_text": time_text,
        "text": user_text,
    }

    logger.info("Parsed query intent=%s stock=%s", intent, stock)
    mcp_response = _call_mcp_server(mcp_payload)

    if "error" in mcp_response:
        return f"Sorry, I couldn't retrieve stock data: {mcp_response['error']}"

    symbol = mcp_response.get("stock", stock)
    result = mcp_response.get("data")
    if result is None:
        return "I couldn't understand the stock response from the data service."

    if intent == "EARNINGS_QUERY":
        return _format_earnings_response(result, symbol=symbol)
    if intent == "HISTORY_QUERY":
        return _format_history_response(result, symbol=symbol, time_text=time_text)
    if intent == "PROFILE_QUERY":
        return _format_profile_response(result, symbol=symbol)
    if intent == "FINANCIAL_QUERY":
        return _format_financial_response(result, symbol=symbol)
    if intent == "NEWS_QUERY":
        return _format_news_response(result, symbol=symbol)
    if intent == "DIVIDEND_QUERY":
        return _format_dividend_response(result, symbol=symbol)
    if intent == "RECOMMENDATIONS_QUERY":
        return _format_recommendations_response(result, symbol=symbol)
    return _format_quote_response(result, symbol=symbol)
