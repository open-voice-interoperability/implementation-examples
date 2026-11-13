#!/usr/bin/env python3
"""
Recall Sentinel — Cafeteria Ops Floor

A sentinel, not a specialist: it is never asked anything. It watches every
reply on the floor for ingredients it knows are recall-prone (lettuce,
jalapeños, cheese, mangoes, sprouts, chicken, pork, ...) and checks each
one against current food recalls (mcp/food_recalls_mcp.py): FDA's, live from
openFDA, and USDA FSIS's for meat and poultry, from a saved copy. It
speaks only when an ingredient on the menu is under an ongoing Class I or II
recall for a hazard the ingredient itself carries -- Salmonella, Listeria,
E. coli, Cyclospora, lead and the like -- reported in the last 90 days.

A recall counts only when it's about the ingredient: the ingredient is the
product itself (not one component of it -- "Fiesta Salad with Shrimp"
doesn't make shrimp the recalled ingredient, nor does a salad kit listing
cucumbers among its ingredients), or the recall reason names it ("jalapeños
may be contaminated"). Labeling-only recalls ("undeclared milk") and foreign-
object recalls (metal or glass in one manufactured product) are skipped:
they concern one packaged product, not an ingredient a kitchen buys.

Recalls name brands and lots; menus name ingredients. So an alert says an
active recall INVOLVES the ingredient and asks to check the supplier's brand
and lot -- never that the cafeteria's own stock is recalled.

FSIS's recall API blocks automated clients, so FSIS results come from a
copy of it saved from a browser (data/fsis_recalls.json); alerts that use it
say when that copy was saved. Each recall is reported once per conversation.

Getting the floor is the same request/decision handshake as the Allergy
Sentinel (OFP 1.1.1 sections 1.19-1.21): on a finding it holds the alert and
sends requestFloor -- `to` itself, reason "@issueDetected <description>"; the
convener answers grantFloor or revokeFloor ("declined: ..."); on grantFloor
it sends the alert, on a declined revoke it drops it.

Port: 8308
"""

import json
import html
import logging
import os
import re
import sys
import threading
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
import mcp_client
from openfloor.events import AcceptInviteEvent, RequestFloorEvent, UtteranceEvent
from openfloor.dialog_event import DialogEvent, Feature, TextFeature, Token
from openfloor.envelope import To

logger = logging.getLogger(__name__)

CONVENER_PORT = 8300

# Reason token that opens this agent's requestFloor reason (see the module
# docstring). Kept in sync by hand with convener.py's ISSUE_DETECTED_TOKEN
# -- agents and the convener share no code.
ISSUE_DETECTED_TOKEN = "@issueDetected"

# Ingredients this sentinel looks for. Chosen from what recalls actually
# name: FDA's (fresh produce, dairy, seafood, nuts, spices, flour) and
# FSIS's (meat and poultry, the last two lines).
WATCHED_INGREDIENTS = [
    "lettuce", "romaine", "iceberg", "spinach", "kale", "arugula", "cucumber", "tomato",
    "jalapeno", "serrano", "onion", "green onion", "scallion", "cilantro", "parsley", "basil",
    "celery", "carrot", "sprouts", "alfalfa", "broccoli", "cantaloupe", "melon", "watermelon",
    "mango", "peach", "strawberry", "blueberry", "raspberry", "avocado", "guacamole", "salsa",
    "pico de gallo", "cheese", "queso", "ricotta", "cottage cheese", "milk", "ice cream",
    "yogurt", "salmon", "tuna", "shrimp", "oyster", "clam", "crab", "tofu", "flour",
    "rice", "cinnamon", "cumin", "paprika", "peanut", "almond", "pistachio", "cashew",
    "walnut", "tahini", "hummus", "sesame", "pasta", "noodle", "corn",
    "chicken", "turkey", "beef", "ground beef", "pork", "lamb", "sausage", "ham", "bacon",
    "salami", "prosciutto", "pepperoni", "guanciale", "chorizo", "hot dog", "meatball", "jerky",
]

