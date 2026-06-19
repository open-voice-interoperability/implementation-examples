#!/usr/bin/env python3
"""
Funding Strategist Agent — Startup Strategy Floor

Estimates funding requirements and milestones using EDGAR comparable
company financials and FRED macro conditions.

Port: 8204
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
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
Keep response to maximum 50 words."""


class FundingAgent(BaseStrategyAgent):
    AGENT_NAME = "Funding Strategist"
    AGENT_PORT = 8204
    AGENT_SYNOPSIS = "Produces funding roadmap and milestone plan using comparable financials"
    AGENT_CAPABILITY_DETAIL = "Recommends funding stage, raise size, valuation range, use-of-funds mix, investor signals, and runway planning."
    AGENT_KEYPHRASES = ["funding", "investment", "raise", "venture", "capital", "seed", "Series A",
                        "investor", "valuation", "runway", "equity", "dilution", "VC"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        try:
            macro = mcp_client.call_tool_sync_or_none("fred", "get_macro_snapshot", {})
            if macro:
                gathered.append(f"Current macro conditions:\n{macro}")
        except Exception as e:
            logger.warning(f"FRED call failed: {e}")

        try:
            s1_data = mcp_client.call_tool_sync_or_none(
                "edgar", "full_text_search",
                {"query": user_text[:80], "form_type": "S-1", "limit": 5}
            )
            if s1_data:
                gathered.append(f"Comparable company S-1 financials:\n{s1_data}")
        except Exception as e:
            logger.warning(f"EDGAR search failed: {e}")

        try:
            wb_data = mcp_client.call_tool_sync_or_none(
                "worldbank", "get_indicator",
                {"country_code": "US", "indicator_code": "NY.GDP.MKTP.KD.ZG", "years": 3}
            )
            if wb_data:
                gathered.append(f"US GDP growth trend:\n{wb_data}")
        except Exception as e:
            logger.warning(f"World Bank call failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No external data — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Financial and macro data:
{context}

Please produce a funding strategy and roadmap."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = FundingAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(FundingAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
