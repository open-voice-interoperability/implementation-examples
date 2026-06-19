#!/usr/bin/env python3
"""
MCP Client — thin synchronous wrapper for calling MCP tool servers.

Each MCP server runs as a separate process via stdio transport.
This client spawns them on demand and caches the connections.
"""

import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Map server name -> script path
MCP_SERVERS = {
    "edgar": os.path.join(os.path.dirname(__file__), "mcp", "edgar_mcp.py"),
    "worldbank": os.path.join(os.path.dirname(__file__), "mcp", "worldbank_mcp.py"),
    "fred": os.path.join(os.path.dirname(__file__), "mcp", "fred_mcp.py"),
    "bls": os.path.join(os.path.dirname(__file__), "mcp", "bls_mcp.py"),
    "uspto": os.path.join(os.path.dirname(__file__), "mcp", "uspto_mcp.py"),
}


async def call_tool(server_name: str, tool_name: str, arguments: dict) -> str:
    """
    Call a tool on an MCP server.
    Spawns the server process, calls the tool, returns the result as a string.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = MCP_SERVERS.get(server_name)
    if not script:
        return json.dumps({"error": f"Unknown MCP server: {server_name}"})
    if not os.path.exists(script):
        return json.dumps({"error": f"MCP server script not found: {script}"})

    python_exe = sys.executable
    server_params = StdioServerParameters(command=python_exe, args=[script])

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                # result.content is a list of content blocks
                if result.content:
                    text_parts = [c.text for c in result.content if hasattr(c, "text")]
                    return "\n".join(text_parts)
                return json.dumps({"result": "no content returned"})
    except Exception as e:
        logger.error(f"MCP call {server_name}.{tool_name} failed: {e}")
        return json.dumps({"error": str(e)})


def call_tool_sync(server_name: str, tool_name: str, arguments: dict) -> str:
    """Synchronous wrapper for call_tool."""
    try:
        return asyncio.run(call_tool(server_name, tool_name, arguments))
    except Exception as e:
        logger.error(f"call_tool_sync failed: {e}")
        return json.dumps({"error": str(e)})


def _has_nested_errors(result_obj: object) -> bool:
    if not isinstance(result_obj, dict):
        return False

    if result_obj.get("error"):
        return True

    macro = result_obj.get("macro_snapshot")
    if isinstance(macro, dict) and macro:
        values = list(macro.values())
        if all(isinstance(v, dict) and v.get("error") for v in values):
            return True

    return False


def call_tool_sync_or_none(server_name: str, tool_name: str, arguments: dict) -> str | None:
    """
    Safe MCP wrapper.
    Returns None when tool execution fails or returns an error payload.
    """
    result = call_tool_sync(server_name, tool_name, arguments)
    if not result:
        return None

    lowered = result.strip().lower()
    if lowered.startswith("error executing tool") or lowered.startswith("unknown tool"):
        return None

    try:
        obj = json.loads(result)
        if _has_nested_errors(obj):
            return None
    except Exception:
        # Non-JSON text results are allowed.
        pass

    return result
