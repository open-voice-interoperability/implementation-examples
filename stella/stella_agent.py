import json
import os
from typing import Optional, List

from openfloor.manifest import Manifest, Identification, Capability, SupportedLayers
from openfloor.agent import BotAgent
from openfloor.envelope import Envelope, Conversation, Sender, Schema, Event as EnvelopeEvent, Parameters
from openfloor.events import UtteranceEvent, InviteEvent, PublishManifestsEvent
from openfloor.dialog_event import DialogEvent, TextFeature, Token, Span
import generate_nasa_gallery as generate_gallery
from generate_nasa_gallery import generate_gallery_html_from_json_obj
import json
import openai
from openai import OpenAI
import nasa_api
from typing import Dict, Any
import re

# Instantiate OpenAI client
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client = OpenAI()


if not client:
    raise ValueError("Please set the OPENAI_API_KEY environment variable.")


def is_html_string(text: str) -> bool:
    """
    Check if a string begins with HTML using a regular expression.
    
    This regex checks for common HTML patterns at the beginning of a string:
    - HTML5 doctype declaration
    - Opening HTML tag
    - Opening head, body, div, span, p, h1-h6, or other common HTML tags
    - Self-closing tags like <br/>, <img/>, etc.
    
    Args:
        text (str): The string to check
        
    Returns:
        bool: True if the string appears to start with HTML, False otherwise
    """
    if not text or not isinstance(text, str):
        return False
    
    # Regex pattern to match HTML at the beginning of a string
    html_pattern = r'^\s*(?:<!DOCTYPE\s+html|<(?:html|head|body|div|span|p|h[1-6]|img|br|a|ul|ol|li|table|tr|td|th|form|input|button|nav|header|footer|section|article|aside|main|figure|figcaption)\b[^>]*>?)'
    
    return bool(re.match(html_pattern, text, re.IGNORECASE))


