"""Port -> display name for this project's own agents.

Used only to make the shared conversation-history transcript readable
(see StrategyBotAgent._record_conversation_turn / _conversation_history_text
in base_strategy_agent.py) -- "Market Validator: ..." rather than
"http://127.0.0.1:8200/: ...".

Hand-kept in sync with convener_service/convener.py's AGENTS dict, the
same "kept in sync by hand" tradeoff as every other cross-agent port
reference in this project -- there is no shared package between the
convener and the agents it addresses. base_strategy_agent.py is identical
across the repo's OFP example projects; this file is the per-project
seam that keeps it that way.
"""

AGENT_LABELS_BY_PORT = {
    8199: "Convener",
    8200: "Market Validator",
    8201: "Competitive Intelligence",
    8202: "Business Model Designer",
    8203: "Risk Identifier",
    8204: "Funding Strategist",
    8205: "Workforce Strategist",
    8206: "Devil's Advocate",
    8207: "Strategy Synthesizer",
    8208: "Technical Feasibility",
}
