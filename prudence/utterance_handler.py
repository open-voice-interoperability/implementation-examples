#!/usr/bin/env python3
"""Utterance handler for Prudence (conservative financial guidance)."""

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
    "Use plain-spoken wording with short clauses and a clear recommendation.",
    "Use restrained professional wording with one concrete caution.",
    "Use concise coach-like wording with one firm risk-control action.",
]
GUIDANCE_STYLE_OPTIONS = [
    "Vary your phrasing from prior replies and avoid repeating stock expressions.",
    "Use a different sentence structure than usual and keep recommendations concrete and firm.",
    "Keep tone steady but rotate wording and examples while remaining decisive.",
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
        "Classify the finance user message for a very conservative advisor. "
        "Return strict JSON with keys: needs_live_data (boolean), "
        "company_or_ticker (string), user_goal (string). "
        "Set needs_live_data=true when the user asks for current/latest/live prices, "
        "today performance, market cap, valuation now, or any real-time company metric. "
        "Discourage any risky financial moves in user_goal. If the user is asking for financial guidance without live data, "
        "Limit response to 50 words max in total. If no company is mentioned, company_or_ticker should be empty string."
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

    # Remove repeated leading addressee prefixes like "Lucky: " or "To Team - ".
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
            "That is reckless advice for most people. Take the safer route: diversify, reduce position size, and protect downside before chasing upside."
        )

    system = (
        "You are Prudence, a conservative financial guidance assistant reacting to another advisor's advice. "
        "keep your vocabulary understandable by a lay person."
        "Respond with a calm but clearly disapproving counterpoint when the advice is reckless or speculative. "
        "Keep it brief, practical, and focused on downside protection, diversification, and capital preservation. "
        "Sound firm and directive. Make a clear recommendation rather than a soft suggestion. "
        "Do not mention live market data. Return at most 2 sentences and 30 words. "
        f"{random.choice(REACTION_STYLE_OPTIONS)}"
    )
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.8,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    )
    return _shorten_response(response.choices[0].message.content or "")


def _generate_conservative_guidance(user_text: str, user_goal: str, client: OpenAI | None) -> str:
    if client is None:
        return _shorten_response(
            "I can help with conservative financial guidance, but I need OPENAI_API_KEY "
            "to generate tailored suggestions. Prioritize emergency savings, diversification, low-cost funds, "
            "and smaller position sizes before taking any additional risk."
        )

    system = (
        "You are Prudence, a conservative financial guidance assistant. "
        "You have a serious, dour personality and openly disapprove of reckless financial behavior. "
        "Be cautious, practical, risk-aware, and skeptical of hype or momentum-chasing. "
        "Do not claim to provide live market data. "
        "Focus on risk management, diversification, downside protection, and long-term planning. "
        "Keep responses concise, clear, and clearly directional. "
        "Give firm recommendations with decisive verbs like avoid, reduce, hold, build, or prioritize. Do not hedge with excessive softness or neutrality. "
        "Return at most 2 sentences and 35 words total. "
        f"{random.choice(GUIDANCE_STYLE_OPTIONS)}"
    )
    user = (
        f"User message: {user_text}\n"
        f"Interpreted goal: {user_goal}\n"
        "Provide 2-3 conservative suggestions only, phrased as direct recommendations."
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.75,
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


def process_utterance(user_text: str, agent_name: str = "Prudence", speaker_name: str = "") -> str:
    global _peer_rebuttal_used, _peer_reaction_count, _responded_to_user_in_cycle

    if not user_text or not user_text.strip():
        return "Share your financial question, and I will give brief conservative guidance."

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
                "That approach is too aggressive for most investors. A safer path is broader diversification, smaller position sizes, and more attention to downside protection."
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
        return _generate_conservative_guidance(user_text, analysis.get("user_goal", user_text), client)
    except Exception:
        logger.exception("Failed to generate conservative guidance")
        return _shorten_response(
            "I could not generate a tailored recommendation right now. "
            "As a conservative default, keep a diversified portfolio, avoid concentrated bets, "
            "and review risk tolerance before making changes."
        )
