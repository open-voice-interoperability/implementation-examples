#!/usr/bin/env python3
"""
Workforce Strategist Agent — Startup Strategy Floor

Provides talent cost and availability analysis using BLS wage data
and World Bank labor statistics.

Port: 8205
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
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
Keep response to maximum 50 words."""


class WorkforceAgent(BaseStrategyAgent):
    AGENT_NAME = "Workforce Strategist"
    AGENT_PORT = 8205
    AGENT_SYNOPSIS = "Assesses talent needs and costs using BLS wage and employment data"
    AGENT_CAPABILITY_DETAIL = "Estimates hiring plan, role mix, compensation ranges, build-vs-buy choices, and first-18-month people costs."
    AGENT_KEYPHRASES = ["hiring", "talent", "team", "workforce", "employees", "salary", "wages",
                        "HR", "headcount", "recruiting", "skills", "people"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        sector = self._infer_sector(user_text)
        try:
            wage_data = mcp_client.call_tool_sync_or_none(
                "bls", "get_wage_snapshot", {"sector": sector}
            )
            if wage_data:
                gathered.append(f"BLS wage data for {sector} sector:\n{wage_data}")
        except Exception as e:
            logger.warning(f"BLS wage call failed: {e}")

        try:
            unemployment = mcp_client.call_tool_sync_or_none(
                "bls", "get_unemployment_by_sector", {}
            )
            if unemployment:
                gathered.append(f"Unemployment by sector (talent availability signal):\n{unemployment}")
        except Exception as e:
            logger.warning(f"BLS unemployment call failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No external data — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Labor market data:
{context}

Please provide a workforce strategy and team cost analysis."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)

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
