#!/usr/bin/env python3
"""
World Bank MCP Server

Provides access to World Bank Open Data API.
No API key required.

Tools exposed:
  - search_indicators(query) -> find relevant World Bank indicators
  - get_indicator(country, indicator_code, years) -> time-series data
  - get_country_overview(country_code) -> key economic stats
  - compare_markets(countries, indicator_code) -> side-by-side comparison
"""

import httpx
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

WB_BASE = "https://api.worldbank.org/v2"
mcp = FastMCP("worldbank")


@mcp.tool()
async def search_indicators(query: str, limit: int = 10) -> str:
    """
    Search for World Bank indicators by keyword.
    Returns indicator codes needed for get_indicator tool.
    Examples: 'GDP growth', 'inflation', 'internet users', 'ease of doing business'
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{WB_BASE}/indicator",
            params={"format": "json", "per_page": str(limit), "q": query},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"World Bank returned {r.status_code}"})

        data = r.json()
        if len(data) < 2:
            return json.dumps({"error": "Unexpected response format"})

        indicators = data[1] or []
        results = [
            {"id": ind.get("id"), "name": ind.get("name"), "source": ind.get("sourceNote", "")[:200]}
            for ind in indicators
        ]
        return json.dumps(results)


@mcp.tool()
async def get_indicator(country_code: str, indicator_code: str, years: int = 5) -> str:
    """
    Get time-series data for a World Bank indicator and country.
    country_code examples: US, CN, GB, DE, IN, BR, JP
    indicator_code examples: NY.GDP.MKTP.CD (GDP), FP.CPI.TOTL.ZG (inflation),
                              IT.NET.USER.ZS (internet users), IC.BUS.EASE.XQ (ease of business)
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{WB_BASE}/country/{country_code}/indicator/{indicator_code}",
            params={"format": "json", "per_page": str(years), "mrv": str(years)},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"World Bank returned {r.status_code}"})

        data = r.json()
        if len(data) < 2 or not data[1]:
            return json.dumps({"error": f"No data for {country_code}/{indicator_code}"})

        records = data[1]
        series = [
            {"year": rec.get("date"), "value": rec.get("value")}
            for rec in records
            if rec.get("value") is not None
        ]
        meta = records[0] if records else {}
        return json.dumps({
            "country": meta.get("country", {}).get("value", country_code),
            "indicator": meta.get("indicator", {}).get("value", indicator_code),
            "data": series,
        })


@mcp.tool()
async def get_country_overview(country_code: str) -> str:
    """
    Get a quick economic overview of a country using key World Bank indicators.
    Returns GDP, GDP growth, inflation, internet penetration, ease of doing business.
    """
    indicators = {
        "GDP (current USD)": "NY.GDP.MKTP.CD",
        "GDP growth (%)": "NY.GDP.MKTP.KD.ZG",
        "Inflation (%)": "FP.CPI.TOTL.ZG",
        "Internet users (% population)": "IT.NET.USER.ZS",
        "Population": "SP.POP.TOTL",
    }

    results = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for label, code in indicators.items():
            r = await client.get(
                f"{WB_BASE}/country/{country_code}/indicator/{code}",
                params={"format": "json", "mrv": "1"},
            )
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 2 and data[1]:
                    val = data[1][0].get("value")
                    year = data[1][0].get("date")
                    results[label] = {"value": val, "year": year}

    return json.dumps({"country": country_code, "overview": results})


@mcp.tool()
async def compare_markets(country_codes: list, indicator_code: str, years: int = 3) -> str:
    """
    Compare a World Bank indicator across multiple countries.
    Useful for market sizing and benchmarking.
    country_codes: list of ISO 2-letter codes e.g. ["US", "CN", "IN"]
    """
    results = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for code in country_codes:
            r = await client.get(
                f"{WB_BASE}/country/{code}/indicator/{indicator_code}",
                params={"format": "json", "mrv": str(years)},
            )
            if r.status_code == 200:
                data = r.json()
                if len(data) >= 2 and data[1]:
                    series = [
                        {"year": rec.get("date"), "value": rec.get("value")}
                        for rec in data[1]
                        if rec.get("value") is not None
                    ]
                    country_name = data[1][0].get("country", {}).get("value", code)
                    results[country_name] = series

    indicator_name = indicator_code
    return json.dumps({"indicator": indicator_name, "comparison": results})


if __name__ == "__main__":
    mcp.run()
