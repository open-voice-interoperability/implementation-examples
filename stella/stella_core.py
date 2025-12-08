"""
Core business logic and AI integration for StellaAgent.

This module contains the AI processing, intent matching, and response generation
logic separated from the OpenFloor event handling.
"""

import os
import json
import re
from typing import Dict, Any, Optional
from openai import OpenAI
import nasa_api
import generate_nasa_gallery


class StellaCore:
    """Core business logic for Stella agent."""
    
    def __init__(self):
        """Initialize the core processing components."""
        self._config = self._load_config()
        self._openai_client = self._init_openai_client()
        self._intent_concepts = self._load_intent_concepts()
        self._conversation_state: Dict[str, Dict[str, Any]] = {}
    
    def _load_config(self) -> dict:
        """Load assistant configuration."""
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "assistant_config.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _init_openai_client(self) -> Optional[OpenAI]:
        """Initialize OpenAI client if API key is available."""
        try:
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                return OpenAI(api_key=api_key)
        except Exception:
            pass
        return None
    
    def _load_intent_concepts(self) -> dict:
        """Load intent concepts for processing."""
        try:
            ic_path = os.path.join(os.path.dirname(__file__), 'intentConcepts.json')
            with open(ic_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"concepts": []}
    
    def search_intent(self, input_text: str) -> list:
        """Simple intent matcher using intentConcepts.json and keyword rules."""
        matched_intents = []
        input_text_lower = (input_text or "").lower()
        
        for concept in self._intent_concepts.get("concepts", []):
            concept_name = concept.get("name", "")
            keywords = concept.get("keywords", [])
            
            for keyword in keywords:
                if keyword.lower() in input_text_lower:
                    if concept_name not in matched_intents:
                        matched_intents.append(concept_name)
                    break
        
        return matched_intents
    
    def generate_response(self, user_input: str, conversation_id: str = "default") -> str:
        """Generate response to user input using AI and intent matching."""
        print(f"Processing input: {user_input}")
        
        # Initialize conversation state if needed
        if conversation_id not in self._conversation_state:
            self._conversation_state[conversation_id] = {
                "messages": [],
                "context": {}
            }
        
        state = self._conversation_state[conversation_id]
        
        # Check for NASA-related intents
        intents = self.search_intent(user_input)
        nasa_intents = [intent for intent in intents if 'nasa' in intent.lower()]
        
        if nasa_intents or any(keyword in user_input.lower() for keyword in ['nasa', 'space', 'astronomy', 'mars', 'rover']):
            return self._handle_nasa_request(user_input, state)
        
        # Default to OpenAI processing
        if self._openai_client:
            return self._handle_openai_request(user_input, state)
        
        # Fallback response
        return "I'm here to help! You can ask me about NASA space missions or general questions."
    
    def _handle_nasa_request(self, user_input: str, state: dict) -> str:
        """Handle NASA-related requests."""
        try:
            # Use NASA API to get relevant data
            nasa_data = nasa_api.search_nasa_content(user_input)
            
            if nasa_data:
                # Generate gallery if we have image data
                if 'collection' in nasa_data and 'items' in nasa_data['collection']:
                    html_response = generate_nasa_gallery.generate_gallery_html_from_json_obj(nasa_data)
                    if html_response:
                        return html_response
                
                # Fallback to text response
                return self._format_nasa_text_response(nasa_data)
            
        except Exception as e:
            print(f"NASA API error: {e}")
        
        return "I couldn't retrieve NASA data at the moment. Please try again later."
    
    def _handle_openai_request(self, user_input: str, state: dict) -> str:
        """Handle general requests using OpenAI."""
        try:
            # Add user message to conversation history
            state["messages"].append({"role": "user", "content": user_input})
            
            # Generate response
            response = self._openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are Stella, a helpful AI assistant with expertise in space and astronomy."},
                    *state["messages"][-10:]  # Keep last 10 messages for context
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            assistant_message = response.choices[0].message.content
            state["messages"].append({"role": "assistant", "content": assistant_message})
            
            return assistant_message
            
        except Exception as e:
            print(f"OpenAI error: {e}")
            return "I'm having trouble processing that request. Could you please try again?"
    
    def _format_nasa_text_response(self, nasa_data: dict) -> str:
        """Format NASA data as text response."""
        try:
            if 'collection' in nasa_data and 'items' in nasa_data['collection']:
                items = nasa_data['collection']['items'][:3]  # Limit to first 3 items
                response_parts = ["Here's what I found from NASA:"]
                
                for item in items:
                    data = item.get('data', [{}])[0]
                    title = data.get('title', 'Unknown')
                    description = data.get('description', '')[:200] + '...' if len(data.get('description', '')) > 200 else data.get('description', '')
                    response_parts.append(f"\n• {title}: {description}")
                
                return "\n".join(response_parts)
        except Exception as e:
            print(f"Error formatting NASA response: {e}")
        
        return "I found some NASA content but couldn't format it properly."


def is_html_string(text: str) -> bool:
    """
    Check if a string begins with HTML using a regular expression.
    
    Returns:
        bool: True if the string appears to start with HTML, False otherwise
    """
    if not text or not isinstance(text, str):
        return False
    
    html_pattern = r'^\s*(?:<!DOCTYPE\s+html|<(?:html|head|body|div|span|p|h[1-6]|img|br|a|ul|ol|li|table|tr|td|th|form|input|button|nav|header|footer|section|article|aside|main|figure|figcaption)\b[^>]*>?)'
    
    return bool(re.match(html_pattern, text.strip(), re.IGNORECASE))