# OpenFloor Agent Template

A complete, production-ready template for building OpenFloor compliant agents. This template implements all OpenFloor protocol events with best practices and clear extension points.

## 📋 Overview

This template provides a fully functional OpenFloor agent with:
- ✅ Complete implementation of all OpenFloor events
- ✅ Proper floor management
- ✅ Manifest publishing and configuration
- ✅ Multi-agent conversation support
- ✅ Clean separation of concerns (agent framework vs. custom logic)
- ✅ Extensive documentation and examples

## 🏗️ Architecture

Clean separation of concerns across three modules:

```
┌─────────────────────────────────────────────┐
│         envelope_handler.py                 │
│    (Envelope Parsing & JSON Handling)       │
│                                             │
│  • Parse incoming JSON (openfloor lib)      │
│  • Create response envelopes                │
│  • Serialize to JSON (openfloor lib)        │
│  • Validation helpers                       │
└──────────────┬──────────────────────────────┘
               │
               │ Provides envelopes to
               │
┌──────────────▼──────────────────────────────┐
│         template_agent.py                   │
│      (Event Handling Logic Only)            │
│                                             │
│  • All OpenFloor events fully implemented   │
│  • Floor management                         │
│  • Manifest handling                        │
│  • Conversation lifecycle                   │
│  • State management                         │
└──────────────┬──────────────────────────────┘
               │
               │ Delegates utterance processing
               │
┌──────────────▼──────────────────────────────┐
│       utterance_handler.py                  │
│   (Your Custom Conversation Logic)          │
│                                             │
│  • User input processing                    │
│  • Response generation                      │
│  • LLM integration (optional)               │
│  • Task execution (optional)                │
│  • Multi-modal responses                    │
└─────────────────────────────────────────────┘
```

## 📂 Files

- **template_agent.py** - Event handling logic for all OpenFloor events
- **envelope_handler.py** - Envelope parsing and JSON serialization (uses openfloor library)
- **utterance_handler.py** - Customizable conversation logic (implement here!)
- **flask_server.py** - HTTP server entry point for deployment
- **agent_config.json** - Agent configuration and manifest
- **README.md** - This documentation

### Separation of Concerns

- **envelope_handler.py**: All JSON parsing/generation using openfloor library methods
- **template_agent.py**: Pure event handling logic, no JSON manipulation
- **utterance_handler.py**: Your custom business logic, separate from framework
- **flask_server.py**: HTTP transport layer (Flask), uses envelope_handler for all processing

## 🚀 Quick Start

### 1. Copy the Template

```bash
cp -r agent-template my-agent
cd my-agent
```

### 2. Install Dependencies

```bash
pip install flask jsonpath-ng
pip install events==0.5
pip install --index-url https://test.pypi.org/simple/ --no-deps openfloor==0.1.4
```

### 3. Configure Your Agent

Edit `agent_config.json`:

```json
{
  "manifest": {
    "identification": {
      "conversationalName": "MyAgent",
      "speakerUri": "http://localhost:8080",
      "serviceUrl": "http://localhost:8080",
      "organization": "MyOrg",
      "role": "your agent's role",
      "synopsis": "what your agent does"
    },
    "capabilities": {
      "keyphrases": ["keyword1", "keyword2"],
      "languages": ["en-us"],
      "descriptions": ["Agent description"],
      "supportedLayers": ["text", "html"]
    }
  }
}
```

### 4. Implement Your Logic

Edit `utterance_handler.py` to implement your agent's behavior.

`utterance_handler.py` is intentionally OpenFloor-agnostic (no Envelope/Event construction). It only receives plain text and returns plain text:

```python
def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
  # YOUR LOGIC HERE
  return f"{agent_name} received: '{user_text}'"
```

All OpenFloor event parsing and envelope construction happens in `template_agent.py`.

### 5. Run the Server

```bash
python flask_server.py
```

Server starts on http://localhost:8080

#### Configuration Options

```bash
# Custom host and port
HOST=0.0.0.0 PORT=5000 python flask_server.py

# Enable debug mode
DEBUG=true python flask_server.py
```

#### Available Endpoints

