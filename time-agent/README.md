# TimeAgent - World Time Information Agent

An OpenFloor-compliant agent that provides current time information for major cities worldwide.

Built using the agent-template architecture with a customized utterance handler.

## Features

- **Current Time Queries**: Ask for the time in any major city
- **Multiple Cities**: Supports 50+ major cities across all continents
- **Timezone Aware**: Accurate timezone conversion using pytz
- **Natural Language**: Understands various phrasings like "what time is it in Tokyo?"
- **City Listings**: Can list all available cities by region

## Supported Cities

### Americas
New York, Los Angeles, Chicago, Toronto, Mexico City, Vancouver, San Francisco, Miami, Denver, Seattle, Boston

### Europe
London, Paris, Berlin, Madrid, Rome, Amsterdam, Brussels, Vienna, Zurich, Stockholm, Oslo, Copenhagen, Dublin, Moscow, Athens

### Asia
Tokyo, Beijing, Shanghai, Hong Kong, Singapore, Seoul, Bangkok, Mumbai, Delhi, Dubai, Tel Aviv, Jakarta, Manila, Kuala Lumpur

### Oceania
Sydney, Melbourne, Auckland, Brisbane, Perth

### Africa
Cairo, Johannesburg, Lagos, Nairobi

### South America
São Paulo, Buenos Aires, Rio de Janeiro, Lima, Santiago

## Installation

1. **Install dependencies:**
```bash
pip install flask pytz
```

2. **Run the agent:**
```bash
cd time-agent
python flask_server.py
```

The agent will start on http://localhost:8081

## Usage Examples

### Basic Time Query
**User**: "What time is it in London?"
**TimeAgent**: "The current time in London is Monday, January 12, 2026 at 03:45 PM GMT"

### Multiple Cities
**User**: "Time in Tokyo"
**TimeAgent**: "The current time in Tokyo is Tuesday, January 13, 2026 at 12:45 AM JST"

### List Cities
**User**: "List cities"
**TimeAgent**: (Returns organized list of all available cities by region)

### Help
**User**: "Help"
**TimeAgent**: (Returns help message with usage instructions)

## Architecture

This agent uses the standard agent-template architecture:

- **template_agent.py**: Event handling (unchanged from template)
- **envelope_handler.py**: JSON parsing/serialization (unchanged from template)
- **utterance_handler.py**: **Custom time-query logic** (customized for this agent)
- **flask_server.py**: HTTP server (port changed to 8081)
- **agent_config.json**: Manifest configuration (customized for TimeAgent)

## Customization

The only customized file is `utterance_handler.py`, which implements:

1. **City Detection**: Extracts city names from natural language queries
2. **Timezone Lookup**: Maps cities to their timezone identifiers
3. **Time Formatting**: Returns human-readable time strings
4. **Help System**: Provides usage guidance

All OpenFloor protocol handling is managed by the unchanged template files.

## Configuration

**Port**: 8081 (configurable via PORT environment variable)
**Host**: 0.0.0.0 (configurable via HOST environment variable)

To change port:
```bash
PORT=9000 python flask_server.py
```

## Testing with AssistantClient

1. Start TimeAgent:
```bash
cd time-agent
python flask_server.py
```

2. Start AssistantClient:
```bash
cd ../assistantClient
python assistantClient.py
```

3. In AssistantClient:
   - Enter `http://localhost:8081` in the URL field
   - Click "Invite"
   - Type: "What time is it in Paris?"
   - Click "Send Utterance"

## Dependencies

- **Flask**: HTTP server framework
- **pytz**: Timezone database and conversions
- **openfloor**: OpenFloor protocol library (vendored in openfloor/ directory)

## OpenFloor Compliance

This agent is fully OpenFloor compliant and handles all standard events:
- invite/uninvite
- utterance
- getManifests/publishManifests
- grantFloor/revokeFloor
- context
- bye

## License

Part of the Open Voice Network implementation examples.

## Related

- **agent-template**: Base template for building OpenFloor agents
- **assistantClient**: GUI client for testing OpenFloor agents
- **stella**: Example astronomy agent
