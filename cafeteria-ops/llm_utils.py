#!/usr/bin/env python3
"""
Shared LLM utility for cafeteria-ops agents.

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

# Load .env from this file's directory (cafeteria-ops/.env) if present.
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


# Hugging Face Inference Providers (image generation only) -- a free-tier
# alternative to OpenAI's paid image endpoint, same "prefer free, fall
# back to paid" split as chat()'s Ollama-then-OpenAI order. HF_IMAGE_MODEL
# defaults to the model HF's own docs list as served by its free
# "hf-inference" provider (as opposed to third-party providers like
# fal-ai/replicate, which need their own separate billing setup).
HF_API_KEY = os.getenv("HF_API_KEY", "")
HF_IMAGE_MODEL = os.getenv("HF_IMAGE_MODEL", "stabilityai/stable-diffusion-3-medium-diffusers")
HF_INFERENCE_BASE = "https://api-inference.huggingface.co/models"

# Which image provider(s) to try, and in what order: 'auto' (Hugging Face
# first, then OpenAI), 'huggingface', or 'openai'.
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "auto").strip().lower()

# A menu illustration is shown at most 200px wide in the report popup (see
# menu_designer_agent.py's _entry_html) -- generating/keeping it at a
# provider's native 1024x1024 wastes bandwidth for no visible benefit (a
# single image came back ~2.5MB base64-encoded as PNG at that size, live-
# tested). IMAGE_MAX_DIMENSION bounds the final image's longer side;
# _shrink_data_uri also re-encodes as JPEG, which compresses a
# photographic image far better than PNG.
IMAGE_MAX_DIMENSION = int(os.getenv("IMAGE_MAX_DIMENSION", "400"))
_IMAGE_JPEG_QUALITY = 80


def _shrink_data_uri(data_uri: str, max_dimension: int = IMAGE_MAX_DIMENSION, quality: int = _IMAGE_JPEG_QUALITY) -> str:
    """Downscale and JPEG-recompress a base64 image data URI. Returns the
    input unchanged (rather than raising) if it isn't a data URI or can't
    be decoded -- shrinking is a size optimization, never a hard
    requirement for the image to be usable."""
    if not data_uri.startswith("data:") or ";base64," not in data_uri:
        return data_uri
    try:
        import base64 as _base64
        import io as _io
        from PIL import Image as _Image

        _, b64_data = data_uri.split(";base64,", 1)
        raw = _base64.b64decode(b64_data)
        image = _Image.open(_io.BytesIO(raw)).convert("RGB")
        image.thumbnail((max_dimension, max_dimension), _Image.LANCZOS)
        buffer = _io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        shrunk_b64 = _base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/jpeg;base64,{shrunk_b64}"
    except Exception as e:
        logger.warning(f"Image shrink failed, using original: {e}")
        return data_uri


def _generate_image_huggingface(prompt: str) -> str:
    """One image via Hugging Face's Inference Providers API, as a base64
    data URI, or "" if unconfigured/unavailable. The API returns raw
    image bytes directly (not JSON) on success. Requested at
    IMAGE_MAX_DIMENSION natively (most diffusion models support this via
    width/height) so there's less to generate and shrink in the first
    place; _shrink_data_uri is still applied afterward for a consistent
    final size/format regardless of whether the model honored the hint."""
    if not HF_API_KEY:
        return ""
    try:
        import base64 as _base64
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        payload = {
            "inputs": prompt,
            "parameters": {"width": IMAGE_MAX_DIMENSION, "height": IMAGE_MAX_DIMENSION},
        }
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{HF_INFERENCE_BASE}/{HF_IMAGE_MODEL}", headers=headers, json=payload)
            content_type = r.headers.get("content-type", "")
            if r.status_code == 200 and content_type.startswith("image/"):
                b64 = _base64.b64encode(r.content).decode()
                logger.info(f"Image generated via Hugging Face ({HF_IMAGE_MODEL})")
                return f"data:{content_type};base64,{b64}"
            logger.warning(f"Hugging Face image generation ({HF_IMAGE_MODEL}) returned {r.status_code}: {r.text[:150]}")
    except Exception as e:
        logger.warning(f"Hugging Face image generation failed: {e}")
    return ""


def _generate_image_openai(prompt: str, size: str) -> str:
    """One image via an OpenAI-compatible /images/generations endpoint, as
    a base64 data URI, or "" if unconfigured/unavailable. Tries
    gpt-image-1 then dall-e-3; handles both url and b64_json responses."""
    if not LLM_API_KEY or LLM_PROVIDER == "ollama":
        logger.debug("OpenAI image generation skipped: no API key or Ollama-only mode")
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
                if model == "gpt-image-1":
                    # gpt-image-1's default quality is slow (this was the
                    # dominant cost in Menu Designer's turn) -- "low" is
                    # meaningfully faster and cheaper at some cost to
                    # fidelity. dall-e-3 has no equivalent "low" value
                    # (only "standard"/"hd"), so this is only set here.
                    payload["quality"] = "low"
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
        logger.warning(f"OpenAI image generation failed: {e}")
    return ""


def generate_image_sync(prompt: str, size: str = "1024x1024") -> str:
    """
    Generate an image and return it as a base64 data URI, or "" if
    unavailable/failed on every configured provider.

    Tries Hugging Face's free Inference Providers API first (if HF_API_KEY
    is set and IMAGE_PROVIDER allows it), then falls back to an
    OpenAI-compatible /images/generations call -- same "prefer free, fall
    back to paid" order as chat()'s Ollama-then-OpenAI split.
    """
    if IMAGE_PROVIDER in {"auto", "huggingface"} and HF_API_KEY:
        image = _generate_image_huggingface(prompt)
        if image:
            return _shrink_data_uri(image)
        if IMAGE_PROVIDER == "huggingface":
            return ""

    if IMAGE_PROVIDER not in {"auto", "openai"}:
        return ""

    image = _generate_image_openai(prompt, size)
    return _shrink_data_uri(image) if image else image
