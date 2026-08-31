#!/usr/bin/env python3
"""
USDA FoodData Central MCP Server

Provides real nutrition data for menu items and ingredients.
Requires a free API key from https://fdc.nal.usda.gov/api-key-signup
(falls back to the shared DEMO_KEY, rate-limited to 30 req/hr).

Tools exposed:
  - search_food(query, limit) -> find foods matching a keyword
  - get_food_details(fdc_id) -> full nutrient breakdown for one food
"""

import httpx
import json
import os
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

FDC_BASE = "https://api.nal.usda.gov/fdc/v1"
FDC_API_KEY = os.getenv("FDC_API_KEY", "DEMO_KEY")

mcp = FastMCP("usda_fdc")


def _extract_nutrients(food: dict, limit: int = 12) -> list[dict]:
    """foodNutrients shape differs between the search and food-detail
    endpoints (flat nutrientName/value vs nested nutrient.name/amount) --
    handle both defensively rather than assuming one."""
    results = []
    for entry in (food.get("foodNutrients") or [])[:limit]:
        nutrient = entry.get("nutrient") or {}
        name = entry.get("nutrientName") or nutrient.get("name")
        unit = entry.get("unitName") or nutrient.get("unitName")
        value = entry.get("value")
        if value is None:
            value = entry.get("amount")
        if not name:
            continue
        results.append({"name": name, "value": value, "unit": unit})
    return results


@mcp.tool()
async def search_food(query: str, limit: int = 10) -> str:
    """
    Search USDA FoodData Central for foods matching a keyword.
    Returns fdcId (needed for get_food_details), description, data type,
    and a short list of headline nutrients for each match.
    Examples: 'grilled chicken breast', 'brown rice', 'cheddar cheese'
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{FDC_BASE}/foods/search",
            params={"api_key": FDC_API_KEY, "query": query, "pageSize": limit},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"FoodData Central returned {r.status_code}: {r.text[:150]}"})

        data = r.json()
        foods = data.get("foods", [])
        results = [
            {
                "fdcId": f.get("fdcId"),
                "description": f.get("description"),
                "dataType": f.get("dataType"),
                "brandOwner": f.get("brandOwner"),
                "nutrients": _extract_nutrients(f, limit=6),
            }
            for f in foods
        ]
        return json.dumps({"query": query, "results": results})


@mcp.tool()
async def get_food_details(fdc_id: int) -> str:
    """
    Get the full nutrient breakdown for a specific food by its fdcId
    (obtained from search_food). Includes calories, macros, sodium,
    fiber, and other tracked nutrients where available.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{FDC_BASE}/food/{fdc_id}",
            params={"api_key": FDC_API_KEY},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"FoodData Central returned {r.status_code} for fdcId {fdc_id}"})

        food = r.json()
        return json.dumps({
            "fdcId": food.get("fdcId"),
            "description": food.get("description"),
            "dataType": food.get("dataType"),
            "servingSize": food.get("servingSize"),
            "servingSizeUnit": food.get("servingSizeUnit"),
            "nutrients": _extract_nutrients(food, limit=25),
        })


if __name__ == "__main__":
    mcp.run()