- **POST /** - Main OpenFloor envelope endpoint
- **GET /health** - Health check (returns agent status)
- **GET /manifest** - Agent manifest (for discovery)
        speakerUri=agent._manifest.identification.speakerUri,
        features=[TextFeature.from_text(response_text)]
    )
    utterance_response = UtteranceEvent.create(dialog)
    out_envelope.events.append(utterance_response)
```

### 4. Test Your Agent

```python
from template_agent import TemplateAgent, load_manifest_from_config

# Load and create agent
manifest = load_manifest_from_config()
agent = TemplateAgent(manifest)

# Agent is ready to process OpenFloor envelopes!
```

## 🎯 Implemented OpenFloor Events

### Conversation Lifecycle
- ✅ **on_invite** - Agent joins conversation, sends greeting
- ✅ **on_uninvite** - Agent leaves conversation gracefully  
- ✅ **on_decline_invite** - Handle declined invitations
- ✅ **on_bye** - Conversation ending cleanup

### Communication
- ✅ **on_utterance** - Process user messages (delegated to utterance_handler.py)
- ✅ **on_context** - Receive contextual information

### Manifest
- ✅ **on_get_manifests** - Publish agent capabilities
- ✅ **on_publish_manifests** - Receive other agents' capabilities

### Floor Management
- ✅ **on_grant_floor** - Agent granted speaking permission
- ✅ **on_revoke_floor** - Speaking permission revoked
- ✅ **on_yield_floor** - Another agent yields the floor

Note: `requestFloor` is sent by agents to a Floor Manager; this template does not handle it as an inbound event.

## 💡 Customization Examples

### Example 1: Simple Echo Bot

```python
# In utterance_handler.py
def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
  return f"You said: {user_text}"
```

### Example 2: LLM-Powered Agent

```python
# In utterance_handler.py
import openai

def process_utterance(user_text: str, agent_name: str = "Agent") -> str:
    # Call OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_text}
        ]
    )
    return response.choices[0].message.content
```

### Example 3: Multi-Modal Response

For multi-modal responses (HTML/images/etc.), keep the utterance handler protocol-agnostic.
One simple approach is to return a plain string and have `template_agent.py` detect special markers and emit additional OpenFloor features.

## 🔧 Agent State Management

The template includes built-in state tracking:

```python
agent.joinedFloor       # Boolean: Agent joined a floor
agent.grantedFloor      # Boolean: Agent has speaking permission
agent.currentConversation  # String: Current conversation ID
```

Add your own state variables as needed:

```python
def __init__(self, manifest):
    super().__init__(manifest)
    # ... existing code ...
    
    # Add custom state
    self.user_context = {}
```

## 📡 Testing with Floor Manager

The agent is ready to integrate with any OpenFloor Floor Manager. Simply point the Floor Manager to your agent's endpoint (e.g., `http://localhost:8080`).

### Testing with curl

```bash
# Send an utterance
curl -X POST http://localhost:8080 \
print("Response JSON ready")
print(response_json)
import envelope_handler

# Create agent
manifest = load_manifest_from_config()
agent = TemplateAgent(manifest)

# Test with JSON payload (as it would come from a Floor Manager)
test_json = '''
{
  "openFloor": {
    "schema": {
      "version": "1.1",
      "url": "https://openvoicenetwork.org/schema"
    },
    "conversation": {
      "id": "test-123"
    },
    "sender": {
      "speakerUri": "http://test-client",
      "serviceUrl": "http://test-client"
    },
    "events": [
      {
        "eventType": "utterance",
        "id": "msg-456",
        "parameters": {
          "dialogEvent": {
            "features": [
              {
                "featureType": "text",
                "tokens": [
                  {"value": "Hello, agent!"}
                ]
              }
            ]
          }
        }
      }
    ]
  }
}
'''

# Process the request (envelope_handler handles all parsing/serialization)
response_json = envelope_handler.process_request(test_json, agent)

# Parse response to verify
import json
response = json.loads(response_json)
print("Response events:", len(response['openFloor']['events']))

# Or test individual components:
# 1. Parse envelope
in_envelope = envelope_handler.parse_incoming_envelope(test_json)
print(f"Conversation ID: {envelope_handler.extract_conversation_id(in_envelope)}")

# 2. Process with agent
out_envelope = agent.process_envelope(in_envelope)

# 3. Serialize response
response_json = envelope_handler.serialize_envelope(out_envelope)
print("Response JSON ready
## 🧪 Testing

Test the agent directly:

```python
from template_agent import TemplateAgent, load_manifest_from_config
from openfloor.envelope import Envelope
from openfloor.events import UtteranceEvent
from openfloor.dialog_event import DialogEvent, TextFeature

# Create agent
manifest = load_manifest_from_config()
agent = TemplateAgent(manifest)

# Create test envelope
in_envelope = Envelope.create_request(
    sender_endpoint="test-client",
    recipient_endpoint=manifest.identification.serviceEndpoint
)

# Add utterance
dialog = DialogEvent(
    speakerUri="test-user",
    features=[TextFeature.from_text("Hello, agent!")]
)
utterance = UtteranceEvent.create(dialog)
in_envelope.events.append(utterance)

# Process
out_envelope = agent.process_envelope(in_envelope)

# Check response
for event in out_envelope.events:
    print(f"Event type: {event.eventType}")
    if event.eventType == 'utterance':
        # Extract response text
        print(f"Response: {event}")
```

## 📚 Additional Resources

- [OpenFloor Protocol Specification](https://github.com/open-voice-interoperability)
- [Example Implementations](../stella/)
- [Floor Manager Documentation](../assistantClient/)

## 🤝 Contributing

When building on this template:

1. Keep `template_agent.py` focused on OpenFloor protocol
2. Put all custom logic in `utterance_handler.py`
3. Document your customizations
4. Follow OpenFloor best practices

## 📄 License

Same as parent project - see [LICENSE](../LICENSE)

---

**Ready to build your OpenFloor agent!** 🚀

Start by editing `utterance_handler.py` to implement your agent's unique capabilities.
