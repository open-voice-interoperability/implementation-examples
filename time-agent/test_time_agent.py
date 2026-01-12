#!/usr/bin/env python3
"""
Simple test script for TimeAgent

Sends test queries to the running TimeAgent server and displays responses.
"""

import requests
import json

AGENT_URL = "http://localhost:8081"


def send_utterance(text: str):
    """Send an utterance to the agent and display the response."""
    envelope = {
        "openFloor": {
            "schema": {
                "version": "1.1",
                "url": "https://openvoicenetwork.org/schema"
            },
            "conversation": {
                "id": "test-conversation-123"
            },
            "sender": {
                "speakerUri": "http://test-client",
                "serviceUrl": "http://test-client"
            },
            "events": [
                {
                    "eventType": "utterance",
                    "parameters": {
                        "dialogEvent": {
                            "speakerUri": "http://test-client",
                            "features": {
                                "text": {
                                    "mimeType": "text/plain",
                                    "tokens": [{"value": text}]
                                }
                            }
                        }
                    }
                }
            ]
        }
    }
    
    print(f"\n{'='*60}")
    print(f"Query: {text}")
    print('='*60)
    
    try:
        response = requests.post(AGENT_URL, json=envelope)
        
        if response.status_code == 200:
            response_data = response.json()
            events = response_data.get("openFloor", {}).get("events", [])
            
            for event in events:
                if event.get("eventType") == "utterance":
                    params = event.get("parameters", {})
                    dialog = params.get("dialogEvent", {})
                    features = dialog.get("features", {})
                    text_feature = features.get("text", {})
                    tokens = text_feature.get("tokens", [])
                    
                    if tokens:
                        response_text = tokens[0].get("value", "")
                        print(f"TimeAgent: {response_text}")
                    else:
                        print("No response text found")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"Error: {e}")


def main():
    print("TimeAgent Test Script")
    print("=" * 60)
    print(f"Testing TimeAgent at {AGENT_URL}")
    
    # Test various queries
    queries = [
        "What time is it in London?",
        "Time in Tokyo",
        "Current time in New York",
        "What time is it in Sydney?",
        "Time in Paris",
        "List cities",
        "Help"
    ]
    
    for query in queries:
        send_utterance(query)
    
    print(f"\n{'='*60}")
    print("Test complete!")
    print('='*60)


if __name__ == "__main__":
    main()
