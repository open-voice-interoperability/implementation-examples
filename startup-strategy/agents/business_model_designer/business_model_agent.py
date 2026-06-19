#!/usr/bin/env python3
"""
Business Model Designer Agent — Startup Strategy Floor

Proposes business model options and estimates unit economics
using comparable S-1 filings from SEC EDGAR.

Port: 8202
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Business Model Designer for startup strategy.
Your job is to propose viable business models and estimate unit economics.

When given data from comparable company S-1 filings, use it to ground your analysis.
Produce a structured output covering:
- 2-3 business model options (e.g. SaaS subscription, marketplace, usage-based, freemium)
- For the recommended model: estimated unit economics
  - CAC (Customer Acquisition Cost) range
  - LTV (Lifetime Value) range
  - Gross margin estimate
  - Payback period
- Key revenue drivers and levers
- Pricing strategy recommendation

Be realistic. Reference how comparable companies structured their models.
Flag if unit economics are fundamentally broken for this model.
Keep response to maximum 50 words."""


class BusinessModelAgent(BaseStrategyAgent):
    AGENT_NAME = "Business Model Designer"
    AGENT_PORT = 8202
    AGENT_SYNOPSIS = "Proposes business models and unit economics from comparable S-1 filings"
    AGENT_CAPABILITY_DETAIL = "Designs business models, pricing, revenue levers, CAC/LTV ranges, gross margin, and payback assumptions."
    AGENT_KEYPHRASES = ["business model", "revenue", "pricing", "unit economics", "monetize",
                        "SaaS", "subscription", "marketplace", "freemium", "CAC", "LTV"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        try:
            s1_data = mcp_client.call_tool_sync_or_none(
                "edgar", "full_text_search",
                {"query": user_text[:100], "form_type": "S-1", "limit": 5}
            )
            if s1_data:
                gathered.append(f"Comparable S-1 filings (IPO prospectuses):\n{s1_data}")
        except Exception as e:
            logger.warning(f"EDGAR S-1 search failed: {e}")

        try:
            macro = mcp_client.call_tool_sync_or_none("fred", "get_macro_snapshot", {})
            if macro:
                gathered.append(f"Current macro conditions (affects valuation multiples):\n{macro}")
        except Exception as e:
            logger.warning(f"FRED call failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No external data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Research data:
{context}

Please propose business model options and estimate unit economics."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = BusinessModelAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(BusinessModelAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
