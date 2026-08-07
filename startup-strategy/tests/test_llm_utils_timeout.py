import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import llm_utils


def _fake_async_client(captured, response):
    """Build a mock replacing httpx.AsyncClient(timeout=...) that records
    the timeout it was constructed with, and captures the JSON payload
    (including "model") passed to post(), returning `response` from it."""

    def factory(*args, **kwargs):
        captured.setdefault("timeouts", []).append(kwargs.get("timeout"))
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        async def fake_post(*post_args, **post_kwargs):
            captured.setdefault("models", []).append(post_kwargs.get("json", {}).get("model"))
            return response

        client.post = fake_post
        return client

    return factory


class ChatTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def _ok_response(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        return response

    async def test_default_timeout_is_sixty_when_unspecified(self):
        captured = {}
        with patch.object(llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())):
            await llm_utils.chat("system", "hello")

        self.assertTrue(captured["timeouts"])
        self.assertTrue(all(t == 60 for t in captured["timeouts"]))

    async def test_explicit_timeout_is_passed_to_httpx_client(self):
        captured = {}
        with patch.object(llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())):
            await llm_utils.chat("system", "hello", timeout=8)

        self.assertTrue(captured["timeouts"])
        self.assertTrue(all(t == 8 for t in captured["timeouts"]))


class ChatModelOverrideTests(unittest.IsolatedAsyncioTestCase):
    """Forces LLM_PROVIDER explicitly per test rather than relying on the
    ambient .env, since some environments have an OS-level LLM_PROVIDER
    already set that load_dotenv(override=False) won't override -- forcing
    it here keeps the test deterministic regardless of what the environment
    actually has."""

    def _ok_response(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        return response

    async def test_default_openai_model_used_when_unspecified(self):
        captured = {}
        with patch.object(llm_utils, "LLM_PROVIDER", "openai"), patch.object(
            llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())
        ):
            await llm_utils.chat("system", "hello")

        self.assertEqual(captured["models"], [llm_utils.LLM_MODEL])

    async def test_explicit_openai_model_overrides_default(self):
        captured = {}
        with patch.object(llm_utils, "LLM_PROVIDER", "openai"), patch.object(
            llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())
        ):
            await llm_utils.chat("system", "hello", openai_model="gpt-4.1-nano")

        self.assertEqual(captured["models"], ["gpt-4.1-nano"])

    async def test_ollama_model_override_does_not_affect_openai_branch(self):
        # Passing an ollama_model override must not leak into the OpenAI
        # payload when only the OpenAI branch actually runs.
        captured = {}
        with patch.object(llm_utils, "LLM_PROVIDER", "openai"), patch.object(
            llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())
        ):
            await llm_utils.chat("system", "hello", ollama_model="llama3.2:1b", openai_model="gpt-4.1-nano")

        self.assertEqual(captured["models"], ["gpt-4.1-nano"])

    async def test_explicit_ollama_model_overrides_default_on_ollama_branch(self):
        captured = {}
        with patch.object(llm_utils, "LLM_PROVIDER", "ollama"), patch.object(
            llm_utils.httpx, "AsyncClient", _fake_async_client(captured, self._ok_response())
        ):
            await llm_utils.chat("system", "hello", ollama_model="llama3.2:1b", openai_model="gpt-4.1-nano")

        self.assertEqual(captured["models"], ["llama3.2:1b"])


class ChatSyncTimeoutTests(unittest.TestCase):
    def test_chat_sync_forwards_timeout_and_models_to_chat(self):
        with patch.object(llm_utils, "chat", new=AsyncMock(return_value="ok")) as chat_mock:
            result = llm_utils.chat_sync(
                "system", "hello", timeout=8, ollama_model="llama3.2:1b", openai_model="gpt-4.1-nano"
            )

        self.assertEqual(result, "ok")
        args = chat_mock.call_args.args
        # chat(system_prompt, user_message, temperature, timeout, ollama_model, openai_model)
        self.assertEqual(args[3], 8)
        self.assertEqual(args[4], "llama3.2:1b")
        self.assertEqual(args[5], "gpt-4.1-nano")


class ClassifierModelDefaultsTests(unittest.TestCase):
    """CLASSIFIER_LLM_MODEL/CLASSIFIER_OLLAMA_MODEL exist specifically so the
    convener's routing classifier can use a smaller/faster model than the
    one used for full specialist analysis.

    These check the fallback logic against whatever this environment's own
    .env actually has (rather than asserting a hardcoded "unset" default),
    since a real deployment -- including this project's own -- may
    legitimately set CLASSIFIER_OLLAMA_MODEL, and the test shouldn't need
    to fight dotenv/module-reload state to stay valid either way.
    """

    def test_classifier_llm_model_defaults_correctly(self):
        expected = os.environ.get("CLASSIFIER_LLM_MODEL") or "gpt-4.1-nano"
        self.assertEqual(llm_utils.CLASSIFIER_LLM_MODEL, expected)
        self.assertNotEqual(llm_utils.CLASSIFIER_LLM_MODEL, llm_utils.LLM_MODEL)

    def test_classifier_ollama_model_defaults_correctly(self):
        # No safe way to guess a smaller locally-pulled model, so the
        # fallback (when unset) must be a no-op: same as OLLAMA_MODEL.
        expected = os.environ.get("CLASSIFIER_OLLAMA_MODEL") or llm_utils.OLLAMA_MODEL
        self.assertEqual(llm_utils.CLASSIFIER_OLLAMA_MODEL, expected)


if __name__ == "__main__":
    unittest.main()
