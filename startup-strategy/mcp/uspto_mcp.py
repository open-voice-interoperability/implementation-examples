#!/usr/bin/env python3
"""
USPTO Patent MCP Server

Provides access to the USPTO PatentsView API.
No API key required.

Tools exposed:
  - search_patents(query, assignee) -> find patents by keyword or company
  - get_patent_landscape(technology) -> summarize patent activity in a tech area
  - get_assignee_patents(company_name) -> patents held by a specific company
  - compare_patent_activity(companies) -> patent filing comparison
"""

import httpx
import json
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

PATENTS_BASE = "https://search.patentsview.org/api/v1"
mcp = FastMCP("uspto")


@mcp.tool()
async def search_patents(query: str, limit: int = 10) -> str:
    """
    Search USPTO patents by keyword or technology.
    Returns patent titles, inventors, assignees, and filing dates.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {
            "q": {"_text_any": {"patent_abstract": query, "patent_title": query}},
            "f": ["patent_id", "patent_title", "patent_date", "assignee_organization",
                  "inventor_last_name", "patent_abstract"],
            "o": {"per_page": limit},
            "s": [{"patent_date": "desc"}],
        }
        r = await client.post(
            f"{PATENTS_BASE}/patent/",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"USPTO API returned {r.status_code}: {r.text[:200]}"})

        data = r.json()
        patents = data.get("patents", [])
        results = []
        for p in patents:
            assignees = [a.get("assignee_organization", "") for a in p.get("assignees", [])]
            inventors = [i.get("inventor_last_name", "") for i in p.get("inventors", [])]
            results.append({
                "id": p.get("patent_id"),
                "title": p.get("patent_title"),
                "date": p.get("patent_date"),
                "assignees": assignees,
                "inventors": inventors,
                "abstract": (p.get("patent_abstract") or "")[:300],
            })
        return json.dumps({"query": query, "count": len(results), "patents": results})


@mcp.tool()
async def get_patent_landscape(technology: str, years_back: int = 5, limit: int = 20) -> str:
    """
    Get a patent landscape overview for a technology area.
    Returns top patent holders, filing trends, and key patents.
    Useful for identifying IP density and white space.
    """
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=20) as client:
        payload = {
            "q": {
                "_and": [
                    {"_text_any": {"patent_title": technology}},
                    {"_gte": {"patent_date": cutoff}},
                ]
            },
            "f": ["patent_id", "patent_title", "patent_date", "assignee_organization"],
            "o": {"per_page": limit},
            "s": [{"patent_date": "desc"}],
        }
        r = await client.post(
            f"{PATENTS_BASE}/patent/",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"USPTO API returned {r.status_code}"})

        data = r.json()
        patents = data.get("patents", [])

        # Count by assignee
        assignee_counts: dict = {}
        for p in patents:
            for a in p.get("assignees", []):
                org = a.get("assignee_organization", "Unknown")
                if org:
                    assignee_counts[org] = assignee_counts.get(org, 0) + 1

        top_holders = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        total = data.get("total_patent_count", len(patents))

        return json.dumps({
            "technology": technology,
            "total_patents_found": total,
            "since": cutoff,
            "top_patent_holders": [{"company": c, "count": n} for c, n in top_holders],
            "recent_patents": [
                {"title": p.get("patent_title"), "date": p.get("patent_date")}
                for p in patents[:5]
            ],
        })


@mcp.tool()
async def get_assignee_patents(company_name: str, limit: int = 20) -> str:
    """
    Get patents assigned to a specific company.
    Useful for understanding a competitor's IP portfolio.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {
            "q": {"_contains": {"assignee_organization": company_name}},
            "f": ["patent_id", "patent_title", "patent_date", "assignee_organization",
                  "cpc_group_id"],
            "o": {"per_page": limit},
            "s": [{"patent_date": "desc"}],
        }
        r = await client.post(
            f"{PATENTS_BASE}/patent/",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"USPTO API returned {r.status_code}"})

        data = r.json()
        patents = data.get("patents", [])
        total = data.get("total_patent_count", 0)

        # Group by CPC category
        categories: dict = {}
        for p in patents:
            for cpc in p.get("cpcs", []):
                group = cpc.get("cpc_group_id", "")[:3]
                if group:
                    categories[group] = categories.get(group, 0) + 1

        return json.dumps({
            "company": company_name,
            "total_patents": total,
            "technology_categories": dict(sorted(categories.items(), key=lambda x: x[1], reverse=True)[:8]),
            "recent_patents": [
                {"title": p.get("patent_title"), "date": p.get("patent_date")}
                for p in patents[:10]
            ],
        })


@mcp.tool()
async def compare_patent_activity(companies: list) -> str:
    """
    Compare patent filing activity across multiple companies.
    Useful for understanding competitive IP intensity.
    companies: list of company names e.g. ["Apple", "Google", "Samsung"]
    """
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for company in companies:
            payload = {
                "q": {"_contains": {"assignee_organization": company}},
                "f": ["patent_id", "patent_date"],
                "o": {"per_page": 1},
            }
            r = await client.post(
                f"{PATENTS_BASE}/patent/",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                data = r.json()
                results[company] = data.get("total_patent_count", 0)

    ranked = sorted(results.items(), key=lambda x: x[1], reverse=True)
    return json.dumps({
        "comparison": [{"company": c, "total_patents": n} for c, n in ranked]
    })


if __name__ == "__main__":
    mcp.run()
