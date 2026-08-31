#!/usr/bin/env python3
"""
Funding Strategist Agent — Startup Strategy Floor

Estimates funding requirements and milestones using EDGAR comparable
company financials and FRED macro conditions.

Port: 8204
"""

import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app, render_bar_chart_png
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Funding Strategist for startup strategy analysis.
Your job is to produce a realistic funding roadmap.

You have access to macro data and comparable company financials.
Produce a structured funding plan:

1. Funding stage recommendation (pre-seed / seed / Series A / bootstrap)
   - How much to raise at each stage
   - What milestones unlock the next round
   - Typical valuation range at each stage (given current macro conditions)

2. Use of funds breakdown (as % allocation):
   - Product / engineering
   - Go-to-market / sales
   - Operations
   - Reserve

3. Key investor signals to target
   - What type of investors (angels, micro-VCs, strategic, etc.)
   - What traction they want to see before writing a check

4. Runway analysis
   - Burn rate estimate
   - How long the raise should last

Ground your estimates in current macro conditions (interest rates, VC sentiment).
Be honest if the current funding environment is difficult for this category.
Cite the source of your financial data.

Work out the actual allocation this idea needs — a hardware-heavy concept,
a pure software product, and a services business do not split the same way.
Two different startup ideas should rarely land on the same percentages; if
you catch yourself reaching for a familiar round split out of habit, stop
and re-derive it from this idea's actual cost structure.

Return your response as a single JSON object:
{
  "text": "plain prose funding summary; length guided by a separate instruction",
  "funds": [
    {"label": "<category>", "pct": <whole number>},
    {"label": "<category>", "pct": <whole number>},
    {"label": "<category>", "pct": <whole number>},
    {"label": "<category>", "pct": <whole number>}
  ]
}

The "funds" array must contain the use-of-funds allocation as whole-number
percentages that sum to 100, computed for this idea. Use short category
labels (max ~14 characters) drawn from what this specific idea actually
needs to spend on.
Output nothing outside the JSON object. Do NOT include any SVG or HTML."""


def _build_funds_svg(funds: list[dict]) -> str:
    """Render a use-of-funds bar chart as a PNG image.
    Positioning is computed here so labels never overlap the bars."""
    rows = []
    for item in funds[:6]:
        label = str(item.get("label", ""))[:16]
        try:
            pct = max(0, min(100, float(item.get("pct", 0))))
        except (TypeError, ValueError):
            pct = 0
        rows.append((label, pct))

    if not rows:
        return ""

    max_bar_w = 220
    chart_rows = [
        (label, round(pct / 100 * max_bar_w), f"{pct:g}%", "#1565C0")
        for label, pct in rows
    ]
    return render_bar_chart_png(
        "Use of Funds", chart_rows,
        row_h=40, top=32, bar_h=22,
        alt="Use of funds chart",
    )


class FundingAgent(BaseStrategyAgent):
    AGENT_NAME = "Funding Strategist"
    AGENT_PORT = 8204
    AGENT_SYNOPSIS = "Produces funding roadmap and milestone plan using comparable financials"
    AGENT_CAPABILITY_DETAIL = "Recommends funding stage, raise size, valuation range, use-of-funds mix, investor signals, and runway planning."
    AGENT_KEYPHRASES = ["funding", "investment", "raise", "venture", "capital", "seed", "Series A",
                        "investor", "valuation", "runway", "equity", "dilution", "VC"]

    def process_utterance(self, user_text: str) -> dict | str:
        gathered = []

        macro, s1_data, wb_data = mcp_client.call_tools_parallel_sync([
            ("fred", "get_macro_snapshot", {}),
            ("edgar", "full_text_search", {"query": user_text[:80], "form_type": "S-1", "limit": 5}),
            ("worldbank", "get_indicator", {"country_code": "US", "indicator_code": "NY.GDP.MKTP.KD.ZG", "years": 3}),
        ])
        if macro:
            gathered.append(f"Current macro conditions:\n{macro}")
        if s1_data:
            gathered.append(f"Comparable company S-1 financials:\n{s1_data}")
        if wb_data:
            gathered.append(f"US GDP growth trend:\n{wb_data}")

        context = "\n\n".join(gathered) if gathered else "No external data — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Financial and macro data:
{context}

Please produce a funding strategy and roadmap."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                text = (parsed.get("text") or "").strip()
                funds = parsed.get("funds") or []
                html = _build_funds_svg(funds) if isinstance(funds, list) else ""
                if text:
                    return {"text": text, "html": html}
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
        return raw


def main() -> None:
    agent = FundingAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(FundingAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
