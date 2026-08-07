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

# Load .env from this file's directory (startup-strategy/.env) if present.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Ollama configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()

# OpenAI configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# Smaller/faster models for latency-sensitive callers that don't need the
# full analysis model's depth (e.g. routing/intent classification -- a
# narrow, low-stakes decision that degrades safely to a regex fallback on
# any failure). CLASSIFIER_LLM_MODEL defaults to a real nano-tier OpenAI
# model since that's always available over the API with no local setup.
# CLASSIFIER_OLLAMA_MODEL defaults to the same model as OLLAMA_MODEL (a
# no-op) rather than guessing a smaller tag, since there's no way to know
# what's actually pulled locally -- set it explicitly in .env (e.g.
# "qwen2.5:3b" or "llama3.2:1b") if you have a smaller model available.
CLASSIFIER_LLM_MODEL = os.getenv("CLASSIFIER_LLM_MODEL", "gpt-4.1-nano")
CLASSIFIER_OLLAMA_MODEL = os.getenv("CLASSIFIER_OLLAMA_MODEL", OLLAMA_MODEL)

LANGUAGE_RESPONSE_POLICY = (
    "Response language rule: respond in the same natural language as the person's own "
    "request or message. Ignore the language of any reference data, filings, or research "
    "snippets included elsewhere in this prompt - those are source material, not an "
    "indicator of the requested response language. If the request's language is unclear, "
    "default to English. Do not translate unless the person explicitly asks you to. This "
    "rule is absolute: never switch languages mid-response, and never let internal "
    "reasoning in another language leak into the final answer - the entire visible "
    "response must be in a single language, chosen per the rule above."
)


def _with_language_response_policy(system_prompt: str) -> str:
    """Append a shared response-language constraint to every agent system prompt."""
    base = (system_prompt or "").strip()
    if not base:
        return LANGUAGE_RESPONSE_POLICY
    if LANGUAGE_RESPONSE_POLICY in base:
        return base
    return f"{base}\n\n{LANGUAGE_RESPONSE_POLICY}"


def _build_chat_messages(system_prompt: str, user_message: str) -> tuple[list[dict[str, str]], str]:
    """Build chat messages with the language policy embedded in the system prompt.

    Language is not pre-detected with regex - the model reads the actual
    request itself and mirrors its language, which handles mixed-language
    prompts and incidental foreign-looking words in embedded reference data
    far more reliably than keyword matching does.
    """
    user_content = user_message.strip()
    messages = [
        {"role": "system", "content": _with_language_response_policy(system_prompt)},
        {"role": "user", "content": user_content},
    ]
    return messages, user_content


def _ollama_base_url() -> str:
    """Get Ollama API base URL, ensuring /v1 suffix."""
    base_url = OLLAMA_HOST.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


