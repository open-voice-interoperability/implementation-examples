#!/usr/bin/env python3
"""
Startup Strategy Convener — OFP Floor Convener

Routes startup strategy queries across 7 specialist agents using
keyword-based intent classification (SLM-ready, no external model required).
"""

import functools
import json
import logging
import os
import re
import sys

from flask import Flask, Response, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import llm_utils
from agents.base_strategy_agent import load_manifest_from_config
from openfloor.envelope import Envelope, Conversation, Sender, Schema, To, Parameters
from openfloor.events import (
    UtteranceEvent,
    PublishManifestsEvent,
    GrantFloorEvent,
    RevokeFloorEvent,
    InviteEvent,
)
from openfloor.dialog_event import DialogEvent, TextFeature, Token

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")

# convener makes no outbound HTTP calls of its own -- web-floor's floor
# manager (floor_router.py) owns all conversant/floor state and is the sole
# thing that ever calls a specialist's URL. convener is a pure decision
# function the floor manager calls (see handle_envelope_json's "roundHistory"
# branch and _decide_delegated_utterance below).


def _field(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    if hasattr(obj, "get"):
        try:
            return obj.get(key, default)
        except Exception:
            pass
    return getattr(obj, key, default)


AGENTS = {
    "market": {"name": "Market Validator", "port": 8200, "url": "http://127.0.0.1:8200/", "aliases": ["market", "tam", "sam", "som", "market sizing", "market validator"]},
    "competitive": {"name": "Competitive Intelligence", "port": 8201, "url": "http://127.0.0.1:8201/", "aliases": ["competitive", "competitor", "competition", "competitive intelligence"]},
    "model": {"name": "Business Model Designer", "port": 8202, "url": "http://127.0.0.1:8202/", "aliases": ["model", "business model", "business model designer"]},
    "risk": {"name": "Risk Identifier", "port": 8203, "url": "http://127.0.0.1:8203/", "aliases": ["risk", "risk identifier", "risk identification"]},
    "funding": {"name": "Funding Strategist", "port": 8204, "url": "http://127.0.0.1:8204/", "aliases": ["funding", "funding strategist", "raise", "fundraising"]},
    "workforce": {"name": "Workforce Strategist", "port": 8205, "url": "http://127.0.0.1:8205/", "aliases": ["workforce", "workforce strategist", "team", "hiring"]},
    "skeptic": {"name": "Devil's Advocate", "port": 8206, "url": "http://127.0.0.1:8206/", "aliases": ["skeptic", "devil's advocate", "skeptic", "devil", "challenge"]},
    "strategy": {"name": "Strategy Synthesizer", "port": 8207, "url": "http://127.0.0.1:8207/", "aliases": ["strategy", "strategy synthesizer", "synthesis", "summary"]}
}

FULL_ANALYSIS_SEQUENCE = [
    "market", "competitive", "model", "risk", "funding", "workforce", "skeptic", "strategy"
]

INTENT_PATTERNS = {
    "market": r"\b(market|tam|sam|som|demand|size|addressable|growth|opportunity|geography)\b",
    "competitive": r"\b(competitor|competition|rival|patent|ip|differentiat|moat|landscape|players)\b",
    "model": r"\b(business model|revenue|pricing|monetize|saas|subscription|marketplace|unit economics|cac|ltv)\b",
    "risk": r"\b(risk|regulatory|compliance|legal|threat|danger|failure|challenge|concern)\b",
    "funding": r"\b(funding|investment|raise|venture|capital|seed|series|investor|valuation|runway|equity)\b",
    "workforce": r"\b(hire|hiring|team|talent|workforce|salary|wages|people|headcount|recruit)\b",
    "skeptic": r"\b(challenge|pushback|critique|flaw|weakness|objection|devil|skeptic|bear case)\b",
    "strategy": r"\b(summary|synthesize|brief|overall|conclusion|verdict|next steps|action plan|recommend)\b"
}

SPECIALIST_SWEEP_PATTERNS = [
    r"\b(check|ask|consult|run)\b.{0,40}\b(specialists|experts|agents)\b",
    r"\b(specialists|experts|agents)\b.{0,40}\b(check|review|evaluate|assess)\b",
    r"\b(evaluate|assess|review|analy[sz]e)\b.{0,40}\b(viability|business idea|startup idea|concept)\b",
    r"\b(one by one|in turn|round robin|sequentially)\b",
]

INVITE_SPECIALISTS_PATTERNS = [
    r"\b(invite|bring in|add)\b.{0,40}\b(all )?(specialists|experts|agents)\b",
    r"\b(invite)\b.{0,40}\b(market|competitive|model|risk|funding|workforce|skeptic|strategy)\b",
]

MAX_RESPONSE_WORDS = 50


def detect_addressed_agent(text: str) -> str | None:
    """Detect if the user is DIRECTLY addressing a specific agent.

    Only matches when the agent name/alias appears at the start of the utterance
    (optionally followed by punctuation) OR after clear address phrases like
    "ask the ...", "tell the ...", "hey ...".  Single common words (market,
    risk, model …) are intentionally NOT matched mid-sentence to avoid false
    positives from startup descriptions that naturally contain those words.

    Examples that match:
      "Market Validator, what's the TAM?" -> "market"
      "Ask the skeptic about risks" -> "skeptic"
      "Competitive intelligence on this?" -> "competitive"

    Examples that do NOT match (word appears in concept, not as address):
      "evaluate a fish market and bowling alley" -> None
      "what are the risks of this model?" -> None
    """
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Pattern 1: alias at the very start, optionally followed by punctuation/space
    for agent_key, agent_info in AGENTS.items():
        for alias in agent_info.get("aliases", []):
            pattern = rf"^{re.escape(alias.lower())}[\s,:.!?]"
            if re.match(pattern, text_lower):
                logger.info(f"Detected addressed agent (start): {agent_key} (alias: {alias})")
                return agent_key

    # Pattern 2: explicit address phrases followed by alias
    address_prefixes = r"(?:ask|tell|hey|@|attention|attn)\s+(?:the\s+)?"
    for agent_key, agent_info in AGENTS.items():
        for alias in agent_info.get("aliases", []):
            pattern = rf"\b{address_prefixes}{re.escape(alias.lower())}\b"
            if re.search(pattern, text_lower):
                logger.info(f"Detected addressed agent (explicit): {agent_key} (alias: {alias})")
                return agent_key

    return None


def _limit_words(text: str, max_words: int = MAX_RESPONSE_WORDS) -> str:
    if not text:
        return ""
    words = re.findall(r"\S+", text.strip())
    if len(words) <= max_words:
        return " ".join(words)
    # Always finish the current sentence rather than cutting mid-sentence.
    result = words[:max_words]
    _sentence_end = re.compile(r'[.!?]["\')]*$')
    if not _sentence_end.search(result[-1]):
        for word in words[max_words:]:
            result.append(word)
            if _sentence_end.search(word):
                break
    return " ".join(result)


def _load_convener_manifest():
    config_path = os.path.join(os.path.dirname(__file__), "agent_config.json")
    manifest = load_manifest_from_config(config_path)
    override_service_url = os.getenv("SERVICE_URL", "").strip()
    override_speaker_uri = os.getenv("SPEAKER_URI", "").strip()
    if override_service_url:
        manifest.identification.serviceUrl = override_service_url
    if override_speaker_uri:
        manifest.identification.speakerUri = override_speaker_uri
    return manifest


CONVENER_MANIFEST = _load_convener_manifest()


def is_specialist_sweep_request(text: str) -> bool:
    """Return True when user explicitly asks the convener to run all specialists in sequence."""
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in SPECIALIST_SWEEP_PATTERNS)


def is_invite_specialists_request(text: str) -> bool:
    """Return True when user asks the convener to invite specialists."""
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in INVITE_SPECIALISTS_PATTERNS)


def classify_intent(text: str) -> list[str]:
    if is_specialist_sweep_request(text):
        logger.info("Detected specialist sweep intent; routing through full analysis sequence")
        return FULL_ANALYSIS_SEQUENCE

    text_lower = text.lower()
    matched = []
    for agent_key, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, text_lower):
            matched.append(agent_key)

    full_triggers = r"\b(analyze|analysis|evaluate|review|assess|tell me about|help me|startup|idea|concept)\b"
    if not matched or re.search(full_triggers, text_lower):
        return FULL_ANALYSIS_SEQUENCE

    return matched


# =============================================================================
# LLM-BASED INTENT CLASSIFICATION
#
# Single call replacing is_invite_specialists_request() + detect_addressed_agent()
# + classify_intent()'s "which agents" decision. Regex keyword matching is
# brittle against phrasing it wasn't written for (e.g. a legitimate business
# idea that happens to contain the word "invite" or a specialist's name in
# prose gets misclassified) and against natural addressing ("what does market
# think?"). The functions above are kept as-is and used as the fallback when
# the LLM call fails or returns something unusable, so routing never blocks
# on LLM/API availability.
# =============================================================================