def load_manifest_from_config(config_path: Optional[str] = None) -> Manifest:
    """Load and normalize a manifest from the project's `assistant_config.json`.

    The repository's `assistant_config.json` uses slightly different property names
    than the Manifest dataclass. This helper maps common keys to the expected
    fields and returns a proper `Manifest` instance.
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "assistant_config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    mf = cfg.get("manifest") or {}
    ident = mf.get("identification") or {}

    # Map known alt-names in the project's config to the Manifest.Identification
    speaker = ident.get("speakerUri") or ident.get("conversationalName") or cfg.get("assistantName") or "urn:stella:assistant"
    service = ident.get("serviceUrl") or ident.get("serviceEndpoint") or ident.get("serviceName") or "https://localhost/"

    identification = Identification(
        speakerUri=speaker,
        serviceUrl=service,
        organization=ident.get("organization") or cfg.get("organization"),
        conversationalName=ident.get("conversationalName") or cfg.get("assistantName"),
        role=ident.get("role"),
        synopsis=ident.get("synopsis")
    )

    caps = mf.get("capabilities") or {}
    # Ensure keyphrases and descriptions are lists
    keyphrases = caps.get("keyphrases") or caps.get("keyphrase") or []
    descriptions = caps.get("descriptions") or []
    languages = caps.get("languages") or None
    supported_layers = caps.get("supportedLayers")

    supported = SupportedLayers(input=["text"], output=["text"])
    if supported_layers:
        # best-effort: if provided as a list, keep it as both input and output
        if isinstance(supported_layers, list):
            supported = SupportedLayers(input=supported_layers, output=supported_layers)

    capability = Capability(
        keyphrases=keyphrases,
        descriptions=descriptions,
        languages=languages,
        supportedLayers=supported
    )

    manifest = Manifest(identification=identification, capabilities=[capability])
    return manifest


class StellaAgent(BotAgent):
    """A small OpenFloor-compatible agent that routes utterances to OpenAI or NASA APIs.

    It subclasses `BotAgent` and overrides the minimal handlers required by the
    OpenFloor spec for a simple bot: invite, utterance and getManifests.
    """


    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        # Load assistant config (if present) and intent concepts
        self._config = None
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "assistant_config.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except Exception:
            self._config = {}

        # OpenAI client (optional)
        self._openai_client: Optional[OpenAI] = None
        try:
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                self._openai_client = OpenAI(api_key=api_key)
        except Exception:
            self._openai_client = None

        # conversation state stored per-conversation id
        self._conversation_state: Dict[str, Dict[str, Any]] = {}

        # load intent concepts from repo file
        self._intent_concepts = None
        try:
            ic_path = os.path.join(os.path.dirname(__file__), 'intentConcepts.json')
            with open(ic_path, 'r', encoding='utf-8') as f:
                self._intent_concepts = json.load(f)
        except Exception:
            self._intent_concepts = {"concepts": []}

    def search_intent(self, input_text: str):
        """Simple intent matcher using intentConcepts.json and keyword rules."""
        matched_intents = []
        input_text_lower = (input_text or "").lower()

        # Simple rule for NASA/space
        if "astronomy" in input_text_lower or "space" in input_text_lower:
            matched_intents.append({"intent": "nasa"})

        # Match configured concepts
        for concept in self._intent_concepts.get("concepts", []):
            examples = concept.get("examples", [])
            matched_words = [word for word in examples if word in input_text_lower]
            if matched_words:
                matched_intents.append({"intent": concept.get("name"), "matched_words": matched_words})

        return matched_intents if matched_intents else None

    def generate_openai_response(self, prompt: str, conv_id: Optional[str] = None) -> str:
        """Call OpenAI to generate a reply. Falls back to a short message if client missing or error."""
        try:
            if not self._openai_client:
                return "I'm sorry — I can't access the language model right now."

            # Build message history
            system_prompt = "You are a helpful astronomy assistant named stella that knows how to access the NASA image API with information about space.  You will generate an API call for the NASA search API that provides image information about the topic of the user's query. You will only provide the exact API call without any other explanation. You will decline to answer questions outside of this domain."
            if self._config and self._config.get("functionPrompt"):
                content = self._config.get("functionPrompt") + " " + system_prompt
            else:
                content = system_prompt
            messages = [
                {"role": "system", "content": content}
            ]

            # Add prior conversation messages if available for this conversation
            if conv_id and conv_id in self._conversation_state and "messages" in self._conversation_state[conv_id]:
                messages.extend(self._conversation_state[conv_id]["messages"])

            messages.append({"role": "user", "content": prompt})


            # Call OpenAI (handle different client SDK shapes)
            nasa_api_to_call = self._openai_client.chat.completions.create(
                model=self._config.get("model", "gpt-4") if self._config else "gpt-4",
                messages=messages,
                max_tokens=200,
                temperature=0.0
            )
            raw_nasa_api_to_call = nasa_api_to_call.choices[0].message.content.strip()
            nasa_api_to_call = re.sub(r'(?s)```\s*GET\s+([^\r\n]+)\s*```', r'GET \1', raw_nasa_api_to_call)
            response = nasa_api.get_nasa(nasa_api_to_call)

            # Robustly extract assistant reply text from various SDK shapes
            def _extract_openai_reply(resp) -> Optional[str]:
                # Try dict-like access
                try:
                    if isinstance(resp, dict):
                        return resp.get("choices", [])[0].get("message", {}).get("content")
                except Exception:
                    pass

                # Try attribute access patterns used by some SDKs
                try:
                    # resp.choices[0].message.content
                    ch0 = getattr(resp, "choices", None)
                    if ch0 and len(ch0) > 0:
                        first = ch0[0]
                        # message may be an object with content attribute
                        msg = getattr(first, "message", None)
                        if msg is not None:
                            # try attribute
                            content = getattr(msg, "content", None)
                            if isinstance(content, str):
                                return content
                            # try mapping-like
                            try:
                                return msg.get("content")
                            except Exception:
                                pass

                        # older SDKs: first.text
                        text = getattr(first, "text", None)
                        if isinstance(text, str):
                            return text
                except Exception:
                    pass

                try:
                   # html_result = generate_gallery_html_from_json_obj(resp, title="NASA Image Results", max_items=25)
                   html_small = generate_gallery_html_from_json_obj(resp, title="NASA", max_items=10, compact=False)
                   # with open("output.html", "w", encoding="utf-8") as f:
                   #     f.write(html_result)         
                   html_clean = re.sub(r'\r?\n', '', html_small)
                   return html_clean                             
                except Exception as e :
                    pass

                # Fallback: try to stringify the response choices
                try:
                    choices = getattr(resp, "choices", None)
                    if choices and len(choices) > 0:
                        # try to get content via several fallbacks
                        first = choices[0]
                        # try mapping
                        try:
                            return first.get("text") or first.get("message", {}).get("content")
                        except Exception:
                            pass
                        # try attributes
                        try:
                            return getattr(first, "text", None) or getattr(getattr(first, "message", None), "content", None)
                        except Exception:
                            pass
                except Exception:
                    pass

                return None

            assistant_reply = _extract_openai_reply(response)

            if assistant_reply is None:
                # If we couldn't extract, produce a sensible fallback message
                return "Error: No valid response received from the language model."

            assistant_reply = assistant_reply.strip()

            # store messages in conversation state
            if conv_id:
                if conv_id not in self._conversation_state:
                    self._conversation_state[conv_id] = {}
                if "messages" not in self._conversation_state[conv_id]:
                    self._conversation_state[conv_id]["messages"] = []
                self._conversation_state[conv_id]["messages"].append({"role": "user", "content": prompt})
                self._conversation_state[conv_id]["messages"].append({"role": "assistant", "content": assistant_reply})

            return assistant_reply
        except Exception as e:
            return f"Error generating response: {str(e)}"

   # These are the minimal incoming event handlers required for a BotAgent
   # Other events that are not expected to be handled by an ordinary bot are left unimplemented
   # These are publishManifests, requestFloor and yieldFloor, declineIInvite
   # variables that track conversation state
    isInConversation: bool = False
    hasSomethingToSay: bool = False
    utteranceInQueue: str = ""
    hasFloor: bool = False
    
    def bot_on_invite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        # Accept the invitation, then send a greeting utterance
        super().bot_on_invite(event, in_envelope, out_envelope)
        name = self._manifest.identification.conversationalName or self._manifest.identification.speakerUri
        greeting = f"Hi, I'm {name}. How can I help with space facts today?"

        dialog = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[greeting])}
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        # Extract the user text robustly
        try:
            # event.parameters may be a Parameters dict or contain dialogEvent directly
            dialog = None
            hasParameters = hasattr(event, "parameters")  
            isparametersDict = isinstance(event.parameters,dict)
            if hasattr(event, "parameters"):
                dialog = event.parameters.get("dialogEvent")
            if dialog is None:
                dialog = getattr(event, "dialogEvent", None)
        except Exception:
            dialog = getattr(event, "dialogEvent", None)

        user_text = None
        if dialog is not None:
            # dialog may be a DialogEvent instance or a dict-like
            if hasattr(dialog, "features"):
                feat = dialog.features.get("text")
                if feat is not None:
                    # Feature may be a TextFeature instance or a plain dict
                    if isinstance(feat, dict):
                        # dict may contain 'values' or 'tokens'
                        vals = feat.get("values")
                        if vals and isinstance(vals, list) and len(vals) > 0:
                            user_text = vals[0]
                        else:
                            tokens = feat.get("tokens") or []
                            if tokens and isinstance(tokens, list) and len(tokens) > 0:
                                # token may be dict or Token instance
                                t0 = tokens[0]
                                if isinstance(t0, dict):
                                    user_text = t0.get("value")
                                else:
                                    user_text = getattr(t0, "value", None)
                    else:
                        # TextFeature or Feature instance: check values then tokens
                        vals = getattr(feat, "values", None)
                        if vals:
                            # vals might be a list
                            try:
                                user_text = vals[0]
                            except Exception:
                                user_text = None
                        else:
                            tokens = getattr(feat, "tokens", None)
                            if tokens and len(tokens) > 0:
                                user_text = getattr(tokens[0], "value", None)
            elif isinstance(dialog, dict):
                try:
                    # dialog dict path
                    user_text = dialog["features"]["text"]["tokens"][0]["value"]
                except Exception:
                    user_text = None

        if user_text is None:
            user_text = ""


        # Maintain conversation state keyed by conversation id
        conv_id = in_envelope.conversation.id if in_envelope and in_envelope.conversation else None
        if conv_id is not None and conv_id not in self._conversation_state:
            self._conversation_state[conv_id] = {}

        reply_text = self.generate_openai_response(user_text, conv_id)

        # Append the assistant's utterance to the outgoing envelope
        dialog_out = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=[reply_text])}
        )
        if reply_text and is_html_string(reply_text):
            # change the mimeType to text/html if the reply looks like HTML
            dialog_out.features["text"].mimeType = "text/html"
        out_envelope.events.append(UtteranceEvent(dialogEvent=dialog_out))

    def bot_on_get_manifests(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        # Respond with the manifest we were constructed with
        out_envelope.events.append(
            PublishManifestsEvent(parameters=Parameters({"servicingManifests": [self._manifest], "discoveryManifests": []}))
        )

    def bot_on_grant_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle grant_floor event.
        
        This event is triggered when the agent is granted the floor to speak.
        Override this method to implement custom floor granting behavior.
        """
        # TODO: Implement grant_floor event handling logic
        # For now, this is just a stub that can be expanded based on requirements
        pass

    def bot_on_decline_invite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle decline_invite event.
        
        This event is triggered when an invitation to join a conversation is declined.
        Override this method to implement custom invitation decline handling.
        """
        # TODO: Implement decline_invite event handling logic
        # For now, this is just a stub that can be expanded based on requirements
        pass

    def bot_on_uninvite(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle uninvite event.
        
        This event is triggered when an agent is uninvited/removed from a conversation.
        Override this method to implement custom uninvite handling.
        """
        # TODO: Implement uninvite event handling logic
        # For now, this is just a stub that can be expanded based on requirements
        pass

    def bot_on_revoke_floor(self, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
        """Handle revoke_floor event.
        
        This event is triggered when the agent's floor permissions are revoked.
        Override this method to implement custom floor revocation handling.
        """
        # TODO: Implement revoke_floor event handling logic
        # For now, this is just a stub that can be expanded based on requirements
        pass

    # Convenience helpers -------------------------------------------------
    def events_for_envelope(self, in_envelope: Envelope) -> List[EnvelopeEvent]:
        """Process the incoming envelope and return the list of outgoing events.

        This leaves the base behavior (returning a full Envelope) intact via
        `process_envelope` but is handy when callers only want the events.
        """
        out_env = super().process_envelope(in_envelope)
        return out_env.events

    def payload_for_envelope(self, in_envelope: Envelope, as_payload: bool = True) -> str:
        """Process the incoming envelope and return the outgoing OpenFloor payload JSON.

        If `as_payload` is True (default) the returned JSON is the OpenFloor wrapper
        matching what clients expect from the HTTP endpoint.
        """
        out_env = super().process_envelope(in_envelope)
        return out_env.to_json(as_payload=as_payload)

    # Backwards-compatibility API ------------------------------------------------
    def generate_response(self, inputOpenFloor, sender_from: Optional[str] = None) -> str:
        """Compatibility wrapper that matches the old assistant.generate_response signature.

        Accepts either a JSON string or a parsed dict representing the OpenFloor wrapper
        and returns the assistant's OpenFloor response JSON (same shape the HTTP
        endpoint returns).
        """
        # Normalize input to JSON string accepted by Envelope.from_json
        try:
            if isinstance(inputOpenFloor, dict):
                payload_text = json.dumps(inputOpenFloor)
            else:
                payload_text = str(inputOpenFloor)

            in_envelope = Envelope.from_json(payload_text, as_payload=True)
        except Exception:
            # If the payload can't be parsed, raise a helpful error
            raise ValueError("Invalid OpenFloor payload passed to generate_response")

        out_envelope = self.process_envelope(in_envelope)
        return out_envelope.to_json(as_payload=True)
