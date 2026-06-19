#!/usr/bin/env python3
"""
Competitive Intelligence Agent — Startup Strategy Floor

Maps the competitive landscape using SEC EDGAR filings and USPTO patent data.
Identifies key players, white space, and differentiation opportunities.

Port: 8201
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import mcp_client
import llm_utils

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Competitive Intelligence specialist for startup strategy.
Your job is to map the competitive landscape for a startup idea.

When given patent and SEC filing data, produce a structured competitive analysis:
- Key competitors and their market positions
- Patent landscape: who owns IP, where are the gaps
- Differentiation opportunities: where can a new entrant win
- Competitive moats existing players have (and how to route around them)
- White space: underserved segments or approaches

Be specific. Use the data you're given. Cite which companies you found in the research.
Call out if the space is too crowded or if there's a clear opening.
Keep response to maximum 50 words."""


class CompetitiveAgent(BaseStrategyAgent):
    AGENT_NAME = "Competitive Intelligence"
    AGENT_PORT = 8201
    AGENT_SYNOPSIS = "Maps competitive landscape using SEC filings and USPTO patent data"
    AGENT_CAPABILITY_DETAIL = "Maps competitors, patent ownership, moat structure, differentiation opportunities, and white-space openings."
    AGENT_KEYPHRASES = ["competitors", "competition", "market map", "patents", "differentiation",
                        "competitive", "landscape", "players", "moat"]

    def process_utterance(self, user_text: str) -> str:
        gathered = []

        try:
            edgar_data = mcp_client.call_tool_sync_or_none(
                "edgar", "full_text_search",
                {"query": user_text[:100], "form_type": "10-K", "limit": 5}
            )
            if edgar_data:
                gathered.append(f"Competitor SEC filings:\n{edgar_data}")
        except Exception as e:
            logger.warning(f"EDGAR search failed: {e}")

        try:
            patent_data = mcp_client.call_tool_sync_or_none(
                "uspto", "get_patent_landscape",
                {"technology": user_text[:80], "years_back": 5, "limit": 20}
            )
            if patent_data:
                gathered.append(f"Patent landscape:\n{patent_data}")
        except Exception as e:
            logger.warning(f"USPTO search failed: {e}")

        context = "\n\n".join(gathered) if gathered else "No data available — use general knowledge."

        user_message = f"""Startup concept: {user_text}

Research data:
{context}

Please provide a competitive landscape analysis."""

        return llm_utils.chat_sync(SYSTEM_PROMPT, user_message)


def main() -> None:
    agent = CompetitiveAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(CompetitiveAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