# A recall reason that's a hazard the ingredient itself carries: pathogens,
# toxins, heavy metals. Deliberately not foreign objects (metal, glass,
# plastic) -- those are a manufacturing fault in one product.
_HAZARD_RE = re.compile(
    r"salmonella|listeria|e\.?\s?coli|\bstec\b|cyclospora|hepatitis|botulin|clostridium|norovirus"
    r"|\blead\b|arsenic|cadmium|\bmold\b|aflatoxin|toxin|histamine|temperature abuse",
    re.IGNORECASE,
)
# In a product name, what follows these is a component, not the product:
# "Fiesta Salad with Shrimp", "Chips & Salsa", "Sprout Mix, containing
# Garlic, Onion and Alfalfa".
_COMPONENT_MARKER_RE = re.compile(r"\b(?:with|and|plus|w/|containing|contains)\b|&", re.IGNORECASE)
# ... and a term right after these is absent: "Guacamole Dip No Tomatoes".
_ABSENT_BEFORE_RE = re.compile(r"\b(?:no|without|free of|non)[\s-]+$", re.IGNORECASE)

# Another sentinel's alert ("Allergy alert: ... Grilled Chicken with Romaine
# ...") quotes dishes; reacting to it would re-flag what the menu already
# said. Sentinel alerts open with "<Kind> alert:".
_SENTINEL_ALERT_RE = re.compile(r"^\s*[A-Z][\w &/-]{0,30} alert:")

# Where a product's ingredient list starts, in an FDA product description.
_INGREDIENT_LIST_RE = re.compile(r"\bingredients?\b|;", re.IGNORECASE)

MAX_LOOKUPS_PER_REPLY = 8
LOOKUP_TIMEOUT_SECONDS = 10.0
MAX_RECALLS_PER_INGREDIENT = 2


