# Stella - NASA Space Assistant

An intelligent conversational agent that provides information about space and astronomy through NASA's APIs. Stella is built using the OpenFloor protocol for multi-agent conversation systems and leverages OpenAI's GPT models for natural language understanding.

## 🌟 Overview

Stella is a specialized assistant focused on space exploration, astronomy, and NASA's vast collection of astronomical images and data. Right now it just accesses NASA's image repository, but in the future it will be extended to NASA's other API endpoints.

**Note:** Stella is a standard OpenFloor agent and can work with any OpenFloor-compliant Floor Manager. The examples in this documentation use `assistantClient` as one implementation, but Stella can integrate with other Floor Manager implementations. 

## 🚀 Features

- **Natural Language Understanding**: Powered by OpenAI GPT-4o for intelligent conversation
- **NASA API Integration**: Direct access to NASA's image repository
- **Multi-Modal Output**: Supports text and HTML responses
- **OpenFloor Protocol**: Fully compliant with OpenFloor multi-agent conversation standard
- **Dynamic Gallery Generation**: Creates beautiful HTML galleries from NASA image collections


## 📋 Requirements

- Python 3.8+
- OpenAI API key
- NASA API key (optional, defaults to demo key)

### Dependencies

```
Flask==2.3.3,<3.0
flask-cors==3.0.10
gunicorn
jsonpath-ng==1.5.3
openai==1.29.0
requests==2.31.0
httpx==0.24.1
```

## 🏗️ Architecture

### System Overview

The diagram below shows Stella working with the `assistantClient` Floor Manager. Stella can work with any OpenFloor-compliant Floor Manager.

```
┌─────────────────────────────────────────────────────────────┐
│                     Assistant Client                         │
│  (assistantClient - One Example Floor Manager)              │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │      UI      │  │    Floor     │                        │
│  │  Interface   │  │   Manager    │                        │
│  └──────────────┘  └──────────────┘                        │
└────────────────────┬────────────────────────────────────────┘
                     │ OpenFloor Protocol (HTTP/JSON)
                     │
┌────────────────────▼────────────────────────────────────────┐
│                      Stella Agent                            │
│     (Flask Server - deployable locally or on the web)       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          OpenFloor Agent Framework                    │  │
│  │                                                        │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │   Envelope  │  │    Event     │  │  Manifest  │  │  │
│  │  │  Processing │  │   Handlers   │  │  Publisher │  │  │
│  │  └─────────────┘  └──────────────┘  └────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          Stella Core Processing                       │  │
│  │                                                        │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │   Intent    │  │   OpenAI     │  │   NASA     │  │  │
│  │  │  Detection  │  │     LLM      │  │    API     │  │  │
│  │  └─────────────┘  └──────────────┘  └────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │        Response Generation                            │  │
│  │                                                        │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │   Gallery   │  │     HTML     │  │    Text    │  │  │
│  │  │  Generator  │  │   Formatter  │  │  Response  │  │  │
│  │  └─────────────┘  └──────────────┘  └────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────┬────────────────────────────────────────┘
                      │
                      │ HTTPS API Calls
                      │
┌─────────────────────▼────────────────────────────────────────┐
│                  External Services                           │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │  OpenAI API  │         │   NASA APIs  │                 │
│  │   (GPT-4o)   │         │              │                 │
│  └──────────────┘         └──────────────┘                 │
└──────────────────────────────────────────────────────────────┘
```

### Component Flow Diagram

```
User Input
   │
   ▼
┌─────────────────────┐
│ Assistant Client    │
│ - Captures input    │
│ - Creates envelope  │
└──────────┬──────────┘
           │
           │ POST /
           │ (OpenFloor Envelope)
           ▼
┌─────────────────────────────────────────────┐
│ Stella Local Server (local.py)              │
│ - Receives HTTP request                     │
│ - Deserializes envelope                     │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ StellaAgent.process_envelope()              │
│ - Routes to event handlers                  │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ Event Handler (based on event type)         │
│ - on_utterance: User message               │
│ - on_invite: Join conversation             │
│ - on_get_manifests: Return capabilities    │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ Intent Detection & Processing               │
│ - Extract keywords                          │
│ - Match against intentConcepts.json         │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ OpenAI GPT Processing                       │
│ - Function calling                          │
│ - Natural language understanding            │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ NASA API Integration (if needed)            │
│ - get_nasa(): Fetch NASA data               │
│ - Parse and format results                  │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ Response Generation                         │
│ - Text response                             │
│ - HTML gallery (if images)                  │
│ - Create DialogEvent                        │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ Create Response Envelope                    │
│ - Wrap in OpenFloor format                  │
│ - Add metadata                              │
└──────────┬──────────────────────────────────┘
           │
           │ JSON Response
           ▼
┌─────────────────────┐
│ Assistant Client    │
│ - Displays response │
│ - Renders HTML      │
└─────────────────────┘
```

