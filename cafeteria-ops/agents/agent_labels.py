"""Port -> display name for this project's own agents.

Used only to make the shared conversation-history transcript readable
(see StrategyBotAgent._record_conversation_turn / _conversation_history_text
in base_strategy_agent.py) -- "Menu Designer: Day 1: ..." rather than
"http://127.0.0.1:8301/: Day 1: ...".

Hand-kept in sync with convener_service/convener.py's AGENTS dict, the
same "kept in sync by hand" tradeoff as every other cross-agent port
reference in this project -- there is no shared package between the
convener and the agents it addresses. base_strategy_agent.py is identical
across the repo's OFP example projects; this file is the per-project
seam that keeps it that way.
"""

AGENT_LABELS_BY_PORT = {
    8300: "Convener",
    8301: "Menu Designer",
    8302: "Nutrition Specialist",
    8303: "Recipe & Portion Specialist",
    8304: "Menu Optimization Specialist",
    8305: "Inventory Specialist",
    8306: "Procurement Specialist",
    8310: "Shopping List Specialist",
}
