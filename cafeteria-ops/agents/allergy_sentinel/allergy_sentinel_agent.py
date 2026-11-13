#!/usr/bin/env python3
"""
Allergy Sentinel — Cafeteria Ops Floor

A sentinel, not a specialist: it is never asked anything. It watches every
utterance on the floor and speaks up only when a dish or ingredient that a
specialist proposed (a) breaks an allergy restriction stated in the request
("nut-free", "no shellfish", "gluten-free", "allergic to sesame"), or (b)
contains one of the four most dangerous allergens -- peanuts, tree nuts,
shellfish, sesame -- even when no restriction was stated. Otherwise it stays
silent, the same contract as Verity's hallucination sentinel.

Detection is a fixed ingredient keyword map over the nine major US allergens
(milk, egg, fish, shellfish, tree nuts, peanuts, wheat/gluten, soy, sesame)
-- no LLM, so it's instant, free and predictable. It can miss a dish whose
allergen-bearing ingredient isn't named anywhere in the conversation; the
Recipe & Portion and Shopping List replies spell ingredients out, which is
where most of its findings come from.

Each finding is reported once per conversation, so it doesn't repeat itself
as later specialists mention the same item.

Getting the floor is a request/decision handshake (OFP 1.1.1 sections 1.19
-1.21), with nothing sentinel-specific in the convener:

1. On finding an issue, the sentinel holds the alert back and replies with
   only a requestFloor -- `to` itself (who the floor is for), with a reason
   that starts with the @issueDetected token and then describes it:
   "@issueDetected these items conflict with the request (no tree nuts)".
2. The floor manager delegates the request to the convener, which reads the
   reason and answers grantFloor (an issue worth interrupting for) or
   revokeFloor (it disagrees). With no convener, the floor manager grants it.
3. On grantFloor, the sentinel sends the held alert(s) as one utterance; the
   convener then revokes its floor. A revokeFloor whose reason starts with
   "declined" means the convener turned the request down, and the held
   alerts are dropped; any other revoke (e.g. the routine one after it has
   spoken) leaves a still-waiting request alone.

Port: 8307
"""

import html
import logging
import os
import re
import sys
import threading
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.base_strategy_agent import BaseStrategyAgent, make_flask_app
from openfloor.events import AcceptInviteEvent, RequestFloorEvent, UtteranceEvent
from openfloor.dialog_event import DialogEvent, Feature, TextFeature, Token
from openfloor.envelope import To

logger = logging.getLogger(__name__)

CONVENER_PORT = 8300

ALLERGEN_LABELS = {
    "peanut": "Peanuts",
    "tree_nut": "Tree nuts",
    "shellfish": "Shellfish",
    "sesame": "Sesame",
    "fish": "Fish",
    "milk": "Milk/dairy",
    "egg": "Eggs",
    "wheat": "Wheat/gluten",
    "soy": "Soy",
}

# Reason token that opens this agent's requestFloor reason, so the convener
# can recognize an issue report exactly rather than from its wording. Same
# style as the spec's own "@" reason tokens (none are defined yet for
# requestFloor). Kept in sync by hand with convener.py's ISSUE_DETECTED_TOKEN
# -- agents and the convener share no code.
ISSUE_DETECTED_TOKEN = "@issueDetected"

# Another sentinel's alert ("Food recall alert: ... on the menu in "...
# Pesto ..."") quotes dishes; reacting to it would re-flag what the menu
# already said. Sentinel alerts open with "<Kind> alert:".
_SENTINEL_ALERT_RE = re.compile(r"^\s*[A-Z][\w &/-]{0,30} alert:")

# Flagged on every menu, restriction or not.
SEVERE_ALLERGENS = ("peanut", "tree_nut", "shellfish", "sesame")

