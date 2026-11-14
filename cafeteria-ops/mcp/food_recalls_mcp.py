#!/usr/bin/env python3
"""
Food Recalls MCP Server (FDA / openFDA)

Provides real, current FDA food recall (enforcement report) data, so the
Recall Sentinel can warn when a menu uses an ingredient under an active
recall. Free; no key needed at low volume (openFDA allows 240 requests/min
and 1,000/day per IP without one). Set OPENFDA_API_KEY for higher limits:
https://open.fda.gov/apis/authentication/

Meat, poultry and processed egg products are USDA FSIS's. Its recall API
(https://www.fsis.usda.gov/fsis/api/recall/v/1) blocks automated clients,
so search_fsis_recalls reads a copy of that API's JSON saved from a browser
instead -- FSIS_RECALLS_FILE, by default cafeteria-ops/data/fsis_recalls.json
(git-ignored). Re-save it to refresh; results say how old the copy is.

Demo mode: set RECALL_FIXTURE to a JSON file of {"term": [recall, ...]} to
replay saved recalls instead of calling openFDA -- for rehearsed demos where
a matching live recall can't be counted on. Records use the same shape this
server returns.

Tools exposed:
  - search_food_recalls(term, days, limit) -> ongoing FDA Class I/II recalls
    whose product description or recall reason mentions the term
  - search_fsis_recalls(term, days, limit) -> active FSIS recalls and public
    health alerts (saved snapshot) whose product mentions the term
"""

import httpx
import json
import os
import logging
import re
from datetime import date, datetime, timedelta
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

OPENFDA_FOOD_ENFORCEMENT = "https://api.fda.gov/food/enforcement.json"
OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY", "")
RECALL_FIXTURE = os.getenv("RECALL_FIXTURE", "")
FSIS_RECALLS_FILE = os.getenv(
    "FSIS_RECALLS_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fsis_recalls.json"),
)

mcp = FastMCP("food_recalls")


def _summarize(r: dict) -> dict:
    return {
        "recall_number": r.get("recall_number"),
        "classification": r.get("classification"),
        "status": r.get("status"),
        "report_date": r.get("report_date"),
        "product": r.get("product_description"),
        "reason": r.get("reason_for_recall"),
        "firm": r.get("recalling_firm"),
        "distribution": r.get("distribution_pattern"),
    }


def _word_forms(term: str) -> list[str]:
    term = term.strip().lower()
    forms = [term]
    if " " not in term:
        if term.endswith("y") and term[-2:-1] not in "aeiou":
            forms.append(term[:-1] + "ies")
        else:
            forms += [term + "s", term + "es"]
    return forms


def _from_fixture(term: str, limit: int) -> str:
    try:
        with open(RECALL_FIXTURE, encoding="utf-8") as f:
            fixture = json.load(f)
    except (OSError, ValueError) as e:
        return json.dumps({"error": f"RECALL_FIXTURE could not be read: {e}"})
    return json.dumps({"term": term, "source": "fixture", "results": (fixture.get(term.lower()) or [])[:limit]})


@mcp.tool()
async def search_food_recalls(term: str, days: int = 90, limit: int = 20) -> str:
    """
    Search ongoing FDA food recalls (Class I and II) reported in the last
    `days` days whose product description or recall reason mentions `term`.
    Returns recall number, classification, report date (YYYYMMDD), product,
    reason, recalling firm and distribution for each.
    Examples: 'lettuce', 'jalapeno', 'cheese', 'mango'
    """
    if RECALL_FIXTURE:
        return _from_fixture(term, limit)

    today = date.today()
    since = today - timedelta(days=days)
    # openFDA matches whole words, so look for plural forms too: a menu says
    # "mango", the recall says "Fresh Whole Mangoes".
    either = " OR ".join(f'"{v}"' for v in _word_forms(term.replace('"', "")))
    search = (
        f"(product_description:({either}) OR reason_for_recall:({either}))"
        f' AND status:"Ongoing"'
        f' AND (classification:"Class I" OR classification:"Class II")'
        f" AND report_date:[{since:%Y%m%d} TO {today:%Y%m%d}]"
    )
    params = {"search": search, "limit": limit}
    if OPENFDA_API_KEY:
        params["api_key"] = OPENFDA_API_KEY

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(OPENFDA_FOOD_ENFORCEMENT, params=params)
    if r.status_code == 404:
        # openFDA answers "no matches" with a 404
        return json.dumps({"term": term, "source": "openFDA", "results": []})
    if r.status_code != 200:
        return json.dumps({"error": f"openFDA returned {r.status_code}: {r.text[:150]}"})
    return json.dumps({"term": term, "source": "openFDA", "results": [_summarize(x) for x in r.json().get("results", [])]})


