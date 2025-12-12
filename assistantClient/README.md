# Assistant Client

A graphical user interface (GUI) application for coordinating multi-agent conversations using the OpenFloor Protocol. This client enables users to interact with multiple conversational AI agents simultaneously, managing conversation flow, floor control, and agent invitations.

![Assistant Client Interface](clientInterface.png)
*Example: Assistant Client interface with two agents (Stella and Verity) on the floor*

## Overview

The Assistant Client acts as a conversation coordinator (convener) that:
- Connects to multiple OpenFloor-compatible agents
- Manages conversational floor (who can speak when)
- Sends user utterances to agents
- Displays agent responses in a unified interface
- Handles invite/uninvite, grant/revoke floor operations
- Supports both broadcast and private messaging
- Displays HTML responses in browser window

## Architecture

The application uses a modular architecture with three main components:

### 1. `assistantClient.py` (728 lines)
**Main coordinator and application entry point**
- Initializes the GUI and manages global state
- Handles agent management (add, update, invite, uninvite)
- Coordinates event sending to agents
- Manages floor operations (grant/revoke)
- Maintains conversation history and agent lists

**Key Components:**
- Global conversation state management
- Agent tracking (invited agents, revoked agents, checkboxes)
- Floor manager integration
- Event envelope construction

### 2. `ui_components.py` (281 lines)
**User interface layer**
- Creates all GUI elements using CustomTkinter
- Handles UI display and updates
- Manages conversation history display
- Provides HTML response rendering in browser
- Handles JSON response display

**Key Components:**
- Text entry and send button
- Conversation history textbox
- Agent URL combobox
- Agent checkboxes with floor control buttons
- Event viewer and floor status display

### 3. `event_handlers.py` (292 lines)
**Three-phase message processing engine**
- **Phase 1: Broadcast** - Send messages to all target agents
- **Phase 2: Process** - Handle responses and update UI
- **Phase 3: Forward** - Recursively forward responses between agents

**Key Features:**
- Robust error handling (connection errors, timeouts)
- Response deduplication
- Speaker identification and name resolution
- Manifest processing and agent registration
- Floor manager integration

## Setup

### Prerequisites
- Python 3.11+
- Required libraries (see Installation)

### Installation

**Install dependencies:**
```bash
pip install customtkinter CTkMessagebox requests
```

Optional (for HTML display):
```bash
pip install tkhtmlview
```

**Run the application:**
```bash
python assistantClient.py
```

## Usage

### Starting a Conversation

1. **Launch the application**
   ```bash
   python assistantClient.py
   ```

2. **Add agent URLs**
   - Enter agent URL in the combobox (e.g., `http://localhost:8767`)
   - Press Enter or click "Get Manifests" to discover agent capabilities

3. **Invite agents**
   - Select an agent URL from the dropdown
   - Click "Invite" button
   - Agent will appear in the agents list with a checkbox

4. **Send utterances**
   - Type your message in the text entry field
   - Click "Send Utterance" (only enabled when agents are invited)
   - Messages are sent to all checked (invited) agents

### Floor Management

The client includes an optional floor manager for controlling conversation turn-taking:

**Start Floor Manager:**
- Click "Start Floor" button to initialize floor management
- Floor status will display current holder and state

**Grant Floor:**
- Click "Grant Floor" button next to an agent
- Only the agent with floor can respond to utterances

**Revoke Floor:**
- Click "Revoke Floor" button next to an agent
- Agent will no longer respond to utterances until floor is granted again

**Floor States:**
- **IDLE**: No floor activity
- **GRANTED**: Floor granted to specific agent
- **REVOKED**: Floor revoked from agent
- **YIELDED**: Agent voluntarily yielded floor

### Agent Management

**Invite Agent:**
```
1. Select agent URL from dropdown
2. Click "Invite"
3. Agent receives invite event with conversation context
4. Agent appears in agents list
```

**Uninvite Agent:**
```
1. Click "Uninvite" button next to agent
2. Agent receives uninvite event
3. Agent removed from conversation
```

**Check/Uncheck Agents:**
- Checked agents receive utterances
- Unchecked agents remain in conversation but don't receive new utterances
- Useful for temporarily excluding agents without uninviting

### Viewing Events

**Show Last Event:**
- Click "Show Event" button to view the last sent OpenFloor envelope
- Displays full JSON structure for debugging

**Conversation History:**
- Displays all utterances with speaker labels
- Format: `[SPEAKER_NAME] message text`
- Includes deduplication to prevent repeated messages

