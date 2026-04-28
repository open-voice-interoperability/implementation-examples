import os
import json
import ast
from pathlib import Path
import pandas as pd
import logging

import openai
from openai import OpenAI
from dotenv import load_dotenv

_preexisting_openai_api_key = os.environ.get("OPENAI_API_KEY")
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
if _preexisting_openai_api_key is None:
    os.environ.pop("OPENAI_API_KEY", None)
else:
    os.environ["OPENAI_API_KEY"] = _preexisting_openai_api_key


# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler()
    ]
)
# Prevent httpx/openai from logging request headers (which include the API key)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()

_logger = logging.getLogger(__name__)


def _ollama_base_url() -> str:
    base_url = OLLAMA_HOST.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _llm_targets() -> list[tuple[str, OpenAI, str]]:
    targets: list[tuple[str, OpenAI, str]] = []
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if LLM_PROVIDER in {"auto", "ollama"}:
        targets.append((
            "ollama",
            OpenAI(base_url=_ollama_base_url(), api_key=(os.environ.get("OLLAMA_API_KEY") or "ollama")),
            OLLAMA_MODEL,
        ))
    if api_key and LLM_PROVIDER in {"auto", "openai", "ollama"}:
        targets.append(("openai", OpenAI(api_key=api_key), OPENAI_MODEL))
    return targets


###############################################################################
# 1. LLM Configuration
###############################################################################
model_configs = {
    "Checker": {
        "model": OPENAI_MODEL,
        "temperature": 0.0,
        "max_tokens": 150,
    }
}

###############################################################################
# 2. Classes for Agents
###############################################################################
class LLMIntegrationAgent:
    def __init__(self, name, model_config, system_message):
        self.name = name
        self.model_config = model_config
        self.system_message = system_message

    def generate_reply(self, user_message):
        """Calls the LLM API to generate a reply, trying Ollama first then OpenAI."""
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message}
        ]
        last_error = None
        for provider, llm_client, model in _llm_targets():
            try:
                response = llm_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=self.model_config.get("temperature", 0.0),
                    max_tokens=self.model_config.get("max_tokens", 200)
                )
                reply = response.choices[0].message.content.strip()
                _logger.info("LLM provider=%s model=%s agent=%s", provider, model, self.name)
                return reply
            except Exception as e:
                last_error = e
                _logger.warning("%s request failed for %s: %s", provider, self.name, e)
        _logger.error("No LLM provider succeeded for %s: %s", self.name, last_error)
        return None

# Define agents 

reviewer_agent = LLMIntegrationAgent(
    name="Reviewer",
    model_config=model_configs["Checker"],
    system_message=(
        "Review the input utterance and determine if it can be factual or if factuality doesn't apply. "
        "Factuality doesn't apply to utterances that are unknowable, subjective, opinions, questions, "
        "commands or assertions about the future. If factuality applies, describe any reasons that the "
        "utterance is not factual. However, if factuality does not apply, but the utterance contains a "
        "false presupposition, identify and explain that presupposition. Include explicit disclaimers "
        "wherever content is speculative or fictional to ensure users are aware of its nature. Include "
        "as a Python dict: 'applicable' (yes if factuality applies and no if it doesn't) 'decision' "
        "(whether the utterance is factual or not factual), 'factual_likelihood' (how likely the "
        "utterance is to be factual on a scale of 0 to 1, where 0 is certainly not factual and 1 is "
        "certainly factual), 'explanation' (description of the decision), max 75 words."
    )
)


###############################################################################
# Interactive Execution
###############################################################################


def interactive_process(utterance):
    import json
    # Fallback response as Python dict string that ast.literal_eval can parse
    fallback_dict = {
        'applicable': 'no',
        'decision': 'unknown',
        'factual_likelihood': 0.5,
        'explanation': 'Unable to process utterance at this time.'
    }
   
    try:
        review_response = reviewer_agent.generate_reply(utterance)
        if review_response is None:
            logging.error(f"Response is None for prompt: {utterance}")
            return str(fallback_dict)
        
        # Verify the response can be parsed
        try:
            ast.literal_eval(review_response)
            return review_response
        except (ValueError, SyntaxError):
            logging.error(f"Response not a valid dict: {review_response}")
            return str(fallback_dict)
            
    except Exception as e:
        logging.error(f"Error processing prompt: {e}")
        return str(fallback_dict)
   
    return str(fallback_dict)

