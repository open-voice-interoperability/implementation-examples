#!/usr/bin/env python3
"""
Debug launcher for the Cafeteria Ops stack.

Runs the Convener and all 9 specialist agents in ONE process, each Flask
app in its own thread, instead of the separate-subprocess-per-agent
approach run_stack.bat / reset_and_run_stack.ps1 use for normal (non-
debugging) use. That means you can set a breakpoint anywhere under
agents/ or in convener_service/convener.py and hit it directly from a
single "Run and Debug" session -- no attach-to-process step, and no need
to figure out which of ten terminals a given request landed in.

Run directly (F5 in most IDEs), or `python debug_all_agents.py`. Point
your debugger's interpreter at this project's own .venv (see
requirements.txt): .venv\\Scripts\\python.exe on Windows,
.venv/bin/python on macOS/Linux.

Hitting a breakpoint only pauses that one agent's own thread -- the floor
manager and the other agents keep serving requests normally while you're
stopped there.

Ctrl+C (or Stop in the debugger) shuts every agent down together, since
they're daemon threads of this one process.
"""

import os
import socket
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.base_strategy_agent import make_flask_app
from agents.inventory_specialist import InventoryAgent
from agents.menu_designer import MenuDesignerAgent
from agents.menu_optimization_specialist import MenuOptimizationAgent
from agents.nutrition_specialist import NutritionAgent
from agents.procurement_specialist import ProcurementAgent
from agents.recipe_portion_specialist import RecipePortionAgent
from agents.shopping_list_specialist import ShoppingListAgent
from convener_service.convener import app as convener_app

CONVENER_PORT = 8300

# Org-chart order, matching reset_and_run_stack.ps1's port assignment so
# this launcher lines up with the rest of the project.
SPECIALIST_CLASSES = [
    MenuDesignerAgent,
    NutritionAgent,
    RecipePortionAgent,
    MenuOptimizationAgent,
    InventoryAgent,
    ProcurementAgent,
    ShoppingListAgent,
]


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _run_flask_app(name: str, app, port: int) -> None:
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except OSError as error:
        print(f"[{name}] could not bind port {port} ({error}) -- is another stack already running? "
              f"Try kill-all-agent-ports.bat first.")
    except Exception as error:
        print(f"[{name}] stopped: {error}")


def main() -> None:
    all_ports = [CONVENER_PORT] + [cls.AGENT_PORT for cls in SPECIALIST_CLASSES]
    busy_ports = [port for port in all_ports if _port_in_use(port)]
    if busy_ports:
        print(f"Warning: port(s) already in use: {busy_ports} -- those agents will fail to "
              f"start below. Run kill-all-agent-ports.bat first if that's an old stack.\n")

    threads = [
        threading.Thread(target=_run_flask_app, args=("Convener", convener_app, CONVENER_PORT),
                          name="convener", daemon=True),
    ]
    for agent_class in SPECIALIST_CLASSES:
        agent = agent_class()
        app = make_flask_app(agent)
        threads.append(threading.Thread(
            target=_run_flask_app, args=(agent_class.AGENT_NAME, app, agent_class.AGENT_PORT),
            name=agent_class.AGENT_NAME, daemon=True,
        ))

    for thread in threads:
        thread.start()

    print(f"Started {len(threads)} agents in-process:")
    print(f"  {'Convener':<32} http://127.0.0.1:{CONVENER_PORT}/")
    for agent_class in SPECIALIST_CLASSES:
        print(f"  {agent_class.AGENT_NAME:<32} http://127.0.0.1:{agent_class.AGENT_PORT}/")
    print("\nCtrl+C (or Stop in the debugger) to shut down.\n")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
