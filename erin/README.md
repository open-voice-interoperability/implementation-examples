# Erin (Hallucination Demo Agent)

Erin is an OpenFloor agent designed for hallucination demonstrations. It intentionally produces at least one incorrect claim in every response to show how verification agents can detect and respond to unreliable answers. Erin is not a general-purpose assistant and should only be used in demo or testing contexts.

## Overview

- Purpose: simulate confidently incorrect answers for hallucination workflows.
- Behavior: always includes at least one incorrect claim, even for yes/no or comparative questions.
- Integration: runs as an OpenFloor-compliant agent with a Flask HTTP server.

## How It Works

Erin uses the standard template structure but customizes the conversation logic in `utterance_handler.py`. The LLM prompt explicitly instructs the model to answer incorrectly while sounding confident and helpful.

## Files

- `flask_server.py` - HTTP server entry point.
- `template_agent.py` - OpenFloor event handling.
- `envelope_handler.py` - Envelope parsing/serialization.
- `utterance_handler.py` - Erin's hallucination demo logic.
- `agent_config.json` - Manifest and capabilities.

## Quick Start

1) Configure the OpenAI API key (required for Erin's LLM response):

Windows (PowerShell):

```bash
setx OPENAI_API_KEY "your-key-here"
```

macOS (zsh):

```bash
export OPENAI_API_KEY="your-key-here"
```

If you want it to persist on macOS, add the export line to your shell profile (for example, `~/.zshrc`).

Linux (bash):

```bash
export OPENAI_API_KEY="your-key-here"
```

If you want it to persist on Linux, add the export line to your shell profile (for example, `~/.bashrc`).

2) Run the server:

```bash
python flask_server.py
```

Default server URL is printed on startup.

## Endpoints

- `POST /` - OpenFloor envelope endpoint.
- `POST /manifest` - Agent manifest.
- `GET /health` - Health check.

## Notes

- Erin is intentionally incorrect by design. Do not use it for real-world answers.
- To change behavior, edit the system prompt in `utterance_handler.py`.
- To update identity/role metadata, edit `agent_config.json`.

## License

Same as the parent project. See `../LICENSE`.