# Ingredient (or near-certain dish) keywords -> allergen. Matched as whole
# words, case-insensitive. Coconut is deliberately absent (FDA no longer
# treats it as a tree nut), and so is "nutmeg".
ALLERGEN_KEYWORDS = {
    "peanut": [
        r"peanuts?", r"peanut butter", r"groundnuts?", r"satay", r"kung pao", r"gado[- ]gado",
    ],
    "tree_nut": [
        r"almonds?", r"walnuts?", r"pecans?", r"cashews?", r"pistachios?", r"hazelnuts?",
        r"macadamias?", r"brazil nuts?", r"pine nuts?", r"pignoli", r"chestnuts?", r"nuts",
        r"pesto", r"praline", r"marzipan", r"frangipane", r"nutella", r"baklava", r"romesco",
        r"gianduja", r"nougat",
    ],
    "shellfish": [
        r"shrimps?", r"prawns?", r"crabs?", r"crabmeat", r"lobsters?", r"crawfish", r"crayfish",
        r"langoustines?", r"scampi", r"clams?", r"mussels?", r"oysters?", r"scallops?",
        r"squid", r"calamari", r"octopus", r"shellfish", r"seafood",
    ],
    "sesame": [
        r"sesame", r"tahini", r"hummus", r"houmous", r"halva", r"halvah", r"za'?atar",
        r"baba ganoush", r"baba ghanoush", r"benne", r"furikake", r"gomasio",
    ],
    "fish": [
        r"fish", r"salmon", r"tuna", r"cod", r"tilapia", r"halibut", r"trout", r"haddock",
        r"anchov(?:y|ies)", r"sardines?", r"mackerel", r"sea bass", r"snapper", r"mahi[- ]mahi",
        r"swordfish", r"catfish", r"pollock", r"fish sauce", r"worcestershire",
    ],
    "milk": [
        r"milk", r"cheeses?", r"feta", r"mozzarella", r"parmesan", r"parmigiano", r"cheddar",
        r"ricotta", r"paneer", r"queso", r"halloumi", r"butter", r"cream", r"yogh?urt",
        r"tzatziki", r"ghee", r"whey", r"casein", r"alfredo", r"b[eé]chamel", r"custard",
        r"raita", r"mascarpone", r"cr[eè]me fra[iî]che", r"sour cream",
    ],
    "egg": [
        r"eggs?", r"mayo", r"mayonnaise", r"aioli", r"meringue", r"custard", r"quiche",
        r"frittata", r"omelett?e", r"hollandaise", r"carbonara",
    ],
    "wheat": [
        r"wheat", r"flour", r"breads?", r"breadcrumbs?", r"panko", r"pasta", r"spaghetti",
        r"penne", r"linguine", r"fettuccine", r"lasagna", r"orzo", r"couscous", r"bulgur",
        r"farro", r"seitan", r"pitas?", r"naan", r"tortillas?", r"noodles?", r"croutons?",
        r"semolina", r"spelt", r"barley", r"rye", r"malt", r"buns?", r"wraps?", r"pizza",
        r"dumplings?", r"soy sauce", r"teriyaki",
    ],
    "soy": [
        r"soy", r"soya", r"soybeans?", r"tofu", r"edamame", r"tempeh", r"miso", r"soy sauce",
        r"tamari", r"shoyu", r"teriyaki",
    ],
}

# A keyword right after one of these is a substitute, not the allergen:
# "nut-free pesto", "dairy-free cheese", "no peanuts", "vegan butter".
_NEGATED_BEFORE = re.compile(
    r"(?:\b[\w']+[- ]free|\bvegan|\bplant[- ]based|\bno|\bwithout|\bfree of|\bnon[- ]dairy|\bsubstitute for)\s+(?:[\w']+\s+)?$",
    re.IGNORECASE,
)

# Keyword-specific exceptions where the word isn't the allergen.
_FALSE_POSITIVES = {
    "milk": re.compile(r"\b(?:coconut|almond|oat|soy|rice|cashew)\s+milk\b|\bmilk thistle\b", re.I),
    "butter": re.compile(r"\b(?:peanut|almond|cashew|apple|nut|seed|cocoa|shea|sunflower)\s+butter\b|\bbutter(?:nut|milk)?\s*(?:squash|lettuce|beans?)\b", re.I),
    "cream": re.compile(r"\bcream of tartar\b|\bcoconut cream\b|\bice cream\b(?=.*\bdairy[- ]free\b)", re.I),
    "tortilla": re.compile(r"\bcorn tortillas?\b", re.I),
    "noodle": re.compile(r"\b(?:rice|glass|cellophane|soba|kelp|zucchini)\s+noodles?\b", re.I),
    "nuts": re.compile(r"\b(?:coco|dough|pea|wing)nuts\b", re.I),
}

