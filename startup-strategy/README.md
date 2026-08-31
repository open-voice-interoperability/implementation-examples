# Startup Strategy Floor

An Open Floor Protocol (OFP) multi-agent system for startup analysis. A user provides a startup concept, and the convener coordinates specialist agents to evaluate market, competition, business model, risk, funding, workforce, skepticism, and synthesis.

## What Runs

The stack starts these services:

| Service | Port | Purpose |
|---|---|---|
| Convener | 8199 | Stateless decision service: tells a floor manager who to invite/grant next |
| Market Validator | 8200 | TAM/SAM/SOM and demand sizing |
| Competitive Intelligence | 8201 | Competitor and positioning analysis |
| Business Model Designer | 8202 | Monetization and model framing |
| Risk Identifier | 8203 | Risk register and failure modes |
| Funding Strategist | 8204 | Raise strategy and milestone planning |
| Workforce Strategist | 8205 | Team, hiring, and labor planning |
| Devil's Advocate | 8206 | Contrarian challenge and downside pressure test |
| Strategy Synthesizer | 8207 | Consolidated recommendation |
| Technical Feasibility | 8208 | Technical implementation and feasibility analysis |

## Current Routing Behavior

The convener is a **stateless decision service**, not an orchestrator: it
makes no outbound HTTP calls of its own. A floor manager (web-floor's
gateway, or any spec-compliant OFP floor manager) owns all conversation/floor
state and calls convener for a decision on each delegated event -- who should
be invited, who gets the floor next, and what question to re-issue alongside
it. Convener recomputes each decision fresh from the conversant roster and
round context it's handed on every call (see `convener_service/convener.py`);
`classify_utterance()` is the only place LLM/regex classification happens,
and it stays a pure function with no state or HTTP dependency.

- The convener drives the core analysis sequence across ports 8200-8207.
- Technical Feasibility runs on port 8208 and is available as a known agent for direct/manual use from clients, but is not part of the core sequence convener drives automatically.
- "Invite all specialists" currently targets the core sequence (8200-8207).

### Known deviations from the OFP spec

- **floorGranted default on invite**: the spec's curation rule defaults a
  newly-invited conversant to `floorGranted: true`. The floor manager
  immediately reconciles this down to `false` via an explicit `revokeFloor`
  right after each invite, and every specialist agent's own local floor gate
  (`agents/base_strategy_agent.py`'s `_handle_invite`) independently defaults
  the same way -- deliberate defense-in-depth against double-answering, not
  an oversight.
- **Concurrency**: the spec's normative sequential-processing rule governs
  the floor manager's event *queue* (processed one at a time, in order), not
  fan-out to multiple recipients of one Pass-Through event. A "grant floor
  to everyone and broadcast one utterance" round delivers to every specialist
  concurrently; only the queue itself is strictly sequential.

## Prerequisites

- Python 3.11+
- Virtual environment support
- Dependencies in requirements.txt
- One LLM provider:
        - Ollama, or
        - OpenAI-compatible API via environment variables

## Setup

Windows PowerShell:

```powershell
cd implementation-examples/startup-strategy
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then edit .env and set your model/provider variables as needed.

## Start the Stack

Recommended (Windows):

```powershell
.\run_stack.bat
```

This calls reset_and_run_stack.ps1, clears existing listeners for the strategy ports, and starts all services (including technical feasibility on 8208).

## Endpoints

- Convener endpoint (raw manual pokes / floor-manager delegation target): http://localhost:8199/
- Convener health: http://localhost:8199/health

Convener holds no conversant/floor state of its own, so there is no
"invited snapshot" endpoint on it -- that state lives on whichever floor
manager is driving the conversation. If you're using web-floor's gateway,
query `GET http://localhost:8090/api/floor/state?conversationId=<id>` instead.

## Example Prompts

```text
Analyze this startup idea: a B2B SaaS platform for restaurant supply chain management.
```

```text
Who are the main competitors and what is the market size?
```

```text
Invite all specialists.
```

```text
Invite the technical feasibility specialist.
```

## LLM Configuration

The shared LLM client in llm_utils.py supports:

- Ollama (default auto path)
- OpenAI-compatible chat completions

Key environment variables:

- LLM_PROVIDER = auto | ollama | openai
- OLLAMA_HOST
- OLLAMA_MODEL
- LLM_BASE_URL
- LLM_API_KEY
- LLM_MODEL

## Data Sources

Specialists may combine model reasoning with MCP-backed and public data integrations depending on agent implementation and environment configuration, including SEC/World Bank/FRED/BLS/USPTO where configured.

## Client Integration

Since convener makes no outbound calls of its own, invite it into a
conversation through a **floor manager** rather than pointing a client
directly at it -- without one, convener's decisions (invite/grant/revoke)
are returned but never actually delivered to anyone. web-floor's gateway
(`implementations/web-floor` in the `floor-implementations` repo) implements
a spec-compliant floor manager; point its browser client at:

```text
http://localhost:8090/
```

and invite convener (`http://localhost:8199/`) into the conversation like
any other agent -- the floor manager detects it as convener automatically
via its manifest's `openFloorRoles.convener` flag.

Convener's own endpoint (`http://localhost:8199/`) still answers raw,
non-delegated pokes directly (e.g. a plain `getManifests`), which is useful
for manual testing without a floor manager in front of it.

To use Technical Feasibility directly from client UI pull-downs, ensure your client known-agent list includes:

```json
{"url": "http://localhost:8208/", "conversationalName": "Technical Feasibility"}
```

## Project Files

- convener service: convener_service/convener.py
- startup script: run_stack.bat
- stack reset/start logic: reset_and_run_stack.ps1
- specialist entrypoints: agents/*_agent.py