## OpenFloor Protocol Integration

### Supported Event Types

**Outgoing (Client → Agents):**
- `invite`: Invite agent to join conversation
- `uninvite`: Remove agent from conversation
- `utterance`: Send user message to agents
- `getManifests`: Request agent capabilities
- `grantFloor`: Grant speaking permission
- `revokeFloor`: Revoke speaking permission

**Incoming (Agents → Client):**
- `publishManifests`: Agent capability announcement
- `utterance`: Agent response message
- `acceptInvite`: Agent accepts invitation
- `declineInvite`: Agent declines invitation

### Message Flow

#### Simple Utterance Flow
```
1. User types message
2. Client creates utterance event with dialogEvent
3. Client sends to all checked agents (Phase 1: Broadcast)
4. Agents process and respond (Phase 2: Process)
5. Responses displayed in conversation history
6. Responses forwarded to other agents (Phase 3: Forward)
```

#### Invite Flow
```
1. User selects agent URL and clicks "Invite"
2. Client creates invite event with conversation context
3. Agent receives invite with dialog history
4. Agent responds with utterance (typically greeting)
5. Agent added to conversation participants
```

### Three-Phase Processing

**Phase 1: Broadcast to Agents**
- Sends events to all target agents simultaneously
- Handles connection errors and timeouts gracefully
- Collects all responses for processing
- 5-second timeout per agent

**Phase 2: Process Responses**
- Extracts and processes publishManifests events
- Adds agents to floor manager
- Updates conversation history with utterances
- Handles HTML responses
- Performs deduplication

**Phase 3: Forward Responses**
- Forwards agent responses to other agents in conversation
- Maintains conversation context across agents
- Handles recursive forwarding with history
- Enables multi-agent collaboration

## Configuration

### Client Identity

Default configuration:
```python
client_uri = "tag:assistantClient,2025:client"  # Client's OpenFloor URI
client_url = "http://localhost:5000"            # Client's service URL
```

### Floor Manager

Optional floor management for turn-taking control. Features:
- Conversant tracking
- Floor granting/revoking
- Role assignment
- Request queuing
- Timeout handling

## Error Handling

**Connection Errors:**
- Displays user-friendly error dialogs
- Continues processing other agents if one fails
- Logs errors to console

**Timeout Handling:**
- 5-second timeout per agent request
- Prevents application hanging on unresponsive agents
- Notifies user of timeout issues

**JSON Parsing:**
- Handles malformed responses gracefully
- Provides error context in dialogs

## Security Features

**Send Button State Management:**
- Button disabled when no agents invited
- Prevents sending to empty recipient list

**Invited Agent Enforcement:**
- Utterances only sent to explicitly invited agents
- URL combobox remains active for invite/getManifests operations

**Input Validation:**
- Validates URLs before agent operations
- Checks for empty messages
- Verifies agent state before operations

## Troubleshooting

### Agent Not Responding
- Verify agent is running and accessible
- Check agent URL is correct
- Look for connection errors in console
- Verify agent supports OpenFloor Protocol

### Messages Not Appearing
- Ensure agent is checked in the agents list
- Verify agent is invited (not just discovered)
- Check conversation history for errors

### Floor Manager Issues
- Click "Start Floor" before using floor operations
- Only one agent should have floor at a time
- Revoked agents won't respond to utterances

## Code Organization

```
assistantClient/
├── assistantClient.py       # Main coordinator (728 lines)
├── ui_components.py         # UI layer (281 lines)
├── event_handlers.py        # Event processing (326 lines)
├── floor.py                 # Floor management
├── known_agents.py          # Agent discovery
├── openfloor/              # OpenFloor protocol classes
│   ├── agent.py
│   ├── envelope.py
│   ├── events.py
│   ├── manifest.py
│   └── dialog_event.py
└── README.md               # This file
```

## Related Components

### AssistantClientSpeech

Speech-enabled version with voice input/output:
- Uses pyttsx3 for TTS
- Uses SpeechRecognition for ASR
- No text input/output (speech only)

**Run with:**
```bash
python assistantClientSpeech.py
```

### AssistantClientWeb

Web-based version for browser access.

**Run with:**
```bash
python assistantClientWeb.py
```

## OpenFloor Protocol Resources

- [OpenFloor Specification](https://github.com/open-voice-interoperability/openfloor-docs)
- [Conversation Envelope Schema](https://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/)

## License

See LICENSE file in repository root.

## Contributors

Part of the Open Voice Interoperability implementation examples.
