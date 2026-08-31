#!/usr/bin/env python3
"""
TheMealDB MCP Server

Provides real recipe ideas -- ingredient lists, instructions, category/area
-- for menu planning. Free, no signup required for non-commercial/prototype
use: the shared test key "1" (the default for THEMEALDB_API_KEY) works
immediately. See https://www.themealdb.com/api.php for a paid key if you
need commercial use or higher limits.

Tools exposed:
  - search_by_name(name) -> recipes matching a dish name
  - search_by_ingredient(ingredient) -> recipes featuring a main ingredient
  - get_recipe_details(meal_id) -> full ingredients + instructions for one recipe
  - random_recipe() -> a single random recipe, for inspiration
"""

import httpx
import json
import os
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

THEMEALDB_API_KEY = os.getenv("THEMEALDB_API_KEY", "1")
THEMEALDB_BASE = f"https://www.themealdb.com/api/json/v1/{THEMEALDB_API_KEY}"

mcp = FastMCP("themealdb")


def _summarize_meal(meal: dict) -> dict:
    return {
        "id": meal.get("idMeal"),
        "name": meal.get("strMeal"),
        "category": meal.get("strCategory"),
        "area": meal.get("strArea"),
        "thumbnail": meal.get("strMealThumb"),
    }


def _full_meal(meal: dict) -> dict:
    ingredients = []
    for i in range(1, 21):
        ingredient = (meal.get(f"strIngredient{i}") or "").strip()
        measure = (meal.get(f"strMeasure{i}") or "").strip()
        if ingredient:
            ingredients.append(f"{measure} {ingredient}".strip())
    return {
        "id": meal.get("idMeal"),
        "name": meal.get("strMeal"),
        "category": meal.get("strCategory"),
        "area": meal.get("strArea"),
        "instructions": meal.get("strInstructions"),
        "ingredients": ingredients,
    }


@mcp.tool()
async def search_by_name(name: str) -> str:
    """
    Search for recipes by dish name.
    Examples: 'chicken curry', 'lentil soup', 'stir fry'
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{THEMEALDB_BASE}/search.php", params={"s": name})
        if r.status_code != 200:
            return json.dumps({"error": f"TheMealDB returned {r.status_code}"})

        meals = r.json().get("meals") or []
        return json.dumps({"query": name, "results": [_summarize_meal(m) for m in meals]})


@mcp.tool()
async def search_by_ingredient(ingredient: str) -> str:
    """
    Find recipes that feature a given main ingredient.
    Examples: 'chicken_breast', 'lentils', 'broccoli', 'salmon'
    (use underscores for multi-word ingredients, matching TheMealDB's convention)
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{THEMEALDB_BASE}/filter.php", params={"i": ingredient})
        if r.status_code != 200:
            return json.dumps({"error": f"TheMealDB returned {r.status_code}"})

        meals = r.json().get("meals") or []
        return json.dumps({"ingredient": ingredient, "results": [_summarize_meal(m) for m in meals]})


@mcp.tool()
async def get_recipe_details(meal_id: str) -> str:
    """
    Get full ingredients (with measures) and step-by-step instructions for
    a specific recipe (obtained from search_by_name or search_by_ingredient).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{THEMEALDB_BASE}/lookup.php", params={"i": meal_id})
        if r.status_code != 200:
            return json.dumps({"error": f"TheMealDB returned {r.status_code} for meal {meal_id}"})

        meals = r.json().get("meals") or []
        if not meals:
            return json.dumps({"error": f"No recipe found for meal id {meal_id}"})
        return json.dumps(_full_meal(meals[0]))


@mcp.tool()
async def random_recipe() -> str:
    """Get one random recipe for menu inspiration."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{THEMEALDB_BASE}/random.php")
        if r.status_code != 200:
            return json.dumps({"error": f"TheMealDB returned {r.status_code}"})

        meals = r.json().get("meals") or []
        if not meals:
            return json.dumps({"error": "TheMealDB returned no recipe"})
        return json.dumps(_full_meal(meals[0]))


if __name__ == "__main__":
    mcp.run()
