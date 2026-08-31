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
import threading
import time

# Load .env from this file's directory (cafeteria-ops/.env) if present,
# same as llm_utils.py -- needed so keys like FDC_API_KEY/AMS_API_KEY end up
# in this process's environment and can be passed through to spawned MCP
# server subprocesses below (the MCP SDK's stdio client does NOT inherit the
# parent's environment by default; it only passes a small OS-level allowlist
# such as PATH, so those keys never reach the child unless explicitly given).
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Map server name -> script path
MCP_SERVERS = {
    "usda_fdc": os.path.join(os.path.dirname(__file__), "mcp", "usda_fdc_mcp.py"),
    "usda_ams": os.path.join(os.path.dirname(__file__), "mcp", "usda_ams_mcp.py"),
    "themealdb": os.path.join(os.path.dirname(__file__), "mcp", "themealdb_mcp.py"),
    "web_search": os.path.join(os.path.dirname(__file__), "mcp", "web_search_mcp.py"),
}

# ---------------------------------------------------------------------------
# TTL result cache — avoids re-spawning subprocesses for identical calls
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, str]] = {}  # key -> (timestamp, result)
_CACHE_TTL = 300.0  # 5 minutes


def _cache_key(server_name: str, tool_name: str, arguments: dict) -> str:
    return f"{server_name}:{tool_name}:{json.dumps(arguments, sort_keys=True)}"


def _cache_get(key: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.monotonic() - entry[0]) < _CACHE_TTL:
            return entry[1]
        return None


def _cache_set(key: str, value: str) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


async def call_tool(server_name: str, tool_name: str, arguments: dict) -> str:
    """
    Call a tool on an MCP server.
    Spawns the server process, calls the tool, returns the result as a string.
    Checks the TTL cache first; populates it on a successful call.
    """
    key = _cache_key(server_name, tool_name, arguments)
    cached = _cache_get(key)
    if cached is not None:
        logger.debug(f"MCP cache hit: {server_name}.{tool_name}")
        return cached
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = MCP_SERVERS.get(server_name)
    if not script:
        return json.dumps({"error": f"Unknown MCP server: {server_name}"})
    if not os.path.exists(script):
        return json.dumps({"error": f"MCP server script not found: {script}"})

    python_exe = sys.executable
    server_params = StdioServerParameters(command=python_exe, args=[script], env=dict(os.environ))

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                # result.content is a list of content blocks
                if result.content:
                    text_parts = [c.text for c in result.content if hasattr(c, "text")]
                    value = "\n".join(text_parts)
                else:
                    value = json.dumps({"result": "no content returned"})
        _cache_set(key, value)
        return value
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

    return bool(result_obj.get("error"))


async def _call_tool_safe(server_name: str, tool_name: str, arguments: dict, timeout: float = 12.0) -> str | None:
    """Async version of call_tool_sync_or_none — returns None on any failure or timeout."""
    try:
        result = await asyncio.wait_for(call_tool(server_name, tool_name, arguments), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"MCP call {server_name}.{tool_name} timed out after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"MCP call {server_name}.{tool_name} failed: {e}")
        return None
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
        pass
    return result


async def _call_tools_gather(requests: list[tuple[str, str, dict]], timeout: float) -> list[str | None]:
    tasks = [_call_tool_safe(s, t, a, timeout=timeout) for s, t, a in requests]
    return list(await asyncio.gather(*tasks))


def call_tools_parallel_sync(requests: list[tuple[str, str, dict]], timeout: float = 12.0) -> list[str | None]:
    """
    Run multiple MCP tool calls in parallel inside a single event loop.
    Returns results in the same order as *requests*; failed calls return None.
    Much faster than calling call_tool_sync_or_none() N times sequentially.
    *timeout* caps each individual tool call (default 12 s).
    """
    try:
        return asyncio.run(_call_tools_gather(requests, timeout=timeout))
    except Exception as e:
        logger.error(f"call_tools_parallel_sync failed: {e}")
        return [None] * len(requests)


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