### OpenFloor Envelope Structure

```
┌────────────────────────────────────────────────────┐
│                OpenFloor Envelope                  │
├────────────────────────────────────────────────────┤
│ schema:                                            │
│   └─ version: "1.1"                               │
│   └─ url: "https://openvoicenetwork.org/..."     │
│                                                    │
│ conversation:                                      │
│   └─ id: <uuid>                                   │
│                                                    │
│ sender:                                            │
│   └─ from:                                        │
│       ├─ serviceEndpoint: "http://..."           │
│       └─ conversationalName: "Stella"            │
│                                                    │
│ to:                                                │
│   └─ serviceEndpoint: "http://..."               │
│                                                    │
│ events: [                                          │
│   {                                                │
│     eventType: "utterance" | "invite" | ...       │
│     id: <uuid>                                    │
│     parameters: { ... }                           │
│   }                                                │
│ ]                                                  │
└────────────────────────────────────────────────────┘
```

### Data Flow Example: User Asks About Space Images

```
1. User: "Show me pictures of Mars"
   │
2. assistantClient creates UtteranceEvent
   └─ DialogEvent with text: "Show me pictures of Mars"
   │
3. POST to http://localhost:8767
   └─ OpenFloor envelope with event
   │
4. Stella receives envelope
   └─ Triggers on_utterance handler
   │
5. Intent detection
   └─ Matches: "space", "NASA", "images"
   │
6. OpenAI function call
   └─ Determines: Use NASA API
   │
7. nasa_api.get_nasa()
   └─ Fetches from NASA API
   │
8. generate_gallery_html_from_json_obj()
   └─ Creates HTML gallery
   │
9. Create response DialogEvent
   ├─ TextFeature: "Here are images of Mars..."
   └─ HTMLFeature: <gallery markup>
   │
10. Wrap in OpenFloor envelope
    └─ Return to assistantClient
    │
11. Client renders response
    ├─ Display text
    └─ Render HTML gallery
```

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd stella
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   # Windows PowerShell
   $env:OPENAI_API_KEY = "your-openai-api-key"
   
   # Linux/Mac
   export OPENAI_API_KEY="your-openai-api-key"
   ```

4. **Configure the agent** (optional)
   
   Edit `assistant_config.json` to customize:
   - AI model and parameters
   - Assistant personality and prompts
   - NASA API key
   - Manifest capabilities

## 🚀 Usage

**Note:** Stella can be deployed on the web (e.g., using Vercel or other hosting services). The local endpoint described below is for testing and development purposes.

### Running Locally (Testing)

**Start the Stella server:**
```bash
python local.py
```

The server will start on `http://localhost:8767`

**Run tests:**
```bash
python test_local.py
```

### Running with Assistant Client

1. Start Stella server (in one terminal):
   ```bash
   cd stella
   python local.py
   ```

2. Start the assistant client (in another terminal):
   ```bash
   cd assistantClient
   python assistantClient.py
   ```

3. Open your browser to the assistant client interface

### Using VS Code Tasks

The workspace includes predefined tasks:
- **Run Stella server**: Starts the local Flask server
- **Run test_local**: Runs the test suite
- **Run both**: Starts both Stella and the client

## 📡 API Endpoints

### POST /

**Description**: Main endpoint for processing OpenFloor envelopes

**Request**:
```json
{
  "openFloor": {
    "schema": {
      "version": "1.1",
      "url": "https://openvoicenetwork.org/schema"
    },
    "conversation": {
      "id": "conv-uuid"
    },
    "sender": { ... },
    "events": [
      {
        "eventType": "utterance",
        "id": "event-uuid",
        "parameters": {
          "dialogEvent": {
            "features": [
              {
                "featureType": "text",
                "tokens": [
                  { "value": "Tell me about Mars" }
                ]
              }
            ]
          }
        }
      }
    ]
  }
}
```

