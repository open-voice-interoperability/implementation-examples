#!/usr/bin/env python3
"""
FRED (Federal Reserve Economic Data) MCP Server

Provides access to macroeconomic data from the St. Louis Fed.
Requires a free API key from https://fred.stlouisfed.org/docs/api/api_key.html

Tools exposed:
  - search_series(query) -> find relevant FRED data series
  - get_series(series_id, limit) -> time-series observations
  - get_macro_snapshot() -> quick dashboard of key macro indicators
  - get_sector_conditions(sector) -> relevant macro data for a business sector
"""

import httpx
import json
import os
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
FRED_API_KEY = os.getenv("FRED_API_KEY", "")  # Free at fred.stlouisfed.org

mcp = FastMCP("fred")


def _fred_params(extra: dict = None) -> dict:
    params = {"api_key": FRED_API_KEY, "file_type": "json"}
    if extra:
        params.update(extra)
    return params


@mcp.tool()
async def search_series(query: str, limit: int = 10) -> str:
    """
    Search FRED for economic data series by keyword.
    Returns series IDs needed for get_series tool.
    Examples: 'interest rate', 'venture capital', 'small business', 'unemployment'
    """
    if not FRED_API_KEY:
        return json.dumps({"error": "FRED_API_KEY not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"})

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{FRED_BASE}/series/search",
            params=_fred_params({"search_text": query, "limit": limit, "order_by": "popularity"}),
        )
        if r.status_code != 200:
            return json.dumps({"error": f"FRED returned {r.status_code}"})

        data = r.json()
        series_list = data.get("seriess", [])
        results = [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "frequency": s.get("frequency"),
                "units": s.get("units"),
                "last_updated": s.get("last_updated"),
            }
            for s in series_list
        ]
        return json.dumps(results)


@mcp.tool()
async def get_series(series_id: str, limit: int = 12) -> str:
    """
    Get observations for a FRED data series.
    Common series IDs:
      FEDFUNDS  - Federal Funds Rate
      CPIAUCSL  - Consumer Price Index (inflation)
      UNRATE    - Unemployment Rate
      DGS10     - 10-Year Treasury Rate
      VIXCLS    - CBOE Volatility Index (market risk)
      SBCSVA    - Small Business Lending (quarterly)
    """
    if not FRED_API_KEY:
        return json.dumps({"error": "FRED_API_KEY not set. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"})

    async with httpx.AsyncClient(timeout=15) as client:
        # Get series metadata
        meta_r = await client.get(
            f"{FRED_BASE}/series",
            params=_fred_params({"series_id": series_id}),
        )
        # Get observations
        obs_r = await client.get(
            f"{FRED_BASE}/series/observations",
            params=_fred_params({
                "series_id": series_id,
                "limit": limit,
                "sort_order": "desc",
            }),
        )

        if obs_r.status_code != 200:
            return json.dumps({"error": f"FRED returned {obs_r.status_code} for {series_id}"})

        obs_data = obs_r.json()
        observations = [
            {"date": o.get("date"), "value": o.get("value")}
            for o in obs_data.get("observations", [])
            if o.get("value") != "."
        ]

        title = series_id
        if meta_r.status_code == 200:
            meta = meta_r.json().get("seriess", [{}])[0]
            title = meta.get("title", series_id)

        return json.dumps({
            "series_id": series_id,
            "title": title,
            "observations": observations,
        })


@mcp.tool()
async def get_macro_snapshot() -> str:
    """
    Get a quick snapshot of key macroeconomic indicators relevant to startup strategy.
    Covers: interest rates, inflation, unemployment, VC sentiment (VIX).
    """
    key_series = {
        "Federal Funds Rate": "FEDFUNDS",
        "Inflation (CPI YoY)": "CPIAUCSL",
        "Unemployment Rate": "UNRATE",
        "10-Year Treasury": "DGS10",
        "Market Volatility (VIX)": "VIXCLS",
    }

    snapshot = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for label, sid in key_series.items():
            if not FRED_API_KEY:
                snapshot[label] = {"error": "FRED_API_KEY not set"}
                continue
            r = await client.get(
                f"{FRED_BASE}/series/observations",
                params=_fred_params({"series_id": sid, "limit": "1", "sort_order": "desc"}),
            )
            if r.status_code == 200:
                obs = r.json().get("observations", [{}])
                if obs:
                    snapshot[label] = {"value": obs[0].get("value"), "date": obs[0].get("date")}

    return json.dumps({"macro_snapshot": snapshot})


@mcp.tool()
async def get_sector_conditions(sector: str) -> str:
    """
    Get macro conditions relevant to a specific business sector.
    sector examples: 'tech', 'retail', 'manufacturing', 'fintech', 'healthcare'
    """
    sector_series = {
        "tech": {
            "VC Investment Sentiment (VIX)": "VIXCLS",
            "10-Year Treasury (discount rate)": "DGS10",
            "Unemployment (talent supply)": "UNRATE",
        },
        "retail": {
            "Consumer Confidence": "UMCSENT",
            "Retail Sales": "RSXFS",
            "Inflation (CPI)": "CPIAUCSL",
        },
        "manufacturing": {
            "Industrial Production": "INDPRO",
            "Producer Price Index": "PPIACO",
            "Unemployment": "UNRATE",
        },
        "fintech": {
            "Federal Funds Rate": "FEDFUNDS",
            "10-Year Treasury": "DGS10",
            "Consumer Credit": "TOTALSL",
        },
        "healthcare": {
            "Medical CPI": "CPIMEDSL",
            "Unemployment": "UNRATE",
            "10-Year Treasury": "DGS10",
        },
    }

    chosen = sector_series.get(sector.lower(), sector_series["tech"])
    results = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for label, sid in chosen.items():
            if not FRED_API_KEY:
                results[label] = {"error": "FRED_API_KEY not set"}
                continue
            r = await client.get(
                f"{FRED_BASE}/series/observations",
                params=_fred_params({"series_id": sid, "limit": "3", "sort_order": "desc"}),
            )
            if r.status_code == 200:
                obs = r.json().get("observations", [])
                results[label] = [
                    {"date": o.get("date"), "value": o.get("value")}
                    for o in obs
                    if o.get("value") != "."
                ]

    return json.dumps({"sector": sector, "conditions": results})


if __name__ == "__main__":
    mcp.run()
