# Startup Strategy Floor

An Open Floor Protocol (OFP) multi-agent system for startup analysis. A user provides a startup concept, and the convener coordinates specialist agents to evaluate market, competition, business model, risk, funding, workforce, skepticism, and synthesis.

## What Runs

The stack starts these services:

| Service | Port | Purpose |
|---|---|---|
| Convener | 8199 | Routes requests and orchestrates specialist turns |
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

- The convener orchestrates the core analysis sequence on ports 8200-8207.
- Technical Feasibility runs on port 8208 and is available as a known agent for direct/manual use from clients.
- "Invite all specialists" currently targets the core sequence (8200-8207).

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

- Convener endpoint: http://localhost:8199/
- Convener health: http://localhost:8199/health
- Convener invited snapshot: http://localhost:8199/invited-agents

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

Point your OFP client (assistantClient, web-floor, or harness tooling) to:

```text
http://localhost:8199/
```

To use Technical Feasibility directly from client UI pull-downs, ensure your client known-agent list includes:

```json
{"url": "http://localhost:8208/", "conversationalName": "Technical Feasibility"}
```

## Project Files

- convener service: convener_service/convener.py
- startup script: run_stack.bat
- stack reset/start logic: reset_and_run_stack.ps1
- specialist entrypoints: agents/*_agent.py