# "X Recalls <product> Due to <reason>" ("X and Y Recall ..." for two firms) /
# "FSIS Issues Public Health Alert for <product> Due to <reason>" -- FSIS
# titles carry the product and hazard.
_FSIS_TITLE_RE = re.compile(
    r"^(?:(?P<firm>.+?)\s+Recalls?\s+|FSIS Issues Public Health Alert for\s+)(?P<product>.+?)(?:\s+Due to\s+(?P<reason>.+))?$",
    re.IGNORECASE,
)


def _clean(text) -> str:
    # browser saves can mangle bullets and quotes into U+FFFD
    return re.sub(r"\s+", " ", str(text or "").replace("�", " ")).strip()


def _as_list(value) -> list:
    return value if isinstance(value, list) else ([value] if value else [])


def _fsis_summary(r: dict, saved: str) -> dict:
    title = _clean(r.get("field_title"))
    match = _FSIS_TITLE_RE.match(title)
    product = _clean(match.group("product")) if match else title
    hazard = _clean(match.group("reason")) if match and match.group("reason") else ""
    categories = ", ".join(_clean(c) for c in _as_list(r.get("field_recall_reason")))
    return {
        "agency": "FSIS",
        "recall_number": _clean(r.get("field_recall_number")),
        "classification": _clean(r.get("field_recall_classification")),
        "status": _clean(r.get("field_recall_type")),
        "report_date": _clean(r.get("field_recall_date")).replace("-", ""),
        "product": product,
        "items": [_clean(i) for i in _as_list(r.get("field_product_items"))][:5],
        "reason": f"{hazard} ({categories})" if hazard and categories else (hazard or categories),
        "firm": _clean(r.get("field_establishment")) or (_clean(match.group("firm")) if match and match.group("firm") else ""),
        "distribution": ", ".join(_clean(s) for s in _as_list(r.get("field_states"))),
        "snapshot_saved": saved,
    }


@mcp.tool()
async def search_fsis_recalls(term: str, days: int = 90, limit: int = 20) -> str:
    """
    Search active USDA FSIS recalls and public health alerts (meat, poultry,
    processed egg products) from the last `days` days whose product -- per
    the recall title or product list -- mentions `term`. Reads the saved copy
    of FSIS's recall API (see FSIS_RECALLS_FILE); each result says when that
    copy was saved.
    Examples: 'chicken', 'pork sausage', 'beef'
    """
    try:
        with open(FSIS_RECALLS_FILE, "rb") as f:
            records = json.loads(f.read().decode("utf-8-sig"))
        saved = datetime.fromtimestamp(os.path.getmtime(FSIS_RECALLS_FILE)).strftime("%Y-%m-%d")
    except FileNotFoundError:
        return json.dumps({"term": term, "source": "FSIS snapshot", "results": [],
                           "note": f"no FSIS snapshot at {FSIS_RECALLS_FILE}"})
    except (OSError, ValueError) as e:
        return json.dumps({"error": f"FSIS snapshot could not be read: {e}"})

    since = (date.today() - timedelta(days=days)).isoformat()
    word = re.compile(r"\b(?:" + "|".join(re.escape(v) for v in _word_forms(term)) + r")\b", re.IGNORECASE)
    results = []
    for r in records:
        if r.get("langcode") != "English":
            continue  # the same recalls also appear in Spanish
        open_recall = r.get("field_recall_type") == "Active Recall" or (
            r.get("field_recall_type") == "Public Health Alert" and str(r.get("field_archive_recall")) == "False")
        if not open_recall or (r.get("field_recall_date") or "") < since:
            continue
        summary = _fsis_summary(r, saved)
        if word.search(summary["product"]) or any(word.search(i) for i in summary["items"]):
            results.append(summary)
    results.sort(key=lambda x: x["report_date"], reverse=True)
    return json.dumps({"term": term, "source": f"FSIS snapshot saved {saved}", "results": results[:limit]})


if __name__ == "__main__":
    mcp.run()