_KEYWORD_RES = {
    allergen: re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)
    for allergen, words in ALLERGEN_KEYWORDS.items()
}

# How a request names each allergen, for reading restrictions.
_RESTRICTION_TERMS = {
    "peanut": r"peanuts?",
    "tree_nut": r"tree[- ]nuts?",
    "nuts": r"nuts?",            # "nut-free" covers peanuts AND tree nuts
    "shellfish": r"shellfish|crustaceans?|shrimp",
    "sesame": r"sesame",
    "fish": r"fish",
    "milk": r"dairy|milk|lactose",
    "egg": r"eggs?",
    "wheat": r"gluten|wheat",
    "soy": r"soy|soya",
}
_RESTRICTION_PATTERNS = [
    r"\b(?:{t})[- ]free\b",
    r"\bno\s+(?:{t})\b",
    r"\bwithout\s+(?:{t})\b",
    r"\bavoid(?:ing|s)?\s+(?:{t})\b",
    r"\bfree of\s+(?:{t})\b",
    r"\b(?:{t})\s+allerg(?:y|ies|ic)\b",
    r"\ballergic to\s+(?:{t})\b",
]


def parse_restrictions(text: str) -> set:
    """Allergen keys the request rules out ("nut-free" -> peanut + tree_nut)."""
    found = set()
    for key, term in _RESTRICTION_TERMS.items():
        for pattern in _RESTRICTION_PATTERNS:
            if re.search(pattern.format(t=term), text, re.IGNORECASE):
                if key == "nuts":
                    found.update(("peanut", "tree_nut"))
                else:
                    found.add(key)
                break
    if re.search(r"\bc(?:o)?eliac\b", text, re.IGNORECASE):
        found.add("wheat")
    return found


def _is_false_positive(match: re.Match, line: str) -> bool:
    word = match.group(0).lower()
    if _NEGATED_BEFORE.search(line[: match.start()]):
        return True
    for stem, pattern in _FALSE_POSITIVES.items():
        if word.startswith(stem):
            for fp in pattern.finditer(line):
                if fp.start() <= match.start() < fp.end():
                    return True
    return False


_LINE_LABEL = re.compile(r"^([A-Za-z][\w &'/.-]{0,30}):\s+")


def find_allergens(text: str) -> list:
    """[(allergen, keyword, item)] for every allergen keyword in text.

    item is the dish or ingredient phrase the keyword appeared in: the
    comma/semicolon-separated clause, prefixed with its line's label when
    there is one ("Friday: grilled salmon with lemon butter"). Specialists
    put one day, dish or ingredient per line, so that's the natural unit to
    report back."""
    findings = []
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = raw_line.strip(" \t-*•·")
        if not line:
            continue
        label_match = _LINE_LABEL.match(line)
        label = label_match.group(1).strip() if label_match else ""
        body = line[label_match.end():] if label_match else line
        for clause in re.split(r"\s*[;,]\s*", body):
            clause = clause.strip(" .")
            if not clause:
                continue
            item = f"{label}: {clause}" if label else clause
            for allergen, regex in _KEYWORD_RES.items():
                for match in regex.finditer(clause):
                    if _is_false_positive(match, clause):
                        continue
                    findings.append((allergen, match.group(0).lower(), item))
                    break  # one hit per allergen per item is enough
    return findings


def _short(line: str, limit: int = 90) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


# Each flagged item ends with its ingredient in parentheses:
# "Shellfish: Thursday: Shrimp tacos (shrimp); Friday: ... (crab)".
_ITEM_INGREDIENT_RE = re.compile(r"\(([^()\n]{1,40})\)(?=;|\s*$)", re.MULTILINE)


def _alert_ingredients(text: str) -> list:
    return [m.group(1) for m in _ITEM_INGREDIENT_RE.finditer(text)]


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


