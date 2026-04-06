#!/usr/bin/env python3
"""Utterance handler for Lucky (high-risk financial guidance)."""

import json
import logging
import os
import random
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

logger = logging.getLogger(__name__)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_RESPONSE_WORDS = 35
REACTION_STYLE_OPTIONS = [
    "Use punchy language and state a clear preferred move.",
    "Use energetic phrasing with one concrete high-beta action.",
    "Use assertive wording and sound decisive, not tentative.",
]
GUIDANCE_STYLE_OPTIONS = [
    "Vary phrasing across turns and avoid repeating boilerplate.",
    "State recommendations directly and keep them specific.",
    "Rotate wording and examples while staying decisive and action-oriented.",
]
_peer_rebuttal_used = False
_peer_reaction_count = 0
_responded_to_user_in_cycle = False


def _canonical_agent_name(value: str) -> str:
    raw = (value or "").strip()
    normalized = raw.lower()
    if not normalized:
        return ""

    if "assistantclientconvener" in normalized:
        return ""

    # Use speaker-provided identity only; avoid hardcoded peer mappings.
    candidate = raw
    if "/" in candidate:
        candidate = candidate.rstrip("/").split("/")[-1]
    if ":" in candidate:
        candidate = candidate.split(":")[-1]

    candidate = re.sub(r"^agent:\s*", "", candidate, flags=re.IGNORECASE).strip()
    candidate = re.sub(r"[^A-Za-z0-9 _-]", " ", candidate).strip()
    if not candidate:
        return ""

    return " ".join(part.capitalize() for part in candidate.split())


def _build_client() -> OpenAI | None:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _classify_query(user_text: str, client: OpenAI | None) -> dict:
    if client is None:
        return {
            "needs_live_data": _heuristic_live_data_check(user_text),
            "company_or_ticker": "",
            "user_goal": user_text,
        }

    prompt = (
        "Classify the finance user message for a very aggressive, high-risk advisor. "
        "Return strict JSON with keys: needs_live_data (boolean), company_or_ticker (string), user_goal (string). "
        "Set needs_live_data=true when the user asks for current/latest/live prices, today performance, market cap, valuation now, or any real-time company metric. "
        "If no company is mentioned, company_or_ticker should be empty string. "
        "limit response to 50 words max in total. "
        "Preserve the user's appetite for risk in user_goal instead of softening it."
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_text},
        ],
    )

    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    return {
        "needs_live_data": bool(parsed.get("needs_live_data")),
        "company_or_ticker": str(parsed.get("company_or_ticker") or "").strip(),
        "user_goal": str(parsed.get("user_goal") or user_text).strip(),
    }


def _heuristic_live_data_check(user_text: str) -> bool:
    lower = user_text.lower()
    triggers = [
        "price",
        "stock",
        "quote",
        "today",
        "right now",
        "currently",
        "latest",
        "live",
        "market cap",
        "valuation",
        "trading at",
    ]
    return any(word in lower for word in triggers)


def _shorten_response(text: str, max_words: int = MAX_RESPONSE_WORDS) -> str:
    words = (text or "").strip().split()
    if len(words) <= max_words:
        return (text or "").strip()
    return " ".join(words[:max_words]).rstrip(",;:-") + "..."


def _should_react_to_other_agent(user_text: str, agent_name: str, speaker_name: str) -> bool:
    normalized_speaker = (speaker_name or "").strip().lower()
    if not normalized_speaker:
        return False

    # Never react to own messages
    speaker_display_name = _canonical_agent_name(speaker_name) or normalized_speaker
    if speaker_display_name.lower() == (agent_name or "").strip().lower():
        return False

    stripped_text = (user_text or "").strip().lower()
    if not stripped_text:
        return False

    return True


def _is_agent_speaker(speaker_name: str) -> bool:
    return bool(_canonical_agent_name(speaker_name))