def _fold(text: str) -> str:
    """Lowercase without accents: "Jalapeños" -> "jalapenos"."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def _ingredient_re(term: str) -> re.Pattern:
    if " " not in term and term.endswith("y"):
        body = re.escape(term[:-1]) + r"(?:y|ies)"
    else:
        body = re.escape(term) + r"(?:e?s)?"
    return re.compile(r"\b" + body + r"\b")


_WATCHED_RES = [(term, _ingredient_re(term)) for term in WATCHED_INGREDIENTS]


def find_watched_ingredients(text: str) -> dict:
    """{ingredient: the clause it appeared in} for each watched ingredient
    in text, longest names first so "cottage cheese" isn't also "cheese"."""
    found = {}
    folded = _fold(text)
    taken = []
    for term, regex in sorted(_WATCHED_RES, key=lambda tr: -len(tr[0])):
        for match in regex.finditer(folded):
            if any(start <= match.start() < end for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            if term not in found:
                found[term] = _clause_around(text, match.start(), match.end())
    return found


def _clause_around(text: str, start: int, end: int) -> str:
    """The comma/semicolon/line-delimited phrase around a match, with its
    line's label ("Tuesday: ...") when there is one."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start: line_end if line_end != -1 else len(text)]
    label_match = re.match(r"^\s*[-*•]?\s*([A-Za-z][\w &'/.-]{0,30}):\s+", line)
    label = label_match.group(1).strip() if label_match else ""
    offset = start - line_start
    pieces = re.split(r"([;,])", line)
    position = 0
    for piece in pieces:
        if position <= offset < position + len(piece) and piece not in (";", ","):
            clause = piece.strip(" .-*•")
            if label and clause.startswith(label + ":"):
                return clause
            return f"{label}: {clause}" if label else clause
        position += len(piece)
    return line.strip()


def relevant_recalls(term: str, recalls: list) -> list:
    """Recalls that are about the ingredient itself (it's the product, or
    the recall reason names it) and for a real hazard."""
    regex = _ingredient_re(term)
    kept = []
    for recall in recalls or []:
        reason = recall.get("reason") or ""
        if not _HAZARD_RE.search(reason):
            continue  # labeling-only, e.g. "undeclared milk"
        if regex.search(_fold(reason)):
            kept.append(recall)
            continue
        product_name = _fold(_INGREDIENT_LIST_RE.split(recall.get("product") or "", maxsplit=1)[0])
        head = _COMPONENT_MARKER_RE.split(product_name, maxsplit=1)[0]
        match = regex.search(head)
        if match and not _ABSENT_BEFORE_RE.search(head[:match.start()]):
            kept.append(recall)
    return kept


def _date(yyyymmdd: str) -> str:
    try:
        return datetime.strptime(yyyymmdd or "", "%Y%m%d").strftime("%b %d, %Y").replace(" 0", " ")
    except ValueError:
        return yyyymmdd or "date unknown"


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _most_serious_first(recall: dict):
    """Class I (most serious) before Class II, then most recent."""
    return (recall.get("classification") != "Class I", -int(recall.get("report_date") or 0))


def describe_recall(recall: dict) -> str:
    product_name = _INGREDIENT_LIST_RE.split(recall.get("product") or "", maxsplit=1)[0]
    firm = f" ({_trim(recall.get('firm'), 40)})" if recall.get("firm") else ""
    return (f"{recall.get('agency', 'FDA')} {recall.get('classification', 'recall')} recall {recall.get('recall_number', '')}, "
            f"reported {_date(recall.get('report_date'))}: {_trim(product_name, 70)}{firm} -- "
            f"{_trim(recall.get('reason'), 100)}")


# Each recalled ingredient heads its entry:
# 'Romaine / Lettuce -- on the menu in "Grilled Chicken with Romaine":'.
_ENTRY_INGREDIENTS_RE = re.compile(r'^\s*(.+?) -- on the menu in "', re.MULTILINE)


def _alert_ingredients(text: str) -> list:
    return [term for m in _ENTRY_INGREDIENTS_RE.finditer(text) for term in m.group(1).split(" / ")]


def _bold_terms_html(text: str, terms) -> str:
    """``text`` as HTML (escaped, line breaks kept) with every whole-word
    mention of ``terms`` -- the ingredients the alert is about, plural too --
    in bold. Sent alongside the plain text: the Planner shows this; the other
    agents read the text."""
    out = html.escape(text)
    words = sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)
    if words:
        alternatives = "|".join(re.escape(html.escape(w)) for w in words)
        pattern = re.compile(rf"(?<![\w-])((?:{alternatives})(?:e?s)?)(?![\w-])", re.IGNORECASE)
        out = pattern.sub(r"<b>\1</b>", out)
    return out.replace("\n", "<br>")


class RecallSentinelAgent(BaseStrategyAgent):
    AGENT_NAME = "Recall Sentinel"
    AGENT_PORT = 8308
    AGENT_SYNOPSIS = "Watches the floor and flags menu ingredients involved in active food recalls"
    AGENT_CAPABILITY_DETAIL = ("Checks recall-prone ingredients named on the floor against ongoing FDA and USDA FSIS "
                               "food recalls and flags any that are involved in one.")
    WORKING_LABEL = "checking FDA food recalls"
    AGENT_KEYPHRASES = []

    REQUEST_RETRY_SECONDS = 60

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        # conv_id -> {"checked": set of ingredients, "reported": set of recall numbers}
        self._watch: dict[str, dict] = {}
        # conv_id -> {"alerts": [text, ...], "summaries": [str], "requested_at": float}
        self._pending: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # OpenFloor handlers
    # ------------------------------------------------------------------

    def _handle_invite(self, event, in_envelope, out_envelope) -> None:
        self._floor_granted = False
        out_envelope.events.append(AcceptInviteEvent())
        self._say(out_envelope, "Recall Sentinel on watch. I'll speak up only if an ingredient on the menu "
                                "is involved in an active food recall.")

    def bot_on_utterance(self, event, in_envelope, out_envelope) -> None:
        try:
            speaker_uri = self._get_event_speaker_uri(event)
            if speaker_uri and self._normalize_endpoint_id(speaker_uri) == self._normalize_endpoint_id(self.speakerUri):
                return
            if self._speaker_kind(speaker_uri, in_envelope) != "agent":
                return  # the request itself, or the convener relaying it
            text = self._extract_utterance_text(event)
            if not text or _SENTINEL_ALERT_RE.match(text):
                return  # nothing said, or another sentinel's alert quoting the menu
            conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
            alert, summary = self._check(conv_id, text)
            if alert:
                self._hold_and_request(conv_id, alert, summary, out_envelope)
        except Exception:
            logger.exception("[RECALL] error while checking utterance")

    def _handle_grant_floor(self, event, in_envelope, out_envelope) -> None:
        super()._handle_grant_floor(event, in_envelope, out_envelope)
        conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
        with self._lock:
            pending = self._pending.pop(conv_id, None)
        if pending and pending["alerts"]:
            logger.info("[RECALL] floor granted in %s; explaining %d finding(s)", conv_id, len(pending["alerts"]))
            self._say(out_envelope, "\n".join(pending["alerts"]))

    def _handle_revoke_floor(self, event, in_envelope, out_envelope) -> None:
        """Only a "declined" revoke drops held findings -- see the Allergy
        Sentinel's identical handling for why other revokes mustn't."""
        super()._handle_revoke_floor(event, in_envelope, out_envelope)
        reason = (getattr(event, "reason", None) or "").strip()
        if not reason.lower().startswith("declined"):
            return
        conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
        with self._lock:
            pending = self._pending.pop(conv_id, None)
        if pending and pending["alerts"]:
            logger.info("[RECALL] floor request turned down in %s (%s); dropping %d finding(s)",
                        conv_id, reason, len(pending["alerts"]))

    # ------------------------------------------------------------------
    # Checking
    # ------------------------------------------------------------------

    def _check(self, conv_id: str, text: str):
        """(alert text, short summary) for recalls involving ingredients in
        text that haven't been reported in this conversation, or ("", "")."""
        found = find_watched_ingredients(text)
        with self._lock:
            watch = self._watch.setdefault(conv_id, {"checked": set(), "reported": set()})
            new_terms = [t for t in found if t not in watch["checked"]][:MAX_LOOKUPS_PER_REPLY]
            watch["checked"].update(new_terms)
        if not new_terms:
            return "", ""

        # Both agencies for every ingredient, all at once.
        tools = ("search_food_recalls", "search_fsis_recalls")
        raw = mcp_client.call_tools_parallel_sync(
            [("food_recalls", tool, {"term": t}) for t in new_terms for tool in tools],
            timeout=LOOKUP_TIMEOUT_SECONDS,
        )
        # Group by the dish each ingredient came from, so "iceberg lettuce"
        # is one entry, not two listing the same supplier's recalls.
        by_clause: dict[str, dict] = {}
        snapshot_dates = set()
        for i, term in enumerate(new_terms):
            results = []
            for tool, result in zip(tools, raw[i * len(tools):(i + 1) * len(tools)]):
                try:
                    data = json.loads(result) if result else {}
                except ValueError:
                    data = {}
                if data.get("error"):
                    logger.warning("[RECALL] %s failed for %s: %s", tool, term, data["error"])
                    continue
                results.extend(data.get("results") or [])
            with self._lock:
                fresh = []
                for r in relevant_recalls(term, results):
                    if r.get("recall_number") not in watch["reported"]:
                        watch["reported"].add(r.get("recall_number"))
                        fresh.append(r)
            snapshot_dates.update(r["snapshot_saved"] for r in fresh if r.get("snapshot_saved"))
            if fresh:
                entry = by_clause.setdefault(found[term], {"terms": [], "by_term": {}})
                entry["terms"].append(term)
                entry["by_term"][term] = sorted(fresh, key=_most_serious_first)

        lines, terms_hit = [], []
        for clause, entry in by_clause.items():
            terms_hit.extend(entry["terms"])
            # Each ingredient's most serious recall first, so one ingredient's
            # many recalls can't hide another's ("tacos with lettuce and pico
            # de gallo" shows a lettuce recall and a pico de gallo recall).
            shown = [entry["by_term"][t][0] for t in entry["terms"]]
            rest = sorted((r for t in entry["terms"] for r in entry["by_term"][t][1:]), key=_most_serious_first)
            shown += rest[:max(0, MAX_RECALLS_PER_INGREDIENT - len(shown))]
            total = sum(len(v) for v in entry["by_term"].values())
            lines.append(f"{' / '.join(t.capitalize() for t in entry['terms'])} -- on the menu in \"{_trim(clause, 70)}\":")
            lines.extend(f"  {describe_recall(r)}" for r in shown)
            if total > len(shown):
                lines[-1] += f" (+{total - len(shown)} more)"

        if not lines:
            return "", ""
        agencies = sorted({r.get("agency", "FDA") for e in by_clause.values() for rs in e["by_term"].values() for r in rs})
        who = {("FDA",): "FDA", ("FSIS",): "USDA FSIS"}.get(tuple(agencies), "FDA and USDA FSIS")
        note = (f" (FSIS data is from a copy saved {', '.join(sorted(snapshot_dates))}; a recall listed there may since have closed.)"
                if snapshot_dates else "")
        alert = (f"Food recall alert: active {who} recalls involve ingredients on this menu. "
                 f"Check your supplier's brand and lot before ordering or serving.{note}\n" + "\n".join(lines))
        summary = f"active {who} recalls involve " + ", ".join(terms_hit)
        return alert, summary

    def _hold_and_request(self, conv_id: str, alert: str, summary: str, out_envelope) -> None:
        with self._lock:
            pending = self._pending.setdefault(conv_id, {"alerts": [], "requested_at": 0.0})
            pending["alerts"].append(alert)
            if pending["requested_at"] and time.time() - pending["requested_at"] < self.REQUEST_RETRY_SECONDS:
                logger.info("[RECALL] finding held; floor request already pending in %s", conv_id)
                return
            pending["requested_at"] = time.time()
        reason = f"{ISSUE_DETECTED_TOKEN} {summary}"
        logger.info("[RECALL] requesting the floor in %s (%s)", conv_id, reason)
        out_envelope.events.append(RequestFloorEvent(
            to=To(speakerUri=self.speakerUri, serviceUrl=self.serviceUrl),
            reason=reason,
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _speaker_kind(self, speaker_uri: str, in_envelope) -> str:
        """"human" | "convener" | "agent": the floor manager lists every
        agent as a conversant and never the human."""
        try:
            if urlparse(speaker_uri or "").port == CONVENER_PORT:
                return "convener"
        except ValueError:
            pass
        conversants = getattr(getattr(in_envelope, "conversation", None), "conversants", None) or []
        target = self._normalize_endpoint_id(speaker_uri)
        for conversant in conversants:
            ident = self._get_attr(conversant, "identification", {}) or {}
            for key in ("speakerUri", "serviceUrl"):
                if target and self._normalize_endpoint_id(self._get_attr(ident, key, "") or "") == target:
                    return "agent"
        return "human"

    def _say(self, out_envelope, text: str) -> None:
        features = {"text": TextFeature(values=[text])}
        terms = _alert_ingredients(text)
        if terms:
            features["html"] = Feature(mimeType="text/html", tokens=[Token(value=_bold_terms_html(text, terms))])
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features=features,
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))


def main() -> None:
    agent = RecallSentinelAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(RecallSentinelAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
