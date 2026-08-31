#!/usr/bin/env python3
"""
Risk Identifier Agent — Startup Strategy Floor

Extracts risk factors from comparable SEC filings and produces
a structured risk register for the startup concept.

Port: 8203
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

SYSTEM_PROMPT = """You are a Risk Identifier for startup strategy analysis.
Your job is to surface the risks that could kill this startup.

You have access to real risk factor disclosures from SEC filings of comparable companies.
Use this data to produce a structured risk register:

For each major risk:
- Risk name
- Description (specific, not generic)
- Severity: High / Medium / Low
- Likelihood: High / Medium / Low
- Mitigation: what the startup can do about it

Risk categories to cover:
1. Market risks (demand doesn't materialize, timing is off)
2. Competitive risks (incumbents respond, new entrants)
3. Regulatory / legal risks
4. Technology / execution risks
5. Financing risks (can't raise next round)
6. Team / talent risks

Be specific. Cite the comparable companies where you found similar risks.
Don't just list generic startup risks — connect them to this specific concept.
Cite the source of your data.

Pick the top 4 risks that are actually most severe for THIS idea, and name
and score them from this concept and its data, not the category checklist
above. The checklist is coverage guidance, not a template to echo back
verbatim — two different startup ideas should rarely produce the same four
labels or the same severities; if you catch yourself reusing labels or
scores from habit, stop and re-derive them from this idea's specifics.

Return your response as a single JSON object:
{
  "text": "plain prose summary of top risks; length guided by a separate instruction",
  "risks": [
    {"label": "<short risk name>", "severity": <1-10>},
    {"label": "<short risk name>", "severity": <1-10>},
    {"label": "<short risk name>", "severity": <1-10>},
    {"label": "<short risk name>", "severity": <1-10>}
  ]
}

The "risks" array must contain the top 4 risks ordered highest severity first.
- "label" is a short risk name (max ~16 characters) specific to this idea.
- "severity" is an integer from 1 (low) to 10 (critical).
Output nothing outside the JSON object. Do NOT include any SVG or HTML."""


def _severity_color(severity: float) -> str:
    if severity >= 8:
        return "#e53935"
    if severity >= 5:
        return "#FB8C00"
    return "#FDD835"


def _build_risk_svg(risks: list[dict]) -> str:
    """Render a top-risks-by-severity bar chart as a PNG image.
    All positioning is computed here so labels never overlap the bars."""
    rows = []
    for item in risks[:4]:
        label = str(item.get("label", ""))[:16]
        try:
            severity = max(0.0, min(10.0, float(item.get("severity", 0))))
        except (TypeError, ValueError):
            severity = 0.0
        rows.append((label, severity))

    if not rows:
        return ""

    max_bar_w = 190      # keep bars clear of the fixed score column at x=325
    score_x = 325
    chart_rows = [
        (label, max(2, round(severity / 10 * max_bar_w)), f"{severity:g}/10", _severity_color(severity))
        for label, severity in rows
    ]
    return render_bar_chart_png(
        "Top Risks by Severity", chart_rows,
        row_h=40, top=32, bar_h=22, value_x=score_x,
        alt="Top risks by severity chart",
    )


class RiskAgent(BaseStrategyAgent):
    AGENT_NAME = "Risk Identifier"
    AGENT_PORT = 8203
    AGENT_SYNOPSIS = "Identifies startup risks from SEC risk factor disclosures"
    AGENT_CAPABILITY_DETAIL = "Builds a startup risk register with severity, likelihood, and mitigation, grounded in comparable SEC risk disclosures."
    AGENT_KEYPHRASES = ["risk", "risks", "regulatory", "compliance", "failure", "threat",
                        "danger", "concern", "problem", "challenge", "legal"]

    def process_utterance(self, user_text: str) -> dict | str:
        gathered = []

        edgar_results, macro = mcp_client.call_tools_parallel_sync([
            ("edgar", "full_text_search", {"query": f"{user_text[:80]} risk factors", "form_type": "10-K", "limit": 3}),
            ("fred", "get_macro_snapshot", {}),
        ])
        if edgar_results:
            gathered.append(f"Risk factor disclosures from comparable companies:\n{edgar_results}")
        if macro:
            gathered.append(f"Macro risk conditions:\n{macro}")

        context = "\n\n".join(gathered) if gathered else "No external data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Risk research data:
{context}

Please produce a structured risk register for this startup."""

        raw = llm_utils.chat_sync(SYSTEM_PROMPT, user_message)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                parsed = json.loads(match.group())
                text = (parsed.get("text") or "").strip()
                risks = parsed.get("risks") or []
                html = _build_risk_svg(risks) if isinstance(risks, list) else ""
                if text:
                    return {"text": text, "html": html}
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}")
        return raw


def main() -> None:
    agent = RiskAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(RiskAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