class AllergySentinelAgent(BaseStrategyAgent):
    AGENT_NAME = "Allergy Sentinel"
    AGENT_PORT = 8307
    AGENT_SYNOPSIS = "Watches the floor and flags dishes with allergens the request rules out, or severe allergens"
    AGENT_CAPABILITY_DETAIL = ("Flags menu items that break a stated allergy restriction, and any dish "
                               "containing peanuts, tree nuts, shellfish or sesame.")
    WORKING_LABEL = "checking for allergens"
    AGENT_KEYPHRASES = []
    MAX_ITEMS_PER_ALLERGEN = 6

    def __init__(self):
        super().__init__()
        # conv_id -> {"restrictions": set, "reported": set of (allergen, item key)}
        self._watch: dict[str, dict] = {}
        self._watch_lock = threading.Lock()
        # conv_id -> {"alerts": [text, ...], "requested_at": float}: alerts
        # held back until the floor is granted (see the module docstring).
        self._pending: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # OpenFloor handlers
    # ------------------------------------------------------------------

    def _handle_invite(self, event, in_envelope, out_envelope) -> None:
        self._floor_granted = False  # joining doesn't mean holding the floor
        out_envelope.events.append(AcceptInviteEvent())
        self._say(out_envelope, "Allergy Sentinel on watch. I'll speak up only if a proposed dish breaks "
                                "an allergy restriction in your request, or contains peanuts, tree nuts, "
                                "shellfish or sesame.")

    def bot_on_utterance(self, event, in_envelope, out_envelope) -> None:
        """Watch, never answer: no floor-holder, scope gate or LLM -- just
        decide whether there's anything to say, and ask for the floor first
        when it doesn't hold it (see the module docstring)."""
        try:
            speaker_uri = self._get_event_speaker_uri(event)
            if speaker_uri and self._normalize_endpoint_id(speaker_uri) == self._normalize_endpoint_id(self.speakerUri):
                return
            text = self._extract_utterance_text(event)
            if not text or _SENTINEL_ALERT_RE.match(text):
                return  # nothing said, or another sentinel's alert quoting the menu
            conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
            kind = self._speaker_kind(speaker_uri, in_envelope)

            with self._watch_lock:
                watch = self._watch.setdefault(conv_id, {"restrictions": set(), "reported": set()})
                if kind in ("human", "convener"):
                    # The request (or the convener relaying it) is where
                    # restrictions are stated; its own wording is never
                    # flagged -- "no shrimp" isn't a shrimp dish.
                    watch["restrictions"] |= parse_restrictions(text)
                    return
                alert = self._build_alert(text, watch)
            if alert:
                self._hold_and_request(conv_id, alert, out_envelope)
        except Exception:
            logger.exception("[ALLERGY] error while checking utterance")

    # How long to wait on an unanswered floor request before asking again.
    REQUEST_RETRY_SECONDS = 60

    def _hold_and_request(self, conv_id: str, alert: str, out_envelope) -> None:
        """Hold the alert; ask for the floor unless a request is already out
        (findings that arrive meanwhile join the same alert)."""
        with self._watch_lock:
            pending = self._pending.setdefault(conv_id, {"alerts": [], "requested_at": 0.0})
            pending["alerts"].append(alert)
            waiting = pending["requested_at"] and time.time() - pending["requested_at"] < self.REQUEST_RETRY_SECONDS
            if waiting:
                logger.info("[ALLERGY] finding held; floor request already pending in %s", conv_id)
                return
            pending["requested_at"] = time.time()
        reason = f"{ISSUE_DETECTED_TOKEN} " + re.sub(r"^Allergy alert:\s*", "", alert.splitlines()[0]).rstrip(".")
        logger.info("[ALLERGY] requesting the floor in %s (%s)", conv_id, reason)
        out_envelope.events.append(RequestFloorEvent(
            to=To(speakerUri=self.speakerUri, serviceUrl=self.serviceUrl),
            reason=reason,
        ))

    def _handle_grant_floor(self, event, in_envelope, out_envelope) -> None:
        super()._handle_grant_floor(event, in_envelope, out_envelope)
        conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
        with self._watch_lock:
            pending = self._pending.pop(conv_id, None)
        if pending and pending["alerts"]:
            logger.info("[ALLERGY] floor granted in %s; explaining %d finding(s)", conv_id, len(pending["alerts"]))
            self._say(out_envelope, "\n".join(pending["alerts"]))

    def _handle_revoke_floor(self, event, in_envelope, out_envelope) -> None:
        """Only a revoke that says it's turning the request down (the
        convener's reason starts with "declined") drops the held findings.
        Other revokes -- the routine one after this agent has had its say,
        or the floor manager's one-reply cap -- can arrive while a newer
        request is still waiting for its answer, and must not cancel it."""
        super()._handle_revoke_floor(event, in_envelope, out_envelope)
        conv_id = getattr(getattr(in_envelope, "conversation", None), "id", "") or ""
        reason = (getattr(event, "reason", None) or "").strip()
        if not reason.lower().startswith("declined"):
            return
        with self._watch_lock:
            pending = self._pending.pop(conv_id, None)
        if pending and pending["alerts"]:
            logger.info("[ALLERGY] floor request turned down in %s (%s); dropping %d finding(s)",
                        conv_id, reason, len(pending["alerts"]))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _speaker_kind(self, speaker_uri: str, in_envelope) -> str:
        """"human" | "convener" | "agent". The floor manager lists every
        agent as a conversant and never the human, so an unlisted speaker is
        the person making the request."""
        if self._port_of(speaker_uri) == CONVENER_PORT:
            return "convener"
        conversants = getattr(getattr(in_envelope, "conversation", None), "conversants", None) or []
        target = self._normalize_endpoint_id(speaker_uri)
        for conversant in conversants:
            ident = self._get_attr(conversant, "identification", {}) or {}
            for key in ("speakerUri", "serviceUrl"):
                if target and self._normalize_endpoint_id(self._get_attr(ident, key, "") or "") == target:
                    return "agent"
        return "human"

    @staticmethod
    def _port_of(uri: str):
        try:
            return urlparse(uri or "").port
        except ValueError:
            return None

    def _build_alert(self, text: str, watch: dict) -> str:
        restrictions = watch["restrictions"]
        conflicts: dict[str, list] = {}
        severe: dict[str, list] = {}
        named = set()  # (allergen, keyword) already listed in this alert
        for allergen, keyword, line in find_allergens(text):
            if allergen in restrictions:
                bucket = conflicts
            elif allergen in SEVERE_ALLERGENS:
                bucket = severe
            else:
                continue
            key = (allergen, _short(line, 60).lower())
            if key in watch["reported"]:
                continue
            watch["reported"].add(key)
            # A recipe names its pesto in the title, the ingredient list and
            # the steps -- list it once.
            if (allergen, keyword) in named:
                continue
            named.add((allergen, keyword))
            items = bucket.setdefault(allergen, [])
            if len(items) < self.MAX_ITEMS_PER_ALLERGEN:
                items.append(f"{_short(line)} ({keyword})")

        if not conflicts and not severe:
            return ""
        parts = []
        if conflicts:
            ruled_out = ", ".join(ALLERGEN_LABELS[a].lower() for a in sorted(restrictions))
            parts.append(f"Allergy alert: these items conflict with the request (no {ruled_out}).")
            parts.extend(self._lines(conflicts))
        if severe:
            parts.append("Severe allergens to label or swap:" if conflicts else
                         "Allergy alert: these items contain severe allergens; label them or offer a swap.")
            parts.extend(self._lines(severe))
        return "\n".join(parts)

    @staticmethod
    def _lines(groups: dict) -> list:
        order = list(ALLERGEN_LABELS)
        return [f"{ALLERGEN_LABELS[a]}: " + "; ".join(items) for a, items in sorted(groups.items(), key=lambda kv: order.index(kv[0]))]

    def _say(self, out_envelope, text: str) -> None:
        features = {"text": TextFeature(values=[text])}
        terms = _alert_ingredients(text)
        if terms:
            # The allergen group label ("Peanuts:") is a heading, not a
            # mention of the ingredient -- left plain, like "Tree nuts:".
            lines = []
            for line in text.split("\n"):
                label, sep, rest = line.partition(": ")
                if sep and label in ALLERGEN_LABELS.values():
                    lines.append(html.escape(label + sep) + _bold_terms_html(rest, terms))
                else:
                    lines.append(_bold_terms_html(line, terms))
            features["html"] = Feature(mimeType="text/html", tokens=[Token(value="<br>".join(lines))])
        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features=features,
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))


def main() -> None:
    agent = AllergySentinelAgent()
    app = make_flask_app(agent)
    port = int(os.getenv("PORT", str(AllergySentinelAgent.AGENT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
