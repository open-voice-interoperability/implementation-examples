#!/usr/bin/env python3
"""
Market Validator Agent — Startup Strategy Floor

Sizes the market opportunity using World Bank and SEC EDGAR data.
Produces TAM/SAM/SOM estimates with real data sources.

Port: 8200
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Market Validator for startup strategy analysis.
Your job is to assess market size and demand for a startup idea.

You have access to real economic data. When given research data, use it to produce
a structured market analysis including:
- TAM (Total Addressable Market) estimate with reasoning
- SAM (Serviceable Addressable Market)
- SOM (Serviceable Obtainable Market) for a realistic startup in year 1-3
- Key demand drivers and trends
- Market maturity assessment (emerging / growing / mature / declining)
- Geographic focus recommendation

Be specific and data-driven. Cite the data sources you used.
If the market is too small for venture scale, say so clearly.
Format your response in clear sections.
Keep response to maximum 50 words."""


class MarketAgent(BaseStrategyAgent):
    AGENT_NAME = "Market Validator"
    AGENT_PORT = 8200
    AGENT_SYNOPSIS = "Sizes market opportunity using World Bank and SEC EDGAR data"
    AGENT_CAPABILITY_DETAIL = "Analyzes market size, demand drivers, TAM, SAM, SOM, market maturity, and geographic focus using macro and filings data."
    AGENT_KEYPHRASES = ["market", "size", "TAM", "SAM", "demand", "opportunity", "growth",
                        "addressable", "segment", "geography"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        try:
            wb_data = mcp_client.call_tool_sync_or_none(
                "worldbank", "get_country_overview", {"country_code": "US"}
            )
            if wb_data:
                gathered.append(f"US economic context:\n{wb_data}")
        except Exception as e:
            logger.warning(f"World Bank call failed: {e}")

        try:
            edgar_data = mcp_client.call_tool_sync_or_none(
                "edgar", "full_text_search",
                {"query": user_text[:100], "form_type": "S-1", "limit": 3}
            )
            if edgar_data:
                gathered.append(f"Comparable company market descriptions from S-1 filings:\n{edgar_data}")
        except Exception as e:
            logger.warning(f"EDGAR call failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No external data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Research data gathered:
{context}

Please provide a market sizing analysis with TAM/SAM/SOM estimates."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = MarketAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(MarketAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
