#!/usr/bin/env python3
"""
generate_nasa_gallery.py

Python library to generate a NASA image gallery HTML page from a JSON collection.

Usage as CLI:
  python generate_nasa_gallery.py -i nasa_search.json -o gallery.html
  cat nasa_search.json | python generate_nasa_gallery.py > gallery.html
"""

import json
import html
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _extract_first_url(raw: Optional[str]) -> Optional[str]:
    """Extract the first https?:// URL from a string (HTML tags or escaped)."""
    if not raw:
        return None
    try:
        s = html.unescape(raw)
    except Exception:
        s = raw
    s = str(s).strip()
    s_no_tags = re.sub(r"<[^>]+>", " ", s)
    m = re.search(r"(https?://[^\"'\s<>]+)", s_no_tags)
    if m:
        return m.group(1)
    return None


def choose_image_link(
    links: List[Dict[str, Any]],
    nasa_id: Optional[str] = None,
    enable_asset_lookup: bool = True
) -> Dict[str, Optional[str]]:
    """Choose preview and full image URLs from NASA API 'links'."""
    preview = None
    full = None

    def clean_href(href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        href = str(href).strip()
        m = re.search(r"(https?://[^\"'\s<>]+)", href)
        return m.group(1) if m else None

    def looks_like_image(u: Optional[str]) -> bool:
        return bool(u and re.search(r"\.(jpe?g|png|gif|webp|bmp)(?:$|[?#])", u, re.I))

    # First pass: pick rel=preview or canonical
    for l in links:
        rel = (l.get("rel") or "").lower()
        href = clean_href(l.get("href"))
        if not href:
            continue
        if rel == "preview" and not preview:
            preview = href
        if rel in ("canonical", "orig", "original") and not full:
            full = href

    # Second pass for preview
    if not preview:
        for l in links:
            rel = (l.get("rel") or "").lower()
            href = clean_href(l.get("href"))
            if rel in ("alternate", "thumb") and href:
                preview = href
                break

    # Fallback: first image-like href
    if not preview and not full:
        for l in links:
            href = clean_href(l.get("href"))
            if looks_like_image(href):
                preview = preview or href
                full = full or href

    # Derive thumbnail from full
    if not preview and full:
        if "~orig" in full:
            preview = full.replace("~orig", "~thumb")
        elif "~large" in full:
            preview = full.replace("~large", "~thumb")
        else:
            preview = full

    return {"preview": preview, "full": full}


def item_to_card(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a NASA API item into a standardized card dict."""
    data = item.get("data") or []
    d0 = data[0] if data else {}
    title = d0.get("title") or d0.get("nasa_id") or "Untitled"
    desc = d0.get("description") or ""
    date_created = d0.get("date_created") or ""
    keywords = d0.get("keywords") or []
    center = d0.get("center") or ""
    nasa_id = d0.get("nasa_id") or ""
    secondary_creator = d0.get("secondary_creator") or ""

    links = item.get("links") or []
    chosen = choose_image_link(links, nasa_id=nasa_id)

    return {
        "title": title,
        "description": desc,
        "date": date_created,
        "keywords": keywords,
        "center": center,
        "nasa_id": nasa_id,
        "creator": secondary_creator,
        "preview": chosen.get("preview"),
        "full": chosen.get("full"),
    }


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{page_title}</title>
<style>
body {{ margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;background:#0f1720;color:#e6eef3 }}
.container {{ padding:1rem; max-width:1200px; margin:0 auto }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:1rem }}
.card {{ background:#0b1220; border-radius:10px; overflow:hidden; box-shadow:0 6px 18px rgba(2,6,23,0.6); border:1px solid rgba(255,255,255,0.03) }}
.thumb {{ width:100%; height:160px; object-fit:cover; display:block; background:#021021 }}
.card-body {{ padding:0.75rem }}
.title {{ font-weight:600; margin:0 0 0.5rem 0; font-size:1rem }}
.meta {{ font-size:0.8rem; color:#9aa7b2; margin-bottom:0.5rem }}
.desc {{ font-size:0.9rem; color:#cfe6f3; min-height:3.2rem; overflow:hidden }}
.footer {{ display:flex; gap:0.5rem; align-items:center; margin-top:0.75rem; flex-wrap:wrap }}
.badge {{ background:rgba(125,211,252,0.08); color:#7dd3fc; padding:0.2rem 0.45rem; border-radius:6px; font-size:0.75rem; border:1px solid rgba(125,211,252,0.06) }}
a.card-link {{ text-decoration:none; color:inherit; display:block }}
</style>
</head>
<body>
<header class="header"><h1>{page_title}</h1><div style="margin-left:auto;color:#9aa7b2">{item_count} items</div></header>
<main class="container">
{intro_html}
<div class="grid">
{cards_html}
</div>
{footer_html}
</main>
</body>
</html>"""

COMPACT_HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>{page_title}</title><style>
img{{max-width:100%}}.grid{{display:flex;flex-wrap:wrap;gap:6px}}.card{{width:180px}}
</style></head><body><h1>{page_title}</h1><div>{item_count} items</div><main><div class="grid">{cards_html}</div></main></body></html>"""


def build_card_html(card: dict, compact: bool = False) -> str:
    value = card.get("value", "")
    if "<html" in value.lower():
        # NASA already returned complete HTML markup — just return it as-is.
        return value

    """Build a single HTML card for a NASA image entry."""

    # --- Extract and sanitize text fields ---
    title = html.escape(card.get("title", "").strip(), quote=True)
    desc_raw = (card.get("description") or "").strip()

    if compact:
        desc = html.escape(re.sub(r"\s+", " ", desc_raw)[:120], quote=True)
    else:
        desc = html.escape(desc_raw, quote=True)

    # --- Meta info (date, center) ---
    meta_parts = []
    if card.get("date"):
        meta_parts.append(html.escape(card["date"], quote=True))
    if card.get("center"):
        meta_parts.append(html.escape(card["center"], quote=True))
    meta = " • ".join(meta_parts)

    # --- Keywords ---
    keywords = ", ".join(
        html.escape(k.strip(), quote=True) for k in (card.get("keywords") or [])
    )

    # --- Clean and extract URLs ---
    raw_preview = card.get("preview") or ""
    raw_full = card.get("full") or card.get("canonical") or raw_preview or ""

    extracted_preview = _extract_first_url(raw_preview)
    extracted_full = _extract_first_url(raw_full)

    # Fallbacks
    preview_url = extracted_preview or ""
    full_url = extracted_full or extracted_preview or "#"

    preview = html.escape(preview_url, quote=True)
    full = html.escape(full_url, quote=True)

    # --- Footer bits ---
    footer_bits = []
    nasa_id = html.escape(card.get("nasa_id") or "", quote=True)
    creator = html.escape(card.get("creator") or "", quote=True)

    if nasa_id:
        footer_bits.append(f'<span class="badge">{nasa_id}</span>')
    if creator:
        footer_bits.append(f'<span class="meta" title="Creator">{creator}</span>')
    if keywords:
        footer_bits.append(f'<span class="badge">{keywords}</span>')

    footer_html = " ".join(footer_bits)

    # --- Compact and full HTML variants ---
    if compact:
        # compact version
        return (
            f'<article class="card"><div class="card-body">'
            f'<a class="card-link" href="{full}" target="_blank" rel="noopener">'
            f'<img class="thumb" src="{preview}" alt="{title}"></a>'
            f'<h3 class="title">{title}</h3>'
            f'<div class="meta">{meta}</div>'
            f'<div class="desc">{desc}</div>'
            f'<div class="footer">{footer_html}</div>'
            f'</div></article>'
        )
    else:
        # detailed version
        return f"""
<article class="card">
  <div class="card-body">
    <a class="card-link" href="{full}" target="_blank" rel="noopener">
      <img class="thumb" src="{preview}" alt="{title}">
    </a>
    <h3 class="title">{title}</h3>
    <div class="meta">{meta}</div>
    <div class="desc">{desc}</div>
    <div class="footer">{footer_html}</div>
  </div>
</article>
""".strip()


def generate_gallery(json_obj: Dict[str, Any], page_title: str = "NASA Image Results", max_items: int = 8, compact: bool = False) -> str:
    """Generate full HTML gallery from NASA JSON."""
    coll = json_obj.get("collection") or json_obj
    items = coll.get("items", []) or []
    items = items[:max_items] if max_items > 0 else items

    cards = [item_to_card(it) for it in items]
    cards_html = "".join(build_card_html(c, compact=compact) for c in cards)
    intro_html = ''
    if coll.get("href"):
        intro_html = f'<p class="empty">Source: <a href="{html.escape(coll.get("href",""))}">{html.escape(coll.get("href",""))}</a></p>'
    footer_html = f'<p style="margin-top:1rem;color:#9aa7b2">Generated: {html.escape(coll.get("version",""))}</p>'

    template = COMPACT_HTML_TEMPLATE if compact else HTML_TEMPLATE
    return template.format(
        page_title=html.escape(page_title),
        item_count=len(cards),
        intro_html=intro_html,
        cards_html=cards_html,
        footer_html=footer_html
    )


# ---------------------------------------------------------------------------
# Programmatic API helpers
# ---------------------------------------------------------------------------

def generate_gallery_html_from_json_obj(json_obj: Dict[str, Any], title: Optional[str] = None, max_items: int = 10, compact: bool = False) -> str:
    page_title = title or "NASA Image Results"
    return generate_gallery(json_obj, page_title=page_title, max_items=max_items, compact=compact)


def generate_gallery_html_from_json_str(json_str: str, title: Optional[str] = None, max_items: int = 10, compact: bool = False) -> str:
    js = json.loads(json_str)
    return generate_gallery_html_from_json_obj(js, title=title, max_items=max_items, compact=compact)


def write_gallery_to_file_from_json_obj(json_obj: Dict[str, Any], out_path: str, title: Optional[str] = None, max_items: int = 10, compact: bool = False) -> str:
    html_out = generate_gallery_html_from_json_obj(json_obj, title=title, max_items=max_items, compact=compact)
    Path(out_path).write_text(html_out, encoding="utf-8")
    return out_path


__all__ = [
    "generate_gallery",
    "generate_gallery_html_from_json_obj",
    "generate_gallery_html_from_json_str",
    "write_gallery_to_file_from_json_obj",
]
