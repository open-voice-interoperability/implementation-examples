#!/usr/bin/env python3
"""
Simple test script for TimeAgent

Sends test queries to the running TimeAgent server and displays responses.
"""

import requests
import json

import globals
import utterance_handler

AGENT_URL = "http://localhost:8081"


def run_local_intent_tests():
    """Run local (non-server) intent tests against utterance_handler."""
    print("\n" + "=" * 60)
    print("Running local intent tests")
    print("=" * 60)

    original_conversants = globals.number_conversants
    globals.number_conversants = 2

    try:
        test_cases = [
            {
                "name": "Non-time statement should not trigger",
                "input": "the moon is smaller than the earth",
                "expect_empty": True,
            },
            {
                "name": "City-only mention should not trigger",
                "input": "san francisco",
                "expect_empty": True,
            },
            {
                "name": "Time query should trigger",
                "input": "what time is it in san francisco?",
                "expect_contains": "The current time in San Francisco is",
            },
            {
                "name": "Timezone query should trigger",
                "input": "what timezone is san francisco in?",
                "expect_contains": "San Francisco is in the America/Los_Angeles time zone",
            },
            {
                "name": "Timezone query with trailing quote should trigger",
                "input": "what is the time zone for chicago'",
                "expect_contains": "Chicago is in the America/Chicago time zone",
            },
        ]

        for case in test_cases:
            response = utterance_handler.process_utterance(case["input"])
            passed = True

            if case.get("expect_empty"):
                passed = (response == "")
            elif case.get("expect_contains"):
                expected = case["expect_contains"]
                passed = isinstance(response, str) and expected in response

            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {case['name']}")
            print(f"  input: {case['input']}")
            print(f"  response: {response!r}")

            if not passed:
                raise AssertionError(f"Test failed: {case['name']}")

        print("All local intent tests passed.")
    finally:
        globals.number_conversants = original_conversants


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

    run_local_intent_tests()
    
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
