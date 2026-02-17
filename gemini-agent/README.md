# Gemini OpenFloor Agent

OpenFloor-compliant agent that fronts the Gemini API for geography questions.

## Setup

1. Install dependencies:

```bash
pip install flask google-generativeai
```

2. Set your Gemini API key:

Windows (PowerShell):

```powershell
$env:GEMINI_API_KEY="your_key"
```

macOS/Linux (bash/zsh):

```bash
export GEMINI_API_KEY="your_key"
```

Optional: override the model name with `GEMINI_MODEL` (default is `gemini-1.5-flash-latest`).

## Run

```bash
python flask_server.py
```

Server starts on http://localhost:8769.

## Notes

- Manifest is defined in agent_config.json.
- The OpenFloor library is vendored in openfloor/.
- Utterance logic lives in utterance_handler.py.
