#!/usr/bin/env python3
"""
Startup Strategy Convener — OFP Floor Convener

Routes startup strategy queries across 7 specialist agents using
keyword-based intent classification (SLM-ready, no external model required).
"""

import json
import logging
import os
import re
import sys
import threading

import httpx
from flask import Flask, Response, request, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.base_strategy_agent import load_manifest_from_config
from openfloor.envelope import Envelope, Conversation, Sender, Schema, To
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
    "market": {"name": "Market Validator", "port": 8200, "url": "http://localhost:8200/", "aliases": ["market", "tam", "sam", "som", "market sizing", "market validator"]},
    "competitive": {"name": "Competitive Intelligence", "port": 8201, "url": "http://localhost:8201/", "aliases": ["competitive", "competitor", "competition", "competitive intelligence"]},
    "model": {"name": "Business Model Designer", "port": 8202, "url": "http://localhost:8202/", "aliases": ["model", "business model", "business model designer"]},
    "risk": {"name": "Risk Identifier", "port": 8203, "url": "http://localhost:8203/", "aliases": ["risk", "risk identifier", "risk identification"]},
    "funding": {"name": "Funding Strategist", "port": 8204, "url": "http://localhost:8204/", "aliases": ["funding", "funding strategist", "raise", "fundraising"]},
    "workforce": {"name": "Workforce Strategist", "port": 8205, "url": "http://localhost:8205/", "aliases": ["workforce", "workforce strategist", "team", "hiring"]},
    "skeptic": {"name": "Devil's Advocate", "port": 8206, "url": "http://localhost:8206/", "aliases": ["skeptic", "devil's advocate", "skeptic", "devil", "challenge"]},
    "strategy": {"name": "Strategy Synthesizer", "port": 8207, "url": "http://localhost:8207/", "aliases": ["strategy", "strategy synthesizer", "synthesis", "summary"]}
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
    """Detect if user is addressing a specific agent by name or alias.
    
    Examples:
      "Market Validator, what's the TAM?" -> "market"
      "Ask the skeptic about risks" -> "skeptic"
      "Competitive intelligence on this?" -> "competitive"
      
    Returns:
      Agent key if detected, None otherwise
    """
    text_lower = text.lower()
    
    for agent_key, agent_info in AGENTS.items():
        for alias in agent_info.get("aliases", []):
            # Match exact words or with common punctuation
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, text_lower):
                logger.info(f"Detected addressed agent: {agent_key} (alias: {alias})")
                return agent_key
    
    return None


def _limit_words(text: str, max_words: int = MAX_RESPONSE_WORDS) -> str:
    if not text:
        return ""
    words = re.findall(r"\S+", text.strip())
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


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


def resolve_agent_target_uri(agent_key: str) -> str:
    """Resolve the best target URI for an agent, preferring manifest speakerUri."""
    agent = AGENTS.get(agent_key)
    if not agent:
        return f"tag:startup-strategy,2025:{agent_key}"

    cached_target = agent.get("target_uri")
    if cached_target:
        return cached_target

    fallback = agent.get("url") or f"tag:startup-strategy,2025:{agent_key}"

    try:
        with httpx.Client(timeout=4) as client:
            response = client.post(f"{agent['url']}manifest")
            if response.status_code == 200:
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                identification = data.get("identification", {}) if isinstance(data, dict) else {}
                speaker_uri = identification.get("speakerUri")
                if speaker_uri:
                    agent["target_uri"] = speaker_uri
                    return speaker_uri
                service_url = identification.get("serviceUrl")
                if service_url:
                    agent["target_uri"] = service_url
                    return service_url
    except Exception as e:
        logger.debug(f"Target URI resolution failed for {agent_key}: {e}")

    agent["target_uri"] = fallback
    return fallback


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


