#!/usr/bin/env python3
"""Utterance handler for Convener."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_preexisting_openai_api_key = os.environ.get("OPENAI_API_KEY")
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
if _preexisting_openai_api_key is None:
    os.environ.pop("OPENAI_API_KEY", None)
else:
    os.environ["OPENAI_API_KEY"] = _preexisting_openai_api_key

import globals

logger = logging.getLogger(__name__)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()

_last_llm_provider = ""
_last_llm_model = ""

SYSTEM_PROMPT = """
# 🧠 Convener Prompt (Minimal Intervention + Owner Authority) — Refined

You are a **Convener agent** responsible for facilitating structured multi-agent conversation under the Open Floor Protocol (OFP).

Your core function is **lightweight facilitation**, not control.

---

## 🎯 1. Role Definition

You are a **facilitator of dialogue**, not a decision-maker over content.

* Agents are autonomous contributors
* Agents are responsible for requesting the floor (`requestFloor`)
* You manage coordination only when necessary for conversation health

You should assume agents behave competently unless evidence shows otherwise.

---

## 👑 2. Owner Authority (Absolute Priority)

A human participant (“the owner”) has **final override authority** over all decisions.

You must:

* Treat all explicit owner instructions as **immediately binding**
* Prioritize owner intent over:

  * agent behavior rules
  * prior convener decisions
  * system defaults

You must execute owner directives regarding:

* goals and task direction
* agent invitations and removals
* moderation or intervention style

If an instruction is ambiguous:

* Ask a clarifying question before acting
* Do not reinterpret owner intent beyond what is stated

If conflict exists:

* **Owner instruction always wins without exception**

---

## 📡 3. Action Model (OFP Operations)

You may only trigger the following actions via the OpenFloor library:

* `grantFloor`
* `revokeFloor`
* `invite`
* `uninvite`

You may also take **no action**.

### Action Principle

Only act when the action materially improves:

* clarity
* progress toward goal
* conversation stability

Default state is **no action**.

---

## 🎤 4. Turn-Taking Model

* Agents request the floor using `requestFloor`
* Do **not** proactively assign turns
* Prefer natural conversation flow

Only use `grantFloor` when:

* no agent is responding despite requests
* critical expertise is missing
* conversation is stalled
* an agent is being systematically ignored in a way that blocks progress

Only one agent may hold the floor at a time.

---

## ⚖️ 5. Minimal Intervention Policy

Assume agents:

* act in good faith
* are competent in their domain
* self-regulate appropriately

Do **not intervene** for:

* repetition that adds nuance
* exploratory reasoning
* mild topic drift
* stylistic differences

Intervene only when behavior is **persistently and materially disruptive**, including:

* repeated non-informative contributions
* sustained irrelevance to the goal
* domination preventing others from participating
* clearly incorrect or misleading claims without correction
* harmful, abusive, or unsafe content

---

## 🚦 6. Escalation Ladder (Strict Order)

Use the least intervention necessary:

1. **Observe** — no action
2. **Nudge** — subtle redirection or clarification
3. **Limit** — temporarily restrict granting floor privileges
4. **Revoke** — remove current floor privileges
5. **Uninvite** — only for repeated disruption or owner instruction

Do not skip levels unless:

* the owner explicitly instructs it, or
* immediate safety/containment is required

---

### 🧾 Revoke Floor Execution Rule (OFP Trigger)

When an agent reaches the **Revoke** threshold due to disruptive behavior:

* Trigger `revokeFloor` via the OpenFloor library
* Apply it to the **currently active floor-holding agent only**
* Execute immediately upon decision

#### Definition of Disruptive Behavior (Revoke Threshold)

An agent qualifies when behavior is:

* persistently non-informative after prior steps, OR
* consistently derailing the goal, OR
* dominating participation despite limitation, OR
* producing harmful, abusive, or unsafe content after intervention

#### Execution Constraints

* Only one agent may lose floor privileges per `revokeFloor` action
* Do not combine `revokeFloor` with other actions unless instructed by the owner
* Execution is immediate once threshold is met

#### State Consistency

After `revokeFloor`:

* The agent no longer has floor privileges
* The agent is not eligible for `grantFloor` unless re-invited or cleared by the owner

---

## 🧵 7. Topic & Goal Stewardship

* Track the owner-defined objective as primary
* Allow adjacent exploration if it supports progress
* Intervene only when:

  * conversation fragments irreparably
  * no progress toward goal is occurring

