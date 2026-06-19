# Startup Strategy Floor

An OFP multi-agent implementation that provides startup strategy analysis using a panel of specialist agents and live MCP data sources.

A founder describes their startup idea. The convener routes the query to specialist agents on the OFP floor, each of which gathers live data and produces structured analysis. The floor produces a complete strategy brief.

## Agents

| Agent | Port | Role | MCP Data Sources |
|---|---|---|---|
| Convener | 8199 | Routes queries, manages the floor | — |
| Market Validator | 8200 | TAM/SAM/SOM, demand sizing | World Bank, SEC EDGAR (S-1) |
| Competitive Intelligence | 8201 | Competitor mapping, IP landscape | SEC EDGAR (10-K), USPTO |
| Business Model Designer | 8202 | Model options, unit economics | SEC EDGAR (S-1), FRED |
| Risk Identifier | 8203 | Risk register from real disclosures | SEC EDGAR (10-K), FRED |
| Funding Strategist | 8204 | Funding roadmap, milestone plan | FRED, SEC EDGAR, World Bank |
| Workforce Strategist | 8205 | Talent needs, compensation ranges | BLS, World Bank |
| Devil's Advocate | 8206 | Challenges assumptions, fatal flaws | LLM only |
| Strategy Synthesizer | 8207 | 1-page strategy brief + verdict | LLM only |

## MCP Data Sources

All data sources are free with no cost:

| Source | Data | Key Required |
|---|---|---|
| SEC EDGAR | Company filings, S-1s, 10-Ks, risk factors | No |
| World Bank | GDP, economic indicators, country comparisons | No |
| FRED | Interest rates, inflation, macro conditions | Free key at fred.stlouisfed.org |
| BLS | Labor costs, unemployment, wage benchmarks | Optional free key |
| USPTO | Patent filings, landscape, IP holders | No |

## Prerequisites

- Python 3.11+
- An OpenAI-compatible API key (or local Ollama)
- `openfloor` Python package

## Setup

```bash
cd implementation-examples/startup-strategy
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set LLM_API_KEY
```

## Run

Start all agents (each in a separate terminal, or use a process manager):

```bash
# Terminal 1 — Market Validator
PORT=8200 python agents/market_agent.py

# Terminal 2 — Competitive Intelligence
PORT=8201 python agents/competitive_agent.py

# Terminal 3 — Business Model Designer
PORT=8202 python agents/business_model_agent.py

# Terminal 4 — Risk Identifier
PORT=8203 python agents/risk_agent.py

# Terminal 5 — Funding Strategist
PORT=8204 python agents/funding_agent.py

# Terminal 6 — Workforce Strategist
PORT=8205 python agents/workforce_agent.py

# Terminal 7 — Devil's Advocate
PORT=8206 python agents/skeptic_agent.py

# Terminal 8 — Strategy Synthesizer
PORT=8207 python agents/strategy_agent.py

# Terminal 9 — Convener (start last)
PORT=8199 python convener.py
```

## Use

Point your OFP client (assistantClient, web-floor, or the OFP test harness) at:

```
http://localhost:8199/
```

### Example prompts

```
I want to build a B2B SaaS platform for restaurant supply chain management.
```

```
Analyze a marketplace connecting freelance nurses with short-staffed hospitals.
```

```
My startup uses AI to automate commercial lease negotiations.
```

The convener will classify the intent and route to the appropriate agents. For a new startup description it runs the full panel in sequence. For follow-up questions it routes to the most relevant agent.

### Follow-up routing examples

| Question | Routes to |
|---|---|
| "How big is the market?" | Market Validator |
| "Who are the main competitors?" | Competitive Intelligence |
| "What business model should we use?" | Business Model Designer |
| "What are the biggest risks?" | Risk Identifier |
| "How much should we raise?" | Funding Strategist |
| "What team do we need?" | Workforce Strategist |
| "What would a VC push back on?" | Devil's Advocate |
| "Give me a summary" | Strategy Synthesizer |

## Architecture

```
User (OFP client)
        |
        v
   Convener (8199)
   classify_intent()
        |
        +-- Market Validator (8200) --> World Bank + EDGAR S-1
        +-- Competitive Intel  (8201) --> EDGAR 10-K + USPTO
        +-- Business Model    (8202) --> EDGAR S-1 + FRED
        +-- Risk Identifier   (8203) --> EDGAR 10-K + FRED
        +-- Funding Strategist (8204) --> FRED + EDGAR + World Bank
        +-- Workforce         (8205) --> BLS
        +-- Devil's Advocate  (8206) --> LLM (reads full context)
        +-- Strategy Synth    (8207) --> LLM (reads full context)
```

Each specialist agent is an independent OFP-compliant Flask server.
The convener sequences them, passing accumulated context to later agents
so the Devil's Advocate and Strategy Synthesizer see all prior analysis.

## Using with Ollama (no API cost)

```bash
# Install and start Ollama
ollama pull llama3.2

# Set env vars
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
LLM_BASE_URL=http://localhost:11434/v1
```

Note: smaller models produce less detailed analysis. `llama3.2` works well for most agents.

## Adding to the OFP test harness

Add the convener to `known_agents.json`:

```json
{"url": "http://localhost:8199/", "conversationalName": "Startup Strategy"}
```
