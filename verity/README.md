# Verity - Fact Checking Agent

Verity is an OpenFloor-compliant agent focused on detecting and mitigating hallucinations. It evaluates statements for correctness and can act as a sentinel in conversations.

## Overview

- Purpose: detect incorrect claims and help correct them
- Role: fact checking in multi-agent conversations
- Transport: Flask HTTP server

## Key Files

- `flask_server.py` - HTTP server entry point
- `template_agent.py` - OpenFloor event handling
- `envelope_handler.py` - Envelope parsing/serialization
- `utterance_handler.py` - Verity's fact-checking logic
- `agent_config.json` - Manifest and capabilities

## Quick Start

```bash
python flask_server.py
```

Default server URL is printed on startup.

## Endpoints

- `POST /` - OpenFloor envelope endpoint
- `POST /manifest` - Agent manifest
- `GET /health` - Health check

## Notes

- Verity is designed to spot and correct hallucinations, not to be a general assistant.
- Verity can run as a regular agent or as a sentinel.
- To run as a sentinel, include an utterance in the invite like "join the floor as a sentinel".
- Sentinels respond only when a message triggers one of their conditions; for example, Verity speaks up only if it detects a non-factual message.
- To change identity or capabilities, edit `agent_config.json`.

## License

Same as the parent project. See `../LICENSE`.