def build_utterance_envelope(conv_id: str, speaker_uri: str, service_url: str, target_uri: str, text: str) -> str:
    envelope = Envelope(
        conversation=Conversation(id=conv_id),
        sender=Sender(speakerUri=speaker_uri, serviceUrl=service_url),
        schema=Schema(version="1.1", url="https://openvoicenetwork.org/schema"),
        events=[]
    )

    dialog_event = DialogEvent(speakerUri=speaker_uri)
    text_feature = TextFeature()
    text_feature.tokens = [Token(value=text)]
    dialog_event.features = {"text": text_feature}

    utterance_kwargs = {"dialogEvent": dialog_event}
    if target_uri:
        # BotAgent._is_addressed_to_me() checks event.to, not envelope.to.
        utterance_kwargs["to"] = To(speakerUri=target_uri)

    envelope.events = [UtteranceEvent(**utterance_kwargs)]
    return envelope.to_json(as_payload=True)


def build_floor_control_envelope(
    conv_id: str,
    speaker_uri: str,
    service_url: str,
    target_uri: str,
    event_type: str,
) -> str:
    envelope = Envelope(
        conversation=Conversation(id=conv_id),
        sender=Sender(speakerUri=speaker_uri, serviceUrl=service_url),
        schema=Schema(version="1.1", url="https://openvoicenetwork.org/schema"),
        events=[]
    )

    to_target = To(speakerUri=target_uri)
    if event_type == "grantFloor":
        envelope.events = [GrantFloorEvent(to=to_target)]
    elif event_type == "revokeFloor":
        envelope.events = [RevokeFloorEvent(to=to_target)]
    else:
        raise ValueError(f"Unsupported floor control event type: {event_type}")

    return envelope.to_json(as_payload=True)


def build_invite_envelope(
    conv_id: str,
    speaker_uri: str,
    service_url: str,
    target_uri: str,
) -> str:
    envelope = Envelope(
        conversation=Conversation(id=conv_id),
        sender=Sender(speakerUri=speaker_uri, serviceUrl=service_url),
        schema=Schema(version="1.1", url="https://openvoicenetwork.org/schema"),
        events=[]
    )
    envelope.events = [InviteEvent(to=To(speakerUri=target_uri))]
    return envelope.to_json(as_payload=True)


def send_to_agent(agent_url: str, envelope_json: str, timeout: int = 10) -> str:
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(agent_url, content=envelope_json, headers={"Content-Type": "application/json"})
            if response.status_code != 200:
                return f"[Agent error {response.status_code}]"

            out_envelope = Envelope.from_json(response.text, as_payload=True)
            events = getattr(out_envelope, "events", []) or []
            for event in events:
                if getattr(event, "eventType", None) == "utterance":
                    dialog = getattr(event, "dialogEvent", None)
                    if dialog is None:
                        params = getattr(event, "parameters", None)
                        if params is not None:
                            dialog = getattr(params, "dialogEvent", None)
                            if dialog is None and hasattr(params, "get"):
                                dialog = params.get("dialogEvent")
                    if dialog:
                        features = _field(dialog, "features", {}) or {}
                        text_feature = _field(features, "text")
                        if text_feature:
                            tokens = _field(text_feature, "tokens", []) or []
                            parsed_text = " ".join(
                                (_field(token, "value", "") if not isinstance(token, str) else token)
                                for token in tokens
                            )
                            return _limit_words(parsed_text)
            return "[No utterance in agent response]"
    except Exception as e:
        logger.error(f"Failed to reach agent at {agent_url}: {e}")
        return f"[Agent unreachable: {e}]"


def send_floor_control_event(
    agent_url: str,
    conv_id: str,
    speaker_uri: str,
    service_url: str,
    target_uri: str,
    event_type: str,
    timeout: int = 5,
) -> None:
    try:
        envelope_json = build_floor_control_envelope(
            conv_id=conv_id,
            speaker_uri=speaker_uri,
            service_url=service_url,
            target_uri=target_uri,
            event_type=event_type,
        )
        with httpx.Client(timeout=timeout) as client:
            response = client.post(agent_url, content=envelope_json, headers={"Content-Type": "application/json"})
            if response.status_code != 200:
                logger.warning(f"{event_type} to {agent_url} returned status {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed sending {event_type} to {agent_url}: {e}")


