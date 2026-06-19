#!/usr/bin/env python3
"""
Shared LLM utility for startup-strategy agents.

All agents use this module to call their configured LLM backend.
Supports Ollama and OpenAI-compatible APIs (OpenAI, LM Studio, etc.)

Configure via environment variables:
  OLLAMA_MODEL   - Ollama model name (default: qwen2.5:14b)
  OLLAMA_HOST    - Ollama API host (default: http://127.0.0.1:11434)
  LLM_BASE_URL   - OpenAI-compatible API base URL (default: OpenAI)
  LLM_API_KEY    - OpenAI API key
  LLM_MODEL      - OpenAI model name (default: gpt-4o-mini)
  LLM_PROVIDER   - 'auto' (try Ollama first, then OpenAI), 'ollama', or 'openai'
"""

import os
import httpx
import json
import logging

logger = logging.getLogger(__name__)

# Ollama configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()

# OpenAI configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


def _ollama_base_url() -> str:
    """Get Ollama API base URL, ensuring /v1 suffix."""
    base_url = OLLAMA_HOST.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


async def chat(system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
    """
    Send a chat completion request to the configured LLM provider(s).
    Tries Ollama first (if enabled), then falls back to OpenAI (if configured).
    Returns the response text, or an error string if all providers fail.
    """
    last_error = None

    # Try Ollama if enabled
    if LLM_PROVIDER in {"auto", "ollama"}:
        try:
            base_url = _ollama_base_url()
            headers = {
                "Content-Type": "application/json",
            }
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
            }
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    data = r.json()
                    response = data["choices"][0]["message"]["content"]
                    logger.info(f"LLM response from Ollama ({OLLAMA_MODEL})")
                    return response
                else:
                    last_error = f"Ollama error {r.status_code}: {r.text[:100]}"
                    logger.warning(last_error)
        except Exception as e:
            last_error = f"Ollama request failed: {e}"
            logger.warning(last_error)

    # Try OpenAI if enabled and Ollama failed or is disabled
    if LLM_API_KEY and LLM_PROVIDER in {"auto", "openai"}:
        try:
            headers = {
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
            }
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    data = r.json()
                    response = data["choices"][0]["message"]["content"]
                    logger.info(f"LLM response from OpenAI ({LLM_MODEL})")
                    return response
                else:
                    last_error = f"OpenAI error {r.status_code}: {r.text[:100]}"
                    logger.warning(last_error)
        except Exception as e:
            last_error = f"OpenAI request failed: {e}"
            logger.warning(last_error)

    # All providers failed
    if last_error:
        logger.error(f"All LLM providers failed: {last_error}")
        if "Ollama" in last_error or LLM_PROVIDER == "ollama":
            return f"[Ollama error: {OLLAMA_MODEL} at {OLLAMA_HOST}]"
        elif "OpenAI" in last_error:
            return "[OpenAI error: check LLM_API_KEY and LLM_MODEL]"
        return f"[LLM call failed: {last_error}]"
    
    return "[No LLM provider configured - set LLM_API_KEY or OLLAMA_HOST]"


def chat_sync(system_prompt: str, user_message: str, temperature: float = 0.3) -> str:
    """Synchronous wrapper around chat() for use in non-async contexts."""
    import asyncio
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # In normal Flask request threads there is no loop; asyncio.run is correct.
        if running_loop and running_loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, chat(system_prompt, user_message, temperature))
                return future.result(timeout=90)
        return asyncio.run(chat(system_prompt, user_message, temperature))
    except Exception as e:
        logger.error(f"chat_sync failed: {e}")
        return f"[LLM call failed: {e}]"