**Response**:
```json
{
  "openFloor": {
    "schema": { ... },
    "conversation": { ... },
    "sender": {
      "from": {
        "conversationalName": "Stella",
        "serviceEndpoint": "http://localhost:8767"
      }
    },
    "events": [
      {
        "eventType": "utterance",
        "id": "response-uuid",
        "parameters": {
          "dialogEvent": {
            "features": [
              {
                "featureType": "text",
                "tokens": [...]
              },
              {
                "featureType": "html",
                "mimeType": "text/html",
                "text": "<html>..."
              }
            ]
          }
        }
      }
    ]
  }
}
```

## 📂 Project Structure

```
stella/
├── stella_agent.py          # Main agent implementation
├── local.py                 # Flask server for local deployment
├── server.py                # Production server configuration
├── nasa_api.py             # NASA API integration
├── generate_nasa_gallery.py # HTML gallery generation
├── event_handlers.py        # Event processing logic
├── assistant_config.json    # Configuration and manifest
├── intentConcepts.json      # Intent recognition keywords
├── requirements.txt         # Python dependencies
├── openfloor/              # OpenFloor protocol library
│   ├── agent.py            # Base agent classes
│   ├── envelope.py         # Envelope data structures
│   ├── events.py           # Event definitions
│   ├── manifest.py         # Capability manifest
│   └── dialog_event.py     # Dialog event structures
└── api/                    # Vercel deployment
    └── index.py            # Serverless function
```

## 🔧 Configuration

### assistant_config.json

```json
{
  "AIVendor": "OpenAI",
  "model": "gpt-4o",
  "temperature": "0.0",
  "personalPrompt": "Your personality and behavior guidelines...",
  "functionPrompt": "Your function and capabilities...",
  "assistantName": "Stella",
  "assistantTitle": "Space Expert",
  "manifest": {
    "identification": {
      "conversationalName": "Stella",
      "serviceName": "space assistant",
      "organization": "BeaconForge",
      "serviceEndpoint": "http://localhost:8767",
      "role": "shows astronomical images",
      "synopsis": "sends images from NASA's image libraries"
    },
    "capabilities": {
      "keyphrases": ["space", "NASA", "astronomy", ...],
      "languages": ["en-us"],
      "supportedLayers": ["text", "html"]
    }
  }
}
```

## 🎯 Key Features Explained

### Intent Recognition

Stella uses a keyword-based intent detection system defined in `intentConcepts.json` to identify topics like:
- Space and astronomy
- NASA missions
- Planetary information
- Astronomical images

### OpenFloor Protocol Compliance

Stella implements the full OpenFloor specification:
- **Manifest Publishing**: Advertises capabilities
- **Event Handling**: Processes utterances, invites, and context events
- **Floor Management**: Participates in multi-agent conversations
- **Multi-modal Responses**: Supports text and HTML layers

### NASA API Integration

Direct integration with NASA's APIs:
- Dynamic query construction based on user requests
- Error handling and fallback responses

### HTML Gallery Generation

Automatically generates responsive HTML galleries from NASA image data with:
- Responsive grid layout
- Image metadata and descriptions
- Modal view for detailed examination

## 🧪 Testing

Run the test suite:
```bash
python test_local.py
```

Test files include:
- Envelope creation and parsing
- Event handling
- NASA API integration
- Response generation

## 🚢 Deployment

### Local Deployment
```bash
python local.py
```

### Production Deployment (Vercel)
```bash
vercel deploy
```

### Docker Deployment
```bash
docker build -t stella .
docker run -p 8767:8767 -e OPENAI_API_KEY=your-key stella
```

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

See [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **NASA**: For providing excellent public APIs
- **OpenAI**: For GPT models powering natural language understanding
- **Open Voice Network**: For the OpenFloor protocol specification

## 📞 Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Contact: BeaconForge

## 🔮 Future Enhancements

- [ ] Support for more NASA APIs (Mars Rover Photos, Earth Polychromatic Imaging Camera)
- [ ] Enhanced multi-turn conversation memory

- [ ] Multi-language support
- [ ] Advanced image search and filtering
- [ ] Integration with additional space data sources
- [ ] Real-time event notifications (launches, ISS location)

---

**Stella** - Your gateway to the cosmos 🌌
