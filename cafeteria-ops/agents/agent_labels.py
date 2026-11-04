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


# Port -> that agent's own AGENT_KEYPHRASES, mirrored here for
# StrategyBotAgent._is_in_scope()'s scope-gate fast-path (base_strategy_
# agent.py): a keyphrase match against THIS agent's own list is normally
# enough to skip the LLM classifier, but if the text ALSO contains another
# agent's keyphrase, that's a strong "wrong specialist" signal (e.g. "is
# Friday's menu balanced across protein and carbs" matches Menu Designer's
# "menu" but also Nutrition's "protein"/"carbs") -- so the fast-path is
# skipped and the classifier decides instead. Reusing each agent's own
# already-curated list here means this stays accurate automatically as
# those lists evolve, instead of a second, separately-maintained "other
# domains' terms" list silently drifting out of date. Hand-kept in sync
# the same way as AGENT_LABELS_BY_PORT above and every other cross-agent
# reference in this project -- there is no shared package between agents.
AGENT_KEYPHRASES_BY_PORT = {
    8301: ["menu design", "design a menu", "design the menu", "plan a menu",
           "plan the menu", "propose a menu", "weekly menu", "lunch menu",
           "menu rotation", "menu theme", "themed menu", "menu concept",
           "menu idea", "dish selection"],
    8302: ["nutrition", "calories", "protein", "fat", "carbs", "sodium",
           "healthy", "macros", "nutrient", "nutritional"],
    8303: ["recipe", "recipes", "portion", "portions", "serving", "serving size",
           "ingredients", "preparation", "cook", "batch", "amounts needed"],
    8304: ["optimize", "optimization", "cost", "waste", "efficiency",
           "ingredient reuse", "variety", "menu mix", "budget"],
    8305: ["inventory", "stock", "stockout", "par level", "overstock",
           "reorder", "shelf life", "spoilage", "count"],
    8306: ["procurement", "sourcing", "purchase", "purchasing", "commodity",
           "price", "pricing", "buy", "contract", "market"],
    8310: ["shopping list", "grocery list", "how much", "ingredients needed",
           "quantities", "buy", "order", "purchase list"],
}
