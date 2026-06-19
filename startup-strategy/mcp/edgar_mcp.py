#!/usr/bin/env python3
"""
SEC EDGAR MCP Server

Provides structured access to SEC EDGAR full-text search and filing data.
No API key required — uses the public EDGAR REST API.

Tools exposed:
  - search_companies(query) -> list of matching companies with CIK
  - get_filings(cik, form_type) -> recent filings metadata
  - get_filing_text(accession_number, section) -> extracted text section
  - search_risk_factors(cik) -> risk factor section from latest 10-K
  - search_full_text(query, form_type) -> full-text search across filings
"""

import httpx
import json
import re
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov"
EDGAR_DATA = "https://data.sec.gov"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": "startup-strategy-agent contact@example.com"}

mcp = FastMCP("edgar")


@mcp.tool()
async def search_companies(query: str, limit: int = 10) -> str:
    """
    Search SEC EDGAR for companies by name or keyword.
    Returns CIK numbers needed for other tools.
    """
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{httpx.URL(query).path}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
    # Use the company search endpoint
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={query}&CIK=&type=10-K&dateb=&owner=include&count=10&search_text=&action=getcompany&output=atom"
    # Better: use EDGAR company search API
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{query}%22&forms=10-K&dateRange=custom&startdt=2022-01-01"

    search_url = "https://efts.sec.gov/LATEST/search-index"
    params = {"q": query, "forms": "10-K", "dateRange": "custom", "startdt": "2022-01-01"}

    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        # Use the company_tickers.json for broad search
        r = await client.get(
            "https://www.sec.gov/cgi-bin/browse-edgar",
            params={"company": query, "CIK": "", "type": "10-K", "owner": "include",
                    "count": str(limit), "action": "getcompany", "output": "atom"},
        )
        if r.status_code != 200:
            return json.dumps({"error": f"EDGAR returned {r.status_code}"})

        # Parse atom feed for company names and CIKs
        cik_matches = re.findall(r'<cik>(\d+)</cik>', r.text)
        name_matches = re.findall(r'<company-name>(.*?)</company-name>', r.text)
        results = [{"name": n, "cik": c} for n, c in zip(name_matches, cik_matches)]
        return json.dumps(results[:limit])


@mcp.tool()
async def get_filings(cik: str, form_type: str = "10-K", limit: int = 5) -> str:
    """
    Get recent filings for a company by CIK number.
    form_type examples: 10-K (annual), 10-Q (quarterly), S-1 (IPO prospectus)
    """
    cik_padded = str(cik).zfill(10)
    url = f"{EDGAR_DATA}/submissions/CIK{cik_padded}.json"

    async with httpx.AsyncClient(headers=HEADERS, timeout=15) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return json.dumps({"error": f"No data for CIK {cik}"})

        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        descriptions = recent.get("primaryDocument", [])

        results = []
        for form, date, acc, doc in zip(forms, dates, accessions, descriptions):
            if form == form_type:
                results.append({
                    "form": form,
                    "date": date,
                    "accession": acc,
                    "document": doc,
                    "cik": cik,
                })
            if len(results) >= limit:
                break

        return json.dumps({
            "company": data.get("name", ""),
            "cik": cik,
            "filings": results,
        })


@mcp.tool()
async def search_risk_factors(cik: str) -> str:
    """
    Extract risk factors section from a company's latest 10-K filing.
    Useful for identifying what risks are disclosed in comparable companies.
    """
    filings_json = await get_filings(cik, "10-K", 1)
    filings = json.loads(filings_json)

    if "error" in filings or not filings.get("filings"):
        return json.dumps({"error": "No 10-K found for this company"})

    latest = filings["filings"][0]
    acc = latest["accession"].replace("-", "")
    cik_padded = str(cik).zfill(10)
    doc = latest["document"]

    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        r = await client.get(filing_url)
        if r.status_code != 200:
            return json.dumps({"error": "Could not retrieve filing document"})

        text = r.text
        # Extract risk factors section (heuristic)
        risk_start = re.search(r'(?i)(item\s+1a\.?\s+risk factors)', text)
        risk_end = re.search(r'(?i)(item\s+1b\.?\s+unresolved)', text)

        if risk_start:
            start = risk_start.start()
            end = risk_end.start() if risk_end else start + 8000
            risk_text = re.sub(r'<[^>]+>', ' ', text[start:end])
            risk_text = re.sub(r'\s+', ' ', risk_text).strip()
            return json.dumps({
                "company": filings["company"],
                "filing_date": latest["date"],
                "risk_factors": risk_text[:4000],
            })

        return json.dumps({"error": "Risk factors section not found in filing"})


@mcp.tool()
async def full_text_search(query: str, form_type: str = "10-K", limit: int = 5) -> str:
    """
    Full-text search across SEC filings.
    Useful for finding companies that mention a specific technology, market, or risk.
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        r = await client.get(
            "https://efts.sec.gov/LATEST/search-index",
            params={
                "q": f'"{query}"',
                "forms": form_type,
                "dateRange": "custom",
                "startdt": "2022-01-01",
            },
        )
        if r.status_code != 200:
            return json.dumps({"error": f"Search failed: {r.status_code}"})

        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        results = []
        for hit in hits[:limit]:
            src = hit.get("_source", {})
            results.append({
                "company": src.get("display_names", [""])[0],
                "form": src.get("form_type", ""),
                "date": src.get("file_date", ""),
                "excerpt": src.get("period_of_report", ""),
            })
        return json.dumps({"query": query, "results": results})


if __name__ == "__main__":
    mcp.run()
