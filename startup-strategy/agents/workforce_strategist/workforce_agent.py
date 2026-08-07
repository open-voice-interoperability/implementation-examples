#!/usr/bin/env python3
"""
Workforce Strategist Agent — Startup Strategy Floor

Provides talent cost and availability analysis using BLS wage data
and World Bank labor statistics.

Port: 8205
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

SYSTEM_PROMPT = """You are a Workforce Strategist for startup strategy analysis.
Your job is to assess the talent implications of this startup.

You have access to real BLS wage data and labor market statistics.
Produce a structured workforce analysis:

1. Key roles needed to build and scale this startup
   - For each role: estimated annual compensation (use BLS data where available)
   - Availability: is this talent scarce or abundant?

2. Team composition for MVP vs. scale
   - Who do you need on day 1 (founding team)?
   - Who do you hire after seed round?
   - Who do you hire after Series A?

3. Build vs. buy vs. outsource recommendations
   - What should be in-house vs. contracted vs. automated

4. Talent risks
   - Are there skills that are hard to hire for?
   - Are there geographic concentrations of the needed talent?

5. Total people cost estimate for first 18 months

Use actual BLS wage data. Be specific about job titles and compensation ranges.
Cite the source of your wage data (e.g. "According to BLS, a software engineer in the tech sector has a median annual wage of $120k").

Name the 4 roles this specific idea actually needs first, in this idea's own
sector — not a generic tech-company default. A coffeehouse, a biotech
company, and a SaaS platform need different roles at different pay; if
you're about to reach for "Sr Engineer / Product Mgr / Designer / Ops Lead"
out of habit, stop and reconsider whether those are really this idea's top
4 roles.

Return your response as a single JSON object:
{
  "text": "plain prose workforce summary; length guided by a separate instruction",
  "roles": [
    {"label": "<role title>", "salary": <annual comp>, "display": "<e.g. $95K>"},
    {"label": "<role title>", "salary": <annual comp>, "display": "<e.g. $95K>"},
    {"label": "<role title>", "salary": <annual comp>, "display": "<e.g. $95K>"},
    {"label": "<role title>", "salary": <annual comp>, "display": "<e.g. $95K>"}
  ]
}

The "roles" array must contain the top 4 roles ordered highest salary first.
- "label" is a short role/title name (max ~16 characters) specific to this idea's sector.
- "salary" is the annual compensation as a plain number (used to size the bar).
- "display" is the human-readable label (e.g. '$165K').
Output nothing outside the JSON object. Do NOT include any SVG or HTML."""


def _build_workforce_svg(roles: list[dict]) -> str:
    """Render a key-role-salaries bar chart as a PNG image.
    All positioning is computed here so labels never overlap the bars."""
    rows = []
    for item in roles[:4]:
        label = str(item.get("label", ""))[:16]
        display = str(item.get("display", ""))[:12]
        try:
            salary = max(0.0, float(item.get("salary", 0)))
        except (TypeError, ValueError):
            salary = 0.0
        rows.append((label, salary, display))

    if not rows:
        return ""

    max_val = max((s for _, s, _ in rows), default=0) or 1
    max_bar_w = 200
    chart_rows = [
        (label, max(2, round(salary / max_val * max_bar_w)), display, "#00695C")
        for label, salary, display in rows
    ]
    return render_bar_chart_png(
        "Key Role Salaries", chart_rows,
        row_h=40, top=32, bar_h=22,
        alt="Key role salaries chart",
    )


class WorkforceAgent(BaseStrategyAgent):
    AGENT_NAME = "Workforce Strategist"
    AGENT_PORT = 8205
    AGENT_SYNOPSIS = "Assesses talent needs and costs using BLS wage and employment data"
    AGENT_CAPABILITY_DETAIL = "Estimates hiring plan, role mix, compensation ranges, build-vs-buy choices, and first-18-month people costs."
    AGENT_KEYPHRASES = ["hiring", "talent", "team", "workforce", "employees", "salary", "wages",
                        "HR", "headcount", "recruiting", "skills", "people"]

    def process_utterance(self, user_text: str) -> dict | str:
        gathered = []

        sector = self._infer_sector(user_text)
        wage_data, unemployment = mcp_client.call_tools_parallel_sync([
            ("bls", "get_wage_snapshot", {"sector": sector}),
            ("bls", "get_unemployment_by_sector", {}),
        ])
        if wage_data:
            gathered.append(f"BLS wage data for {sector} sector:\n{wage_data}")
        if unemployment:
            gathered.append(f"Unemployment by sector (talent availability signal):\n{unemployment}")

        context = "\n\n".join(gathered) if gathered else "No external data — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Labor market data:
{context}

Please provide a workforce strategy and team cost analysis."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                text = (parsed.get("text") or "").strip()
                roles = parsed.get("roles") or []
                html = _build_workforce_svg(roles) if isinstance(roles, list) else ""
                if text:
                    return {"text": text, "html": html}
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
        return raw

    def _infer_sector(self, text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["software", "app", "platform", "ai", "ml", "saas", "tech"]):
            return "tech"
        if any(w in text_lower for w in ["health", "medical", "clinic", "patient", "pharma"]):
            return "healthcare"
        if any(w in text_lower for w in ["bank", "finance", "fintech", "payment", "invest"]):
            return "finance"
        if any(w in text_lower for w in ["store", "retail", "shop", "consumer", "ecommerce"]):
            return "retail"
        return "tech"


def main() -> None:
    agent = WorkforceAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(WorkforceAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
