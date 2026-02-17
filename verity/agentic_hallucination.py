import os
import json
import pandas as pd
import logging

import openai
from openai import OpenAI


# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler()
    ]
)

# Instantiate OpenAI client
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI()


if not client:
    raise ValueError("Please set the OPENAI_API_KEY environment variable.")


###############################################################################
# 1. LLM Configuration
###############################################################################
model_configs = {
    "Checker": {
        "model": "gpt-4o-mini",
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
        """Calls the OpenAI API to generate a reply based on the provided messages."""
        try:
            messages = [
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": user_message}
            ]
            response = client.chat.completions.create(
                model=self.model_config["model"],
                messages=messages,
                temperature=self.model_config.get("temperature", 0.0),
                max_tokens=self.model_config.get("max_tokens", 200)
            )
            reply = response.choices[0].message.content.strip()
            logging.info(f"{self.name} generated a response.")
            return reply
        except Exception as e:
            logging.error(f"Error in {self.name} generate_reply: {e}")
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
    final_response = "unknown"
   
    try:
            review_response = reviewer_agent.generate_reply(utterance)
            if review_response is None:
                logging.error(f"Response is None for prompt: {utterance}")
                return None, None     
            final_response = review_response

    except Exception as e:
        logging.error(f"Error processing prompt: {e}")
   
    print("Pipeline completed successfully.")
    return(final_response)

