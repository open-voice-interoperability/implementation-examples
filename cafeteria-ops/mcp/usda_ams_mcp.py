#!/usr/bin/env python3
"""
USDA AMS MARS (My Market News) MCP Server

Provides wholesale/commodity food price data from USDA's Agricultural
Marketing Service, useful for procurement/sourcing context.
Free registration (required -- confirmed via testing that unlike FoodData
Central's DEMO_KEY, there is no anonymous fallback; requests without a key
get a 401) at https://mymarketnews.ams.usda.gov/mars-api/getting-started

Auth: the API key is passed as the HTTP Basic Auth username with an empty
password (USDA's documented convention -- not a bearer token or query param).

Tools exposed:
  - search_reports(keyword, limit) -> find relevant market news reports by keyword
  - get_report(slug_id, commodity, limit) -> real price rows for one report

Confirmed live (2026-09-18) that v1.2's /reports/{slug_id} -- the endpoint
this file used until now -- only ever returns the "Report Header" section:
one row per publication date with a prose narrative, no numeric price
fields at all. USDA AMS's actual price data (price_avg/price_min/price_max,
commodity, type/cut, region, store_count) lives in v3.1's section-based
endpoint, /reports/{slug_id}/{section}, under the "Report Details" section
-- discovered via the API's own /services/help/all listing, since v1.2
isn't in that listing at all and appears to be an undocumented legacy
version still served for backward compatibility but never updated.
"""

import httpx
import json
import os
import logging
import re
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

AMS_BASE = "https://marsapi.ams.usda.gov/services/v3.1"
AMS_API_KEY = os.getenv("AMS_API_KEY", "")

mcp = FastMCP("usda_ams")


def _auth():
    # Empty key still attempts the call -- USDA's shared/sample access tier
    # handles unauthenticated-username requests for light use; a real key
    # only raises the rate limit, per the getting-started documentation.
    return (AMS_API_KEY, "")


@mcp.tool()
async def search_reports(keyword: str, limit: int = 10) -> str:
    """
    Search USDA Market News reports by keyword (matched against each
    report's title -- report_title, e.g. "Weekly Grocery Store Beef Feature
    Activity" -- NOT slug_name, which is just an opaque internal code like
    "AMS_1034" and never contains a commodity name; matching against it
    made every keyword search return zero results regardless of the
    commodity asked about). Returns slug_id values needed for get_report.
    Examples: 'poultry', 'dairy', 'vegetables', 'grain', 'beef'
    """
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{AMS_BASE}/reports", auth=_auth())
        if r.status_code != 200:
            return json.dumps({"error": f"MARS API returned {r.status_code}: {r.text[:150]}"})

        try:
            reports = r.json()
        except Exception:
            return json.dumps({"error": "MARS API returned a non-JSON response"})

        # Whole-word match, not a bare substring test -- confirmed live
        # that a plain `keyword in title` check let a single-word
        # fallback term ("sweet", from a caller falling back off a
        # multi-word ingredient name like "sweet potatoes") match
        # "East Tennessee Livestock Center - Sweetwater, TN" purely
        # because "sweet" is a PREFIX of the place name "Sweetwater" --
        # a livestock/cattle report with nothing to do with the actual
        # commodity being searched for. \b...\b only matches "sweet" as
        # its own word (real hits like "Sweet Corn" still match fine),
        # not as a fragment of a longer word.
        try:
            pattern = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)
        except re.error:
            pattern = None
        matches = [
            {
                "slug_id": rep.get("slug_id"),
                "report_title": rep.get("report_title"),
            }
            for rep in reports
            if pattern is not None and pattern.search(rep.get("report_title") or "")
        ][:limit]

        return json.dumps({"keyword": keyword, "results": matches})


@mcp.tool()
async def get_report(slug_id: str, commodity: str = "", limit: int = 500) -> str:
    """
    Get real price rows (commodity, type/cut, region, price_avg/min/max,
    price_unit, store_count) for the MOST RECENTLY PUBLISHED edition of a
    USDA Market News report (obtained from search_reports) -- the "Report
    Details" section, which is where the actual numeric data lives (the
    plain /reports/{slug_id} endpoint returns only publication metadata,
    no prices). A report can carry hundreds of price line items per week
    across every cut/type and region it tracks, so pass ``commodity``
    (e.g. "Chicken", "Beef") to filter server-side to just that commodity
    -- the specific cut/type asked about (e.g. "thighs") still needs a
    second, client-side pass over the returned rows' "type" field, since
    USDA doesn't expose a reliable cut-level filter.
    """
    params: dict = {"lastReports": 1, "numberOfRows": max(limit, 1)}
    if commodity:
        params["q"] = f"commodity={commodity}"

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{AMS_BASE}/reports/{slug_id}/Report%20Details", params=params, auth=_auth())
        if r.status_code != 200:
            return json.dumps({"error": f"MARS API returned {r.status_code} for report {slug_id}"})

        try:
            data = r.json()
        except Exception:
            return json.dumps({"error": "MARS API returned a non-JSON response"})

        rows = data.get("results", [])
        return json.dumps({"slug_id": slug_id, "rows": rows[:limit]})


if __name__ == "__main__":
    mcp.run()
