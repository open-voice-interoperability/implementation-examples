#!/usr/bin/env python3
"""
Web Search MCP Server (Tavily)

General-purpose web search, used by the Procurement Specialist to ground
sourcing guidance in real current retail/grocery prices for ingredients
USDA AMS's wholesale commodity reports don't cover (e.g. quinoa, shrimp,
soy sauce -- specialty or manufactured items with no wholesale commodity
market at all). Tavily was chosen over other search APIs specifically
because its free tier (1,000 searches/month) needs no credit card --
Brave Search's free tier now requires a card on file, and Google's
Custom Search JSON API is closed to new signups as of 2025 (confirmed
via research before choosing this).

Free API key (no credit card required) at https://tavily.com

Tools exposed:
  - search(query, max_results) -> web search results with title/url/snippet,
    plus Tavily's own synthesized answer when available
"""

import httpx
import json
import os
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

TAVILY_BASE = "https://api.tavily.com"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

mcp = FastMCP("web_search")


@mcp.tool()
async def search(query: str, max_results: int = 5) -> str:
    """
    Search the web for current information (e.g. "quinoa price per pound
    grocery store", "soy sauce wholesale price"). Returns a JSON object
    with Tavily's synthesized answer (when available) plus individual
    results (title/url/content snippet).
    """
    if not TAVILY_API_KEY:
        return json.dumps({"error": "TAVILY_API_KEY not configured"})

    payload = {
        "query": query,
        "max_results": max(1, min(max_results, 10)),
        "include_answer": "basic",
    }
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{TAVILY_BASE}/search", json=payload, headers=headers)
        if r.status_code != 200:
            return json.dumps({"error": f"Tavily API returned {r.status_code}: {r.text[:150]}"})

        try:
            data = r.json()
        except Exception:
            return json.dumps({"error": "Tavily API returned a non-JSON response"})

        results = [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
            }
            for item in (data.get("results") or [])
        ]
        return json.dumps({"query": query, "answer": data.get("answer"), "results": results})


if __name__ == "__main__":
    mcp.run()
