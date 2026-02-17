#!/usr/bin/env python3
"""
Utterance Handler - Customize Your Agent's Conversation Logic

This module handles the core conversation logic for your agent.

This module is intentionally simple and isolated from OpenFloor details.
It only deals with text input and text output.

The process_utterance function receives:
- user_text: The text message from the user
- agent_name: Optional display name for the agent

And returns:
- response_text: The text response to send back

All OpenFloor event parsing and envelope construction is handled by template_agent.py.
"""

import globals


def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
    """
    Process user input and generate a text response.
    
    CUSTOMIZE THIS FUNCTION to implement your agent's behavior.
    This function is intentionally simple - it only handles text.
    
    Args:
        user_text: The user's message (already extracted from OpenFloor event)
        agent_name: Display name for the agent (plain string; no OpenFloor types)
        
    Returns:
        response_text: The response message (will be wrapped in OpenFloor event)
        
    Example implementation patterns:
    
    1. SIMPLE ECHO BOT:
       return f"You said: {user_text}"
       
    2. LLM-POWERED AGENT:
       response = call_openai(user_text)
       return response
       
    3. TASK-ORIENTED AGENT:
       intent = classify_intent(user_text)
       result = execute_task(intent)
       return format_result(result)
       
    4. STATEFUL CONVERSATION:
       agent.conversation_history.append(user_text)
       response = generate_contextual_response(agent.conversation_history)
       return response
    """
    
    # CUSTOMIZE THIS SECTION - Implement your agent's logic here
    
    # Example 1: Simple echo response
    response_text = _generate_echo_response(user_text, agent_name)
    
    # Example 2: Uncomment and implement your custom logic
    # response_text = _call_your_llm(user_text, agent)
    # response_text = _process_intent(user_text, agent)
    # response_text = _execute_task(user_text, agent)
    
    return response_text


# =============================================================================
# HELPER FUNCTIONS - CUSTOMIZE THESE
# =============================================================================

def _generate_echo_response(user_text: str, agent_name: str) -> str:
    """
    Generate a simple echo response.
    
    REPLACE THIS with your actual response generation logic.
    
    Args:
        user_text: The user's input text
        agent: The agent instance (access manifest, state, etc.)
        
    Returns:
        Response text
    """
    return f"{agent_name} received: '{user_text}'"


# =============================================================================
# IMPLEMENT YOUR CUSTOM LOGIC BELOW
# =============================================================================

def _call_your_llm(user_text: str, agent_name: str) -> str:
    """
    Example: Call an LLM API for intelligent responses.
    
    IMPLEMENT THIS to integrate with OpenAI, Anthropic, etc.
    
    Args:
        user_text: User's message
        agent: Agent instance
        
    Returns:
        LLM-generated response
    """
    # Example implementation:
    # import openai
    # response = openai.ChatCompletion.create(
    #     model="gpt-4",
    #     messages=[
    #         {"role": "system", "content": "You are a helpful assistant."},
    #         {"role": "user", "content": user_text}
    #     ]
    # )
    # return response.choices[0].message.content
    
    raise NotImplementedError("LLM integration not implemented")


def _process_intent(user_text: str, agent_name: str) -> str:
    """
    Example: Intent-based processing.
    
    IMPLEMENT THIS for task-oriented agents.
    
    Args:
        user_text: User's message
        agent: Agent instance
        
    Returns:
        Intent-based response
    """
    # Example implementation:
    # intent = classify_intent(user_text)
    # if intent == "greeting":
    #     return "Hello! How can I help you?"
    # elif intent == "question":
    #     return answer_question(user_text)
    # else:
    #     return "I'm not sure how to help with that."
    
    raise NotImplementedError("Intent processing not implemented")


def _execute_task(user_text: str, agent_name: str) -> str:
    """
    Example: Execute a specific task based on user input.
    
    IMPLEMENT THIS for task-execution agents.
    
    Args:
        user_text: User's message
        agent: Agent instance
        
    Returns:
        Task execution result
    """
    # Example implementation:
    # task = parse_task(user_text)
    # result = execute(task)
    # return format_result(result)
    
    raise NotImplementedError("Task execution not implemented")


# =============================================================================
# ADVANCED EXAMPLES
# =============================================================================

# Note: For multi-modal responses (HTML, images, etc.), you can return
# structured data from process_utterance() and handle it in template_agent.py.
# For simple text responses, just return a string as shown above.