_AGENT_TOPIC_SUMMARY = {
    "market": "market sizing (TAM/SAM/SOM), demand, growth, geography",
    "competitive": "competitive landscape, differentiation, moat, IP/patents",
    "model": "business model, revenue, pricing, monetization, unit economics",
    "risk": "risk register: regulatory, legal, compliance, execution risk",
    "funding": "funding strategy: raise size, investors, valuation, runway",
    "workforce": "hiring/workforce: team, roles, salaries, headcount",
    "skeptic": "devil's advocate: challenges, weaknesses, pushback, bear case",
    "strategy": "strategy synthesis: summarizes all specialists into a recommendation",
}


def _build_classifier_system_prompt() -> str:
    roster = "\n".join(
        f'- {key}: {AGENTS[key]["name"]} — {_AGENT_TOPIC_SUMMARY.get(key, "")}'
        for key in FULL_ANALYSIS_SEQUENCE
        if key in AGENTS
    )
    valid_keys = ", ".join(k for k in FULL_ANALYSIS_SEQUENCE if k in AGENTS)
    return f"""You are the routing layer for a startup-strategy floor with these specialist agents:
{roster}

Classify the user's message into exactly one action:
- "invite_only": the message is ONLY an instruction to invite/add specialists to the conversation, with no question or startup idea to analyze (e.g. "invite your specialists", "bring the team in"). Do not use this if the message also contains a question or idea.
- "ask_specific_agent": the message is clearly and directly addressed to ONE named specialist (e.g. "Market Validator, what's the TAM?", "ask risk about compliance"). Do not use this for a general question that merely mentions a specialist's topic in passing.
- "ask_agents": anything else — a startup idea, question, or request for one or more specialists to weigh in. If the message doesn't clearly call for only specific specialists, include every specialist key (a full analysis sweep) rather than guessing narrowly.

Respond with ONLY a single JSON object and no other text, in this exact shape (field names and action values are literal identifiers -- always in English, regardless of what language the user's message is in):
{{"action": "invite_only", "addressed_agent_key": null, "agent_keys": []}}
or
{{"action": "ask_specific_agent", "addressed_agent_key": "<one of: {valid_keys}>", "agent_keys": []}}
or
{{"action": "ask_agents", "addressed_agent_key": null, "agent_keys": ["<one or more of: {valid_keys}>"]}}
"""


_CLASSIFIER_SYSTEM_PROMPT = _build_classifier_system_prompt()


