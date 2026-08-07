#!/usr/bin/env python3
"""
Market Validator Agent — Startup Strategy Floor

Sizes the market opportunity using World Bank and SEC EDGAR data.
Produces TAM/SAM/SOM estimates with real data sources.

Port: 8200
"""

import json
import logging
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app, render_bar_chart_png
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)


def _prewarm_worldbank() -> None:
    """Pre-populate the worldbank US cache at server startup so the first real
    request finds it already there instead of paying the subprocess-spawn cost."""
    try:
        mcp_client.call_tool_sync_or_none("worldbank", "get_country_overview", {"country_code": "US"})
        logger.info("Market Agent: worldbank US cache pre-warmed")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Market Agent: worldbank pre-warm failed: %s", exc)


# Fire off the pre-warm immediately when this module is imported (i.e. at server start).
threading.Thread(target=_prewarm_worldbank, daemon=True).start()

SYSTEM_PROMPT = """You are a Market Validator for startup strategy analysis.
Your job is to assess market size and demand for a startup idea.

You have access to real economic data. Use it to estimate TAM, SAM, and SOM with
clear dollar figures, plus a brief assessment of demand drivers and market maturity.

Be specific and data-driven. Write in plain prose only — no markdown, bold, or bullets.

Derive TAM/SAM/SOM from this specific idea and the research data provided —
work from the actual market/sector, target customer, and geography described,
not a generic template. Two different startup ideas should essentially never
land on the same dollar figures; if you notice yourself reaching for a round
number you've used before, stop and re-derive it from this idea's specifics.

Return your response as a single JSON object with exactly these two fields:
{
  "text": "your prose analysis here; length guided by a separate instruction",
  "bars": [
    {"label": "TAM", "value": <number>, "display": "<e.g. $1.2B>"},
    {"label": "SAM", "value": <number>, "display": "<e.g. $180M>"},
    {"label": "SOM", "value": <number>, "display": "<e.g. $9M>"}
  ]
}

The "bars" array must contain exactly three entries in this order: TAM, SAM, SOM.
- "value" is the raw dollar amount as a plain number (used to size the bar) —
  compute it for this idea; do not copy the placeholder figures above.
- "display" is the human-readable string form of that same number (e.g. '$1.2B').
Output nothing outside the JSON object. Do NOT include any SVG or HTML."""


def _build_market_svg(bars: list[dict]) -> str:
    """Render a TAM/SAM/SOM bar chart as a PNG image.
    All positioning is computed here so labels never overlap the bars."""
    colors = ["#2196F3", "#00897B", "#43A047"]
    rows = []
    for item in bars[:3]:
        label = str(item.get("label", ""))[:6]
        display = str(item.get("display", ""))[:12]
        try:
            value = max(0.0, float(item.get("value", 0)))
        except (TypeError, ValueError):
            value = 0.0
        rows.append((label, value, display))

    if not rows:
        return ""

    max_val = max((v for _, v, _ in rows), default=0) or 1
    max_bar_w = 230
    chart_rows = [
        (label, round(value / max_val * max_bar_w), display, colors[i % len(colors)])
        for i, (label, value, display) in enumerate(rows)
    ]
    return render_bar_chart_png(
        "Market Size", chart_rows,
        row_h=44, top=35, bar_h=26,
        alt="Market size chart",
    )


class MarketAgent(BaseStrategyAgent):
    AGENT_NAME = "Market Validator"
    AGENT_PORT = 8200
    AGENT_SYNOPSIS = "Sizes market opportunity using World Bank and SEC EDGAR data"
    AGENT_CAPABILITY_DETAIL = "Analyzes market size, demand drivers, TAM, SAM, SOM, market maturity, and geographic focus using macro and filings data."
    AGENT_KEYPHRASES = ["market", "size", "TAM", "SAM", "demand", "opportunity", "growth",
                        "addressable", "segment", "geography"]

    def process_utterance(self, user_text: str) -> dict | str:
        gathered = []

        wb_data, edgar_data = mcp_client.call_tools_parallel_sync([
            ("worldbank", "get_country_overview", {"country_code": "US"}),
            ("edgar", "full_text_search", {"query": user_text[:80], "form_type": "S-1", "limit": 2}),
        ], timeout=10.0)
        if wb_data:
            gathered.append(f"US economic context:\n{wb_data}")
        if edgar_data:
            gathered.append(f"Comparable company market descriptions from S-1 filings:\n{edgar_data}")

        context = "\n\n".join(gathered) if gathered else "No external data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Research data gathered:
{context}

Please provide a market sizing analysis with TAM/SAM/SOM estimates as a JSON object."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                text = (parsed.get("text") or "").strip()
                bars = parsed.get("bars") or []
                html = _build_market_svg(bars) if isinstance(bars, list) else ""
                if text:
                    return {"text": text, "html": html}
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
        return raw


def main() -> None:
    agent = MarketAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(MarketAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