def _strip_leading_addressee_prefixes(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    # Remove repeated leading addressee prefixes like "Prudence: " or "To Team - ".
    prefix_pattern = re.compile(r"^\s*(?:to\s+)?[a-z][a-z0-9 _-]{0,40}\s*[:,-]\s*", re.IGNORECASE)
    while True:
        updated = prefix_pattern.sub("", cleaned, count=1).strip()
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _is_user_finance_question(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False

    lower = text.lower()
    finance_keywords = (
        "stock", "stocks", "price", "market", "invest", "investment", "portfolio",
        "risk", "returns", "etf", "fund", "trading", "earnings", "company", "shares",
        "dividend", "valuation", "finance", "financial",
        "retire", "retirement", "pension", "401k", "ira", "roth", "annuity",
        "savings", "save", "wealth", "budget", "debt", "loan", "mortgage",
        "strategy", "money", "asset", "assets", "allocation", "bond", "bonds",
        "crypto", "bitcoin", "interest", "rate", "tax", "taxes",
    )
    request_starts = (
        "what", "how", "why", "when", "where", "who", "can", "could", "should", "would",
        "is", "are", "do", "does", "did", "tell me", "show me", "give me", "help me",
        "i need", "i want", "please",
    )

    is_question_or_request = "?" in text or lower.startswith(request_starts)
    has_finance_context = any(word in lower for word in finance_keywords)
    return is_question_or_request and has_finance_context


def _generate_reaction_to_peer_advice(user_text: str, client: OpenAI | None) -> str:
    if client is None:
        return _shorten_response(
            "That is too cautious and likely to cap upside. Take the higher-upside route: concentrate selectively, accept volatility, and keep capital aimed at the strongest growth opportunity."
        )

    system = (
        "You are Lucky, a high-risk financial guidance assistant reacting to another advisor. "
        "keep your vocabulary understandable by a lay person."
        "You have a cheerful happy-go-lucky personality and clearly disapprove of overly cautious, fear-driven advice. "
        "Reply with a short, assertive counterpoint favoring upside, selective concentration, and volatility tolerance. "
        "Sound confident and decisive. Make a direct recommendation instead of hedging or listing balanced pros and cons. "
        "Do not mention live market data. Return at most 2 sentences and 30 words. "
        f"{random.choice(REACTION_STYLE_OPTIONS)}"
    )
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.85,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    )
    return _shorten_response(response.choices[0].message.content or "")


def _generate_aggressive_guidance(user_text: str, user_goal: str, client: OpenAI | None) -> str:
    if client is None:
        return _shorten_response(
            "I can help with aggressive financial guidance, but I need OPENAI_API_KEY "
            "to generate tailored suggestions. Default to concentrated upside, accept volatility, "
            "and put more capital behind the highest-conviction speculative idea."
        )

    system = (
        "You are Lucky, a high-risk, devil may care, impulsive financial guidance assistant. "
        "You favor aggressive upside, concentrated bets, momentum, speculative trades, and asymmetric return opportunities. "
        "You openly disapprove of overly cautious investing that sacrifices too much upside. "
        "keep your vocabulary understandable by a lay person."
        "Do not claim to provide live market data. "
        "Keep responses concise, practical, energetic, and clearly directional. "
        "Give strong recommendations with decisive verbs like buy, add, trim, hold, or avoid. Do not hedge with excessive caveats or neutrality. "
        "Return at most 2 sentences and 35 words total. "
        f"{random.choice(GUIDANCE_STYLE_OPTIONS)}"
    )
    user = (
        f"User message: {user_text}\n"
        f"Interpreted goal: {user_goal}\n"
        "Provide 2-3 aggressive, high-risk suggestions only, phrased as direct recommendations."
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.8,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _shorten_response(response.choices[0].message.content or "")


def _looks_like_agent_greeting(text: str) -> bool:
    """Return True if text looks like an agent invite greeting that may be echoed back."""
    lower = (text or "").strip().lower()
    return (
        lower.startswith("hi, i'm")
        or lower.startswith("hello, i'm")
        or lower.startswith("hi i'm")
    )


def process_utterance(user_text: str, agent_name: str = "Lucky", speaker_name: str = "") -> str:
    global _peer_rebuttal_used, _peer_reaction_count, _responded_to_user_in_cycle

    if not user_text or not user_text.strip():
        return "Share your financial question, and I will give brief aggressive guidance."

    # Block agent invite greetings - no advice should be triggered by another agent's greeting
    if _looks_like_agent_greeting(user_text):
        return ""

    if _is_agent_speaker(speaker_name):
        max_peer_reactions = 1 if _responded_to_user_in_cycle else 2
        if _peer_reaction_count >= max_peer_reactions or not _should_react_to_other_agent(user_text, agent_name, speaker_name):
            return ""

        target_name = _canonical_agent_name(speaker_name) or (speaker_name or "").strip()
        client = _build_client()
        try:
            reaction_text = _strip_leading_addressee_prefixes(_generate_reaction_to_peer_advice(user_text, client))
            if not reaction_text:
                return ""
            _peer_reaction_count += 1
            _peer_rebuttal_used = True
            return f"{target_name}: {reaction_text}" if target_name else reaction_text
        except Exception:
            logger.exception("Failed to generate reaction to another advisor")
            fallback = _strip_leading_addressee_prefixes(_shorten_response(
                "That is too cautious for someone seeking upside. If the risk budget is real, a focused high-volatility allocation can make more sense than over-diversifying everything away."
            ))
            if not fallback:
                return ""
            _peer_reaction_count += 1
            _peer_rebuttal_used = True
            return f"{target_name}: {fallback}" if target_name else fallback

    # A fresh user question resets peer-reaction budget for this turn.
    _peer_rebuttal_used = False
    _peer_reaction_count = 0
    _responded_to_user_in_cycle = False

    if not _is_user_finance_question(user_text):
        return ""

    _responded_to_user_in_cycle = True

    client = _build_client()

    try:
        analysis = _classify_query(user_text, client)
    except Exception:
        logger.exception("Failed to classify message; falling back to heuristic analysis")
        analysis = {
            "needs_live_data": _heuristic_live_data_check(user_text),
            "company_or_ticker": "",
            "user_goal": user_text,
        }

    if analysis.get("needs_live_data"):
        return ""

    try:
        return _generate_aggressive_guidance(user_text, analysis.get("user_goal", user_text), client)
    except Exception:
        logger.exception("Failed to generate aggressive guidance")
        return _shorten_response(
            "I could not generate a tailored recommendation right now. "
            "As a high-risk default, concentrate only what you can afford to lose, lean into volatility intentionally, "
            "and treat speculative positions as capped-risk bets."
        )