def _classify_utterance_fallback(user_text: str) -> dict:
    """Regex-based classification (the pre-LLM implementation), used when the
    LLM classifier is unavailable or returns something unusable."""
    if is_invite_specialists_request(user_text):
        return {"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}

    addressed_agent_key = detect_addressed_agent(user_text)
    if addressed_agent_key:
        return {"action": "ask_specific_agent", "addressed_agent_key": addressed_agent_key, "agent_keys": []}

    return {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": classify_intent(user_text)}


def _fast_action_hint(user_text: str) -> dict | None:
    """Cheap regex-only check for the two actions ("invite_only" and
    "ask_specific_agent") that must be able to override a round in progress
    regardless of what's already invited. Runs on every utterance, so it has
    to stay microseconds-fast; unlike _classify_utterance_fallback() it does
    NOT fall through to classify_intent()'s full-sweep guess, since that's
    exactly the ambiguous "which agents" decision the LLM classifier exists
    to make better than regex.

    Returns None when neither regex signal fires -- the caller should then
    either reuse an existing round-robin roster or call the LLM.
    """
    if is_invite_specialists_request(user_text):
        return {"action": "invite_only", "addressed_agent_key": None, "agent_keys": []}

    addressed_agent_key = detect_addressed_agent(user_text)
    if addressed_agent_key:
        return {"action": "ask_specific_agent", "addressed_agent_key": addressed_agent_key, "agent_keys": []}

    return None


# Classification only needs a ~50-token JSON reply, unlike specialist
# analysis calls which can legitimately run long. Keep its timeout short so
# a slow/degraded LLM backend fails over to the regex fallback in seconds,
# not the 60-90s chat_sync default -- that default is sized for the other
# kind of call.
_CLASSIFIER_TIMEOUT_SECONDS = 8


@functools.lru_cache(maxsize=128)
def _classify_via_llm(user_text: str) -> dict:
    """The actual LLM call plus JSON parsing/validation, memoized by exact
    utterance text. Guards against a client retry (or double-submit) paying
    for a second LLM round-trip -- and, since the model isn't perfectly
    deterministic even at temperature=0, against a retry landing on a
    different classification than the first attempt already committed floor
    events for. Raises on any failure; a raised exception is never cached,
    so failures are retried on the next call rather than sticking."""
    raw = llm_utils.chat_sync(
        _CLASSIFIER_SYSTEM_PROMPT,
        user_text,
        temperature=0,
        timeout=_CLASSIFIER_TIMEOUT_SECONDS,
        ollama_model=llm_utils.CLASSIFIER_OLLAMA_MODEL,
        openai_model=llm_utils.CLASSIFIER_LLM_MODEL,
    )
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise ValueError(f"no JSON object in classifier response: {raw!r}")
    parsed = json.loads(match.group())

    action = parsed.get("action")
    if action not in ("invite_only", "ask_specific_agent", "ask_agents"):
        raise ValueError(f"invalid action: {action!r}")

    addressed_agent_key = parsed.get("addressed_agent_key")
    if addressed_agent_key not in AGENTS:
        addressed_agent_key = None

    agent_keys = [k for k in (parsed.get("agent_keys") or []) if k in AGENTS]

    if action == "ask_specific_agent" and not addressed_agent_key:
        # Claimed a specific agent but didn't name a valid one -- degrade
        # to asking everyone rather than silently doing nothing.
        action = "ask_agents"
    if action == "ask_agents" and not agent_keys:
        agent_keys = list(FULL_ANALYSIS_SEQUENCE)

    result = {"action": action, "addressed_agent_key": addressed_agent_key, "agent_keys": agent_keys}
    logger.info(f"LLM classification for '{user_text[:60]}' -> {result}")
    return result


def classify_utterance(user_text: str, round_robin_roster: list[str] | None = None) -> dict:
    """LLM-based routing classification for a user utterance.

    Returns a dict:
      {"action": "invite_only" | "ask_specific_agent" | "ask_agents",
       "addressed_agent_key": str | None,
       "agent_keys": list[str]}

    Falls back to _classify_utterance_fallback() (the regex-based
    classifiers) on any failure: LLM/API error, unparseable response, or a
    hallucinated agent key that doesn't exist. Routing must never block on
    LLM availability.

    round_robin_roster: when the caller already knows which agents are
    mid-round (a continuing round-robin turn), pass that roster here. A
    cheap regex pre-check still runs first (an explicit meta-instruction or
    direct address must be able to interrupt a round), but if neither fires,
    the roster is reused directly and the LLM call -- whose "which agents"
    answer would be discarded in favor of the roster anyway -- is skipped
    entirely. This is what keeps continuing round-robin turns fast; a fresh
    conversation (no roster) always goes through the real (memoized) LLM
    call in _classify_via_llm().
    """
    fast = _fast_action_hint(user_text)
    if fast is not None:
        return fast

    if round_robin_roster:
        return {"action": "ask_agents", "addressed_agent_key": None, "agent_keys": round_robin_roster}

    try:
        # Copy (including the agent_keys list) so callers can't mutate the
        # object shared across calls via the lru_cache.
        cached = _classify_via_llm(user_text)
        return {**cached, "agent_keys": list(cached["agent_keys"])}
    except Exception as exc:
        logger.warning(f"LLM classification failed, falling back to regex classifiers: {exc}")
        return _classify_utterance_fallback(user_text)


def build_convener_text_event(text: str) -> UtteranceEvent:
    """Build a single utterance event spoken by the convener itself, e.g. for
    status acknowledgements ("All specialists are already invited.") that
    aren't tied to any specialist's turn."""
    dialog_event = DialogEvent(speakerUri=CONVENER_MANIFEST.identification.speakerUri)
    text_feature = TextFeature()
    text_feature.tokens = [Token(value=text)]
    dialog_event.features = {"text": text_feature}
    return UtteranceEvent(dialogEvent=dialog_event)




app = Flask(__name__)


def _normalize_id(value: str | None) -> str:
    if not value:
        return ""
    normalized = str(value).strip().lower()
    if normalized.startswith("agent:"):
        normalized = normalized[6:]
    return normalized.rstrip("/")


def _conversant_records(conversation) -> list[dict]:
    """[{"speakerUri", "serviceUrl"}, ...] from the conversation.conversants
    the floor manager supplies -- the stateless replacement for
    resolve_agent_target_uri()'s old HTTP round-trip."""
    conversants = _field(conversation, "conversants", []) or []
    records = []
    for c in conversants:
        ident = _field(c, "identification", {}) or {}
        records.append({
            "speakerUri": _field(ident, "speakerUri", "") or "",
            "serviceUrl": _field(ident, "serviceUrl", "") or "",
        })
    return records


def _agent_key_for_service_url(service_url: str) -> str | None:
    normalized = _normalize_id(service_url)
    if not normalized:
        return None
    for key, info in AGENTS.items():
        if _normalize_id(info["url"]) == normalized:
            return key
    return None


def _agent_key_for_speaker_uri(speaker_uri: str, conversant_records: list[dict]) -> str | None:
    normalized_speaker = _normalize_id(speaker_uri)
    if not normalized_speaker:
        return None
    for record in conversant_records:
        if _normalize_id(record["speakerUri"]) == normalized_speaker:
            return _agent_key_for_service_url(record["serviceUrl"])
    return None


def _invited_agent_keys_from_conversants(conversant_records: list[dict]) -> list[str]:
    keys = []
    for record in conversant_records:
        key = _agent_key_for_service_url(record["serviceUrl"])
        if key and key not in keys:
            keys.append(key)
    # Canonical order, matching the old _round_robin_invited_keys() behavior.
    return [k for k in FULL_ANALYSIS_SEQUENCE if k in keys]


def _find_speaker_uri_for_key(agent_key: str, conversant_records: list[dict]) -> str:
    normalized = _normalize_id(AGENTS.get(agent_key, {}).get("url", ""))
    for record in conversant_records:
        if _normalize_id(record["serviceUrl"]) == normalized:
            return record["speakerUri"]
    return ""


def _lookup_target_for_agent(agent_key: str, conversant_records: list[dict]) -> To:
    info = AGENTS.get(agent_key, {})
    configured_url = info.get("url", "")
    normalized = _normalize_id(configured_url)
    for record in conversant_records:
        if _normalize_id(record["serviceUrl"]) == normalized:
            return To(speakerUri=record["speakerUri"] or None, serviceUrl=record["serviceUrl"] or configured_url)
    return To(serviceUrl=configured_url)


def _question_text(text: str, max_words: int) -> str:
    if not max_words or max_words == MAX_RESPONSE_WORDS:
        return text
    return text + f"\n\n[Write approximately {max_words} words.]"


def _question_dialog_event(text: str, max_words: int) -> DialogEvent:
    dialog_event = DialogEvent(speakerUri=CONVENER_MANIFEST.identification.speakerUri)
    text_feature = TextFeature()
    text_feature.tokens = [Token(value=_question_text(text, max_words))]
    dialog_event.features = {"text": text_feature}
    return dialog_event


def _grant_and_ask_events(agent_key: str, text: str, max_words: int, conversant_records: list[dict], private: bool) -> list:
    if agent_key not in AGENTS:
        return []
    target = _lookup_target_for_agent(agent_key, conversant_records)
    utterance_kwargs = {"dialogEvent": _question_dialog_event(text, max_words)}
    if private:
        utterance_kwargs["to"] = To(speakerUri=target.speakerUri, serviceUrl=target.serviceUrl, private=True)
    return [GrantFloorEvent(to=target), UtteranceEvent(**utterance_kwargs)]


def _grant_only_event(agent_key: str, conversant_records: list[dict]):
    if agent_key not in AGENTS:
        return None
    return GrantFloorEvent(to=_lookup_target_for_agent(agent_key, conversant_records))


def _public_question_utterance(text: str, max_words: int) -> UtteranceEvent:
    return UtteranceEvent(dialogEvent=_question_dialog_event(text, max_words))


def _invite_events_for_not_yet_invited(conversant_records: list[dict]) -> list:
    already = set()
    for record in conversant_records:
        key = _agent_key_for_service_url(record["serviceUrl"])
        if key:
            already.add(key)
    events = []
    for key in FULL_ANALYSIS_SEQUENCE:
        if key in already:
            continue
        events.append(InviteEvent(to=To(serviceUrl=AGENTS[key]["url"])))
    if not events:
        return [build_convener_text_event("All specialists are already invited.")]
    return events


def _decide_for_human_utterance(text: str, routing_mode: str, max_words: int, conversant_records: list[dict]) -> list:
    invited_keys = _invited_agent_keys_from_conversants(conversant_records)
    classification = classify_utterance(text, round_robin_roster=invited_keys if routing_mode == "round_robin" else [])

    if classification["action"] == "invite_only":
        logger.info("Detected invite-specialists intent")
        return _invite_events_for_not_yet_invited(conversant_records)

    if classification["action"] == "ask_specific_agent":
        agent_key = classification["addressed_agent_key"]
        if not agent_key:
            return []
        logger.info(f"Directly addressed agent for '{text[:60]}' -> {agent_key}")
        return _grant_and_ask_events(agent_key, text, max_words, conversant_records, private=True)

    agent_keys = classification["agent_keys"]
    if not agent_keys:
        return []

    if routing_mode == "round_robin":
        logger.info(f"Round-robin turn order for '{text[:60]}' -> agents: {agent_keys}; starting with {agent_keys[0]}")
        return _grant_and_ask_events(agent_keys[0], text, max_words, conversant_records, private=True)

    logger.info(f"Full-sweep classification for '{text[:60]}' -> agents: {agent_keys}")
    events = []
    for key in agent_keys:
        grant = _grant_only_event(key, conversant_records)
        if grant is not None:
            events.append(grant)
    if not events:
        return []
    events.append(_public_question_utterance(text, max_words))
    return events


def _decide_for_specialist_reply(speaker_uri: str, routing_mode: str, question_text: str, max_words: int,
                                  round_turn_order: list[str], conversant_records: list[dict]) -> list:
    revoke_event = RevokeFloorEvent(to=To(speakerUri=speaker_uri))

    if routing_mode != "round_robin" or not question_text:
        # Full-sweep: each agent was already granted+asked up front (see
        # _decide_for_human_utterance); nothing left to do but revoke this
        # one now that it has spoken.
        return [revoke_event]

    invited_keys = _invited_agent_keys_from_conversants(conversant_records)
    classification = classify_utterance(question_text, round_robin_roster=invited_keys)
    agent_keys = classification["agent_keys"] if classification["agent_keys"] else invited_keys

    already_spoken = {_normalize_id(u) for u in (round_turn_order or [])}
    remaining = [
        key for key in agent_keys
        if _normalize_id(_find_speaker_uri_for_key(key, conversant_records)) not in already_spoken
    ]
    if not remaining:
        logger.info("Round-robin sequence complete")
        return [revoke_event]

    logger.info(f"Round-robin: advancing to next agent -> {remaining[0]}")
    return [revoke_event, *_grant_and_ask_events(remaining[0], question_text, max_words, conversant_records, private=True)]


def _classify_speaker(speaker_uri: str, conversant_records: list[dict]) -> str:
    """"specialist" | "human" -- distinguishes a specialist's own reply
    (advance/end the round) from a fresh question (start a round)."""
    if _agent_key_for_speaker_uri(speaker_uri, conversant_records) is not None:
        return "specialist"
    return "human"


def _decide_delegated_utterance(event, conversation) -> list:
    params = getattr(event, "parameters", None) or {}
    dialog = getattr(event, "dialogEvent", None)
    if dialog is None and hasattr(params, "get"):
        dialog = params.get("dialogEvent")
    speaker_uri = _field(dialog, "speakerUri", "") if dialog else ""

    def _param(key, default):
        return params.get(key, default) if hasattr(params, "get") else default

    round_question = (_param("roundQuestion", "") or "").strip()
    round_routing_mode = (_param("roundRoutingMode", "") or "").strip().lower()
    round_max_words = _param("roundMaxWords", 0) or MAX_RESPONSE_WORDS
    round_turn_order = list(_param("roundTurnOrder", []) or [])

    if not round_question:
        return []

    conversant_records = _conversant_records(conversation)
    if _classify_speaker(speaker_uri, conversant_records) == "specialist":
        return _decide_for_specialist_reply(
            speaker_uri, round_routing_mode, round_question, round_max_words, round_turn_order, conversant_records
        )
    return _decide_for_human_utterance(round_question, round_routing_mode, round_max_words, conversant_records)


def _parse_incoming_envelope(json_payload: str):
    first_error = None
    try:
        return Envelope.from_json(json_payload, as_payload=True)
    except Exception as e:
        first_error = e

    try:
        return Envelope.from_json(json_payload)
    except Exception as e:
        raise ValueError(f"{first_error}; fallback parse failed: {e}")


def handle_envelope_json(json_payload: str) -> str:
    try:
        in_envelope = _parse_incoming_envelope(json_payload)
    except Exception as e:
        return json.dumps({"error": f"Invalid envelope: {e}"})

    conv_id = getattr(getattr(in_envelope, "conversation", None), "id", None) or "default"
    events = getattr(in_envelope, "events", []) or []

    out_envelope = Envelope(
        conversation=Conversation(id=conv_id),
        sender=Sender(
            speakerUri=CONVENER_MANIFEST.identification.speakerUri,
            serviceUrl=CONVENER_MANIFEST.identification.serviceUrl
        ),
        schema=Schema(version="1.1", url="https://openvoicenetwork.org/schema"),
        events=[]
    )

    for event in events:
        event_type = getattr(event, "eventType", None)
        event_params = getattr(event, "parameters", None) or {}
        # web-floor's spec-literal floor manager (floor_router.py) always
        # attaches roundHistory/roundTurnOrder to events it delegates or
        # courtesy-copies (OFP spec section 2.2's routing table) -- that
        # marker is how this branch stays fully separate from the
        # pre-existing utterance/invite/getManifests handling below, which
        # the OLD (still-live, pre-floor-manager) gateway path continues to
        # use completely unchanged.
        if "roundHistory" in event_params:
            # Trivial echo-back for delegated control events (approve as
            # given -- convener has no additional opinion on invite/
            # uninvite/requestFloor/grantFloor/revokeFloor beyond what the
            # floor manager already decided to ask about). Real decision
            # logic lives in _decide_delegated_utterance for utterances.
            if event_type in ("invite", "uninvite", "requestFloor", "grantFloor", "revokeFloor"):
                out_envelope.events = [event]
            elif event_type == "utterance":
                out_envelope.events = _decide_delegated_utterance(event, getattr(in_envelope, "conversation", None))
            else:
                out_envelope.events = []
            break
        if event_type == "getManifests":
            publish = PublishManifestsEvent(parameters=Parameters({
                "servicingManifests": [CONVENER_MANIFEST],
                "discoveryManifests": []
            }))
            out_envelope.events = [publish]
            break
        if event_type == "invite":
            from openfloor.events import AcceptInviteEvent
            out_envelope.events = [AcceptInviteEvent()]
            break
        # A plain (non-delegated) utterance with no floor manager in front of
        # it has no meaning anymore -- every utterance convener should act on
        # arrives via the "roundHistory" branch above. Nothing left to do.

    if not getattr(out_envelope, "events", None):
        out_envelope.events = []

    return out_envelope.to_json(as_payload=True)


@app.route("/", methods=["POST"])
def handle():
    payload = request.get_data(as_text=True)
    if not payload:
        return Response('{"error":"empty body"}', status=400, mimetype="application/json")
    logger.info("Convener handling POST request")
    try:
        result = handle_envelope_json(payload)
        logger.info("Convener generated response")
        return Response(result, status=200, mimetype="application/json")
    except Exception as e:
        logger.error(f"Convener error: {e}", exc_info=True)
        return Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


@app.route("/health", methods=["GET"])
def health():
    # convener holds no conversant/floor state of its own anymore -- that's
    # web-floor's floor manager's job (GET /api/floor/state on the gateway
    # reports live conversants). This just confirms the service is up.
    return {
        "status": "ok",
        "agent": "Startup Strategy Convener",
        "agents": list(AGENTS.keys()),
    }


@app.route("/manifest", methods=["POST"])
def manifest():
    return jsonify(CONVENER_MANIFEST.__json__())


def main() -> None:
    port = int(os.getenv("PORT", "8199"))
    logger.info(f"Starting Startup Strategy Convener on port {port}")
    logger.info("Specialist agents expected at ports 8200-8207")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
