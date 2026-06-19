#!/usr/bin/env python3
"""
Risk Identifier Agent — Startup Strategy Floor

Extracts risk factors from comparable SEC filings and produces
a structured risk register for the startup concept.

Port: 8203
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
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
Keep response to maximum 50 words."""


class RiskAgent(BaseStrategyAgent):
    AGENT_NAME = "Risk Identifier"
    AGENT_PORT = 8203
    AGENT_SYNOPSIS = "Identifies startup risks from SEC risk factor disclosures"
    AGENT_CAPABILITY_DETAIL = "Builds a startup risk register with severity, likelihood, and mitigation, grounded in comparable SEC risk disclosures."
    AGENT_KEYPHRASES = ["risk", "risks", "regulatory", "compliance", "failure", "threat",
                        "danger", "concern", "problem", "challenge", "legal"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        try:
            edgar_results = mcp_client.call_tool_sync_or_none(
                "edgar", "full_text_search",
                {"query": f"{user_text[:80]} risk factors", "form_type": "10-K", "limit": 3}
            )
            if edgar_results:
                gathered.append(f"Risk factor disclosures from comparable companies:\n{edgar_results}")
        except Exception as e:
            logger.warning(f"EDGAR risk search failed: {e}")

        try:
            macro = mcp_client.call_tool_sync_or_none("fred", "get_macro_snapshot", {})
            if macro:
                gathered.append(f"Macro risk conditions:\n{macro}")
        except Exception as e:
            logger.warning(f"FRED call failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No external data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Risk research data:
{context}

Please produce a structured risk register for this startup."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = RiskAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(RiskAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