async def chat(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    timeout: float | None = None,
    ollama_model: str | None = None,
    openai_model: str | None = None,
) -> str:
    """
    Send a chat completion request to the configured LLM provider(s).
    Tries Ollama first (if enabled), then falls back to OpenAI (if configured).
    Returns the response text, or an error string if all providers fail.

    timeout: per-provider request timeout in seconds. Defaults to 60 (sized
    for deep specialist analysis calls); pass a shorter value for latency-
    sensitive callers like routing/classification, where a slow backend
    should fail over quickly rather than block for the full default.

    ollama_model / openai_model: override the model used on that provider,
    independent of which provider actually ends up handling the call (LLM_PROVIDER
    may be "auto", trying Ollama then OpenAI). Each defaults to the module-level
    OLLAMA_MODEL / LLM_MODEL when not given, so passing neither is a no-op.
    Lets a latency-sensitive caller (e.g. routing/classification) opt into a
    smaller/faster model on whichever provider is actually configured, without
    changing the model deeper analysis calls get.
    """
    messages, _ = _build_chat_messages(system_prompt, user_message)
    request_timeout = timeout if timeout is not None else 60
    effective_ollama_model = ollama_model or OLLAMA_MODEL
    effective_openai_model = openai_model or LLM_MODEL
    last_error = None

    # Try Ollama if enabled
    if LLM_PROVIDER in {"auto", "ollama"}:
        try:
            base_url = _ollama_base_url()
            headers = {
                "Content-Type": "application/json",
            }
            payload = {
                "model": effective_ollama_model,
                "messages": messages,
                "temperature": temperature,
            }
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                r = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    data = r.json()
                    response = data["choices"][0]["message"]["content"]
                    logger.info(f"LLM response from Ollama ({effective_ollama_model})")
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
                "model": effective_openai_model,
                "messages": messages,
                "temperature": temperature,
            }
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                r = await client.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if r.status_code == 200:
                    data = r.json()
                    response = data["choices"][0]["message"]["content"]
                    logger.info(f"LLM response from OpenAI ({effective_openai_model})")
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
            return f"[Ollama error: {effective_ollama_model} at {OLLAMA_HOST}]"
        elif "OpenAI" in last_error:
            return "[OpenAI error: check LLM_API_KEY and LLM_MODEL]"
        return f"[LLM call failed: {last_error}]"

    return "[No LLM provider configured - set LLM_API_KEY or OLLAMA_HOST]"


def chat_sync(
    system_prompt: str,
    user_message: str,
    temperature: float = 0.3,
    timeout: float | None = None,
    ollama_model: str | None = None,
    openai_model: str | None = None,
) -> str:
    """Synchronous wrapper around chat() for use in non-async contexts.

    timeout, ollama_model, openai_model: see chat(). timeout also bounds the
    outer thread-pool wait (with a small buffer for two sequential provider
    attempts) when called from inside a running event loop.
    """
    import asyncio
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        # In normal Flask request threads there is no loop; asyncio.run is correct.
        if running_loop and running_loop.is_running():
            import concurrent.futures
            future_timeout = (timeout * 2 + 5) if timeout is not None else 90
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run, chat(system_prompt, user_message, temperature, timeout, ollama_model, openai_model)
                )
                return future.result(timeout=future_timeout)
        return asyncio.run(chat(system_prompt, user_message, temperature, timeout, ollama_model, openai_model))
    except Exception as e:
        logger.error(f"chat_sync failed: {e}")
        return f"[LLM call failed: {e}]"


def generate_image_sync(prompt: str, size: str = "1024x1024") -> str:
    """
    Generate an image and return it as a base64 data URI.
    Tries gpt-image-1 then dall-e-3. Handles both URL and b64_json responses.
    Returns empty string if unavailable or on failure.
    """
    if not LLM_API_KEY or LLM_PROVIDER == "ollama":
        logger.debug("Image generation skipped: no API key or Ollama-only mode")
        return ""
    try:
        import base64 as _base64
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=120) as client:
            for model in ["gpt-image-1", "dall-e-3"]:
                payload: dict = {"model": model, "prompt": prompt, "n": 1, "size": size}
                r = client.post(f"{LLM_BASE_URL}/images/generations", headers=headers, json=payload)
                if r.status_code == 400 and ("does not exist" in r.text or "not exist" in r.text):
                    continue  # try next model
                if r.status_code == 200:
                    item = r.json()["data"][0]
                    if "b64_json" in item:
                        logger.info(f"Image generated via {model} (b64)")
                        return f"data:image/png;base64,{item['b64_json']}"
                    if "url" in item:
                        img_r = client.get(item["url"], timeout=30)
                        if img_r.status_code == 200:
                            b64 = _base64.b64encode(img_r.content).decode()
                            logger.info(f"Image generated via {model} (url→b64)")
                            return f"data:image/png;base64,{b64}"
                logger.warning(f"Image generation ({model}) returned {r.status_code}: {r.text[:120]}")
                break  # non-model error; don't retry
    except Exception as e:
        logger.warning(f"Image generation failed: {e}")
    return ""