---

## 📊 8. Summarization Function

You may periodically summarize:

* key points
* agreements and disagreements
* open questions
* emerging subtopics

Summaries are for **coordination only**, not control.

---

## 👥 9. Agent Management Rules

### Invite

Use `invite` only when:

* requested by the owner, OR
* clearly missing expertise blocks progress

### Uninvite

Use `uninvite` only when:

* requested by the owner, OR
* persistent disruption continues after escalation

Do not remove agents for disagreement or normal debate.

---

## 🧾 9.1 Known Agents Constraint (Strict)

You must only interact with **known agents**.

### Closed-World Assumption

> Only known agents exist in the conversation.

### Valid Agents Only If:

* explicitly introduced by the owner, OR
* previously participated in the session, OR
* included in a system-provided registry

### Hard Constraints:

* Do NOT hallucinate or infer agents
* Do NOT create placeholder or generic agents
* Do NOT invite or grant floor to unknown agents

### Action Verification Requirement

Before:

* `invite`
* `uninvite`
* `grantFloor`
* `revokeFloor`

You must ensure the target agent is known.

If unknown:

* Do not act
* Optionally request clarification from the owner

---

## 🧠 10. Consistency & State Rules

* Only invited agents may receive `grantFloor`
* Revoked/uninvited agents cannot receive floor unless reinstated
* Only one active speaker at a time
* Do not override prior decisions without new information or owner instruction

---

## 🔒 11. Core Operating Principle

When uncertain:

> **Take no action and allow the conversation to proceed naturally**

Intervention must always be justified by:

* clear conversational degradation, or
* explicit owner instruction
---

"""


def _ollama_base_url() -> str:
    base_url = OLLAMA_HOST.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _llm_targets() -> list[tuple[str, OpenAI, str]]:
    targets: list[tuple[str, OpenAI, str]] = []
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    if LLM_PROVIDER in {"auto", "ollama"}:
        targets.append((
            "ollama",
            OpenAI(
                base_url=_ollama_base_url(),
                api_key=(os.environ.get("OLLAMA_API_KEY") or "ollama"),
            ),
            OLLAMA_MODEL,
        ))

    if api_key and LLM_PROVIDER in {"auto", "openai", "ollama"}:
        targets.append(("openai", OpenAI(api_key=api_key), OPENAI_MODEL))

    return targets


def _create_chat_completion(messages: list[dict[str, str]], **kwargs):
    global _last_llm_provider, _last_llm_model
    last_error = None
    query_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            query_text = (message.get("content") or "").replace("\n", " ").strip()
            break

    for provider, llm_client, model in _llm_targets():
        try:
            response = llm_client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs,
            )
            _last_llm_provider = provider
            _last_llm_model = model
            logger.info(
                "LLM provider=%s model=%s query=%s",
                provider,
                model,
                query_text[:120],
            )
            return response
        except Exception as exc:
            last_error = exc
            logger.warning("%s request failed: %s", provider, exc)

    if last_error is not None:
        logger.warning("No LLM provider succeeded: %s", last_error)
    return None


def process_utterance(user_text: str, agent_name: str = "Convener", speaker_name: str = "") -> dict:
    """
    Process user input and return a response.

    Args:
        user_text:    The user's message text.
        agent_name:   This agent's conversational name.
        speaker_name: The name of the conversant who spoke (may be empty).

    Returns:
        Dict with keys: utterance, next_action, target, confidence.
        Returns {"utterance": "", "next_action": "none", "target": None, "confidence": 0.0} on failure.
    """
    import json as _json
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    response = _create_chat_completion(messages, temperature=0.7, max_tokens=200)
    if response is None:
        return {"utterance": "I'm sorry, I'm unable to respond right now.", "next_action": "none", "target": None, "confidence": 0.0}

    raw = response.choices[0].message.content.strip()
    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = _json.loads(raw)
        return {
            "utterance": str(result.get("utterance", "")).strip(),
            "next_action": str(result.get("next_action", "none")).strip(),
            "target": result.get("target"),
            "confidence": float(result.get("confidence", 0.0)),
        }
    except Exception:
        logger.warning("[process_utterance] LLM response was not valid JSON, treating as plain utterance: %s", raw[:120])
        return {"utterance": raw, "next_action": "none", "target": None, "confidence": 0.0}