def invite_all_specialists(conv_id: str) -> str:
    speaker_uri = CONVENER_MANIFEST.identification.speakerUri
    service_url = CONVENER_MANIFEST.identification.serviceUrl

    invited = []
    invited_keys = []
    failed = []

    for agent_key in FULL_ANALYSIS_SEQUENCE:
        agent = AGENTS.get(agent_key)
        if not agent:
            failed.append(agent_key)
            continue

        agent_name = agent["name"]
        agent_url = agent["url"]
        target_uri = resolve_agent_target_uri(agent_key)

        try:
            envelope_json = build_invite_envelope(
                conv_id=conv_id,
                speaker_uri=speaker_uri,
                service_url=service_url,
                target_uri=target_uri,
            )
            with httpx.Client(timeout=6) as client:
                response = client.post(agent_url, content=envelope_json, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    invited.append(agent_name)
                    invited_keys.append(agent_key)
                else:
                    failed.append(agent_name)
        except Exception as e:
            logger.warning(f"Invite failed for {agent_name}: {e}")
            failed.append(agent_name)

    _mark_invited_agents(conv_id, invited_keys)

    if invited and not failed:
        return _limit_words(f"Invited all specialists: {', '.join(invited)}.")
    if invited and failed:
        return _limit_words(
            f"Invited: {', '.join(invited)}. Failed: {', '.join(failed)}."
        )
    return _limit_words("Failed to invite specialists.")


def extract_utterance_text(in_envelope: Envelope) -> str:
    events = getattr(in_envelope, "events", []) or []
    for event in events:
        if getattr(event, "eventType", None) == "utterance":
            dialog = getattr(event, "dialogEvent", None)
            if dialog is None:
                params = getattr(event, "parameters", None)
                if params is not None:
                    dialog = getattr(params, "dialogEvent", None)
                    if dialog is None and hasattr(params, "get"):
                        dialog = params.get("dialogEvent")
            if dialog:
                features = _field(dialog, "features", {}) or {}
                text_feature = _field(features, "text")
                if text_feature:
                    tokens = _field(text_feature, "tokens", []) or []
                    return " ".join(
                        (_field(token, "value", "") if not isinstance(token, str) else token)
                        for token in tokens
                    )
    return ""


def run_analysis(
    conv_id: str,
    user_text: str,
    agent_keys: list[str],
    addressed_agent_key: str | None = None,
) -> str:
    speaker_uri = CONVENER_MANIFEST.identification.speakerUri
    service_url = CONVENER_MANIFEST.identification.serviceUrl

    accumulated_context = f"Startup concept: {user_text}\n\n"
    responses = []

    # Addressed prompts are broadcast to every specialist so they all hear the
    # conversation, but only the named agent should reply via the `to` filter.
    delivery_agent_keys = FULL_ANALYSIS_SEQUENCE if addressed_agent_key else agent_keys
    target_uri = resolve_agent_target_uri(addressed_agent_key) if addressed_agent_key else None

    for agent_key in delivery_agent_keys:
        agent = AGENTS.get(agent_key)
        if not agent:
            logger.warning(f"Agent {agent_key} not found")
            continue

        agent_name = agent["name"]
        agent_url = agent["url"]
        message = accumulated_context if agent_key in ("skeptic", "strategy") else user_text
        per_agent_target_uri = resolve_agent_target_uri(agent_key)

        # Explicitly grant floor before each specialist turn.
        send_floor_control_event(
            agent_url=agent_url,
            conv_id=conv_id,
            speaker_uri=speaker_uri,
            service_url=service_url,
            target_uri=per_agent_target_uri,
            event_type="grantFloor",
        )

        logger.info(f"Routing to {agent_name} at {agent_url} (target: {target_uri})")
        envelope_json = build_utterance_envelope(
            conv_id,
            speaker_uri,
            service_url,
            target_uri=target_uri,
            text=message
        )
        response_text = send_to_agent(agent_url, envelope_json)
        if response_text == "[No utterance in agent response]":
            logger.info(f"No response from {agent_name}; message was heard but not addressed there")
            continue
        logger.info(f"Got response from {agent_name}: {response_text[:100]}")

        # Revoke floor immediately after specialist response.
        send_floor_control_event(
            agent_url=agent_url,
            conv_id=conv_id,
            speaker_uri=speaker_uri,
            service_url=service_url,
            target_uri=per_agent_target_uri,
            event_type="revokeFloor",
        )

        header = f"### {agent_name}\n"
        responses.append(header + response_text)
        accumulated_context += f"\n\n{header}{response_text}"

    if not responses:
        return _limit_words("No specialist agents were available to process this request.")
    if len(responses) == 1:
        return _limit_words(responses[0])
    return _limit_words("\n\n---\n\n".join(responses))


app = Flask(__name__)
_conversations: dict = {}
_lock = threading.Lock()


def _mark_invited_agents(conv_id: str, invited_agent_keys: list[str]) -> None:
    if not invited_agent_keys:
        return
    with _lock:
        existing = _conversations.get(conv_id)
        if not isinstance(existing, set):
            existing = set(existing or [])
        existing.update(invited_agent_keys)
        _conversations[conv_id] = existing


def _invited_agents_snapshot() -> dict:
    with _lock:
        return {
            conv_id: sorted(list(agent_keys))
            for conv_id, agent_keys in _conversations.items()
            if isinstance(agent_keys, set) and agent_keys
        }


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
        if event_type == "getManifests":
            publish = PublishManifestsEvent()
            publish.manifests = [CONVENER_MANIFEST]
            out_envelope.events = [publish]
            break
        if event_type == "invite":
            from openfloor.events import AcceptInviteEvent
            out_envelope.events = [AcceptInviteEvent()]
            break
        if event_type == "utterance":
            user_text = extract_utterance_text(in_envelope)
            if not user_text.strip():
                user_text = "Please analyze this startup concept."

            if is_invite_specialists_request(user_text):
                logger.info("Detected invite-specialists intent")
                response_text = invite_all_specialists(conv_id)

                dialog_event = DialogEvent(speakerUri=CONVENER_MANIFEST.identification.speakerUri)
                text_feature = TextFeature()
                text_feature.tokens = [Token(value=response_text)]
                dialog_event.features = {"text": text_feature}
                out_envelope.events = [UtteranceEvent(dialogEvent=dialog_event)]
                break

            addressed_agent_key = detect_addressed_agent(user_text)
            agent_keys = classify_intent(user_text)
            logger.info(
                f"Classified intent for '{user_text[:60]}' -> agents: {agent_keys}; addressed_agent={addressed_agent_key}"
            )
            response_text = _limit_words(
                run_analysis(conv_id, user_text, agent_keys, addressed_agent_key=addressed_agent_key)
            )

            dialog_event = DialogEvent(speakerUri=CONVENER_MANIFEST.identification.speakerUri)
            text_feature = TextFeature()
            text_feature.tokens = [Token(value=response_text)]
            dialog_event.features = {"text": text_feature}
            out_envelope.events = [UtteranceEvent(dialogEvent=dialog_event)]
            break

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
    invited_snapshot = _invited_agents_snapshot()
    invited_agent_keys = sorted({key for keys in invited_snapshot.values() for key in keys})
    invited_agents = [AGENTS[key]["name"] for key in invited_agent_keys if key in AGENTS]
    return {
        "status": "ok",
        "agent": "Startup Strategy Convener",
        "agents": list(AGENTS.keys()),
        "invitedAgentKeys": invited_agent_keys,
        "invitedAgents": invited_agents,
    }


@app.route("/invited-agents", methods=["GET"])
def invited_agents():
    invited_snapshot = _invited_agents_snapshot()
    invited_agents_by_conversation = {
        conv_id: [AGENTS[key]["name"] for key in keys if key in AGENTS]
        for conv_id, keys in invited_snapshot.items()
    }
    return {
        "status": "ok",
        "invitedAgentKeysByConversation": invited_snapshot,
        "invitedAgentsByConversation": invited_agents_by_conversation,
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
