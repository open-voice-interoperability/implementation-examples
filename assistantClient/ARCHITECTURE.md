# Assistant Client Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Assistant Client (Convener)                      │
│                                                                          │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────────┐   │
│  │ assistantClient│  │  ui_components   │  │  event_handlers     │   │
│  │     .py        │──│      .py         │  │      .py            │   │
│  │  (728 lines)   │  │   (281 lines)    │  │   (326 lines)       │   │
│  │                │  │                  │  │                     │   │
│  │ • Coordinator  │  │ • GUI widgets    │  │ • 3-phase processor │   │
│  │ • State mgmt   │  │ • Display logic  │  │ • Error handling    │   │
│  │ • Agent mgmt   │  │ • HTML viewer    │  │ • Message routing   │   │
│  └────────────────┘  └──────────────────┘  └─────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Floor Manager (Optional)                       │  │
│  │  • Conversation turn-taking control                              │  │
│  │  • Grant/Revoke floor permissions                                │  │
│  │  • Conversant tracking and role assignment                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    OpenFloor Protocol Layer                       │  │
│  │  openfloor/agent.py • envelope.py • events.py • manifest.py      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ────────────────┼────────────────
                    │               │               │
                    ▼               ▼               ▼
            ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
            │   Agent 1    │ │   Agent 2    │ │   Agent N    │
            │   (Stella)   │ │   (Verity)   │ │     ...      │
            │              │ │              │ │              │
            │ localhost:   │ │ localhost:   │ │ localhost:   │
            │   8767       │ │   8768       │ │   XXXX       │
            └──────────────┘ └──────────────┘ └──────────────┘
```

## Component Architecture

### 1. Main Coordinator (`assistantClient.py`)

```
┌─────────────────────────────────────────────────────────────┐
│                    assistantClient.py                        │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Global State Management                    │ │
│  │                                                         │ │
│  │  • global_conversation    - Conversation object        │ │
│  │  • invited_agents[]       - List of invited URLs       │ │
│  │  • agent_checkboxes{}     - URL → checkbox mapping     │ │
│  │  • revoked_agents[]       - Agents with revoked floor  │ │
│  │  • conversation_history[] - Full conversation log      │ │
│  │  • floor_manager          - Optional floor controller  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │            Agent Management Functions                   │ │
│  │                                                         │ │
│  │  add_agent(url)              - Register new agent      │ │
│  │  update_agent(index, info)   - Modify agent info       │ │
│  │  create_agent_checkbox(url)  - Add UI for agent        │ │
│  │  extract_url_from_agent()    - Parse agent URL         │ │
│  │  invite_agent(url)           - Send invite event       │ │
│  │  uninvite_agent(info, url)   - Send uninvite event     │ │
│  │  grant_floor_to_agent()      - Grant speaking rights   │ │
│  │  revoke_floor_from_agent()   - Revoke speaking rights  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │               Event Coordination                        │ │
│  │                                                         │ │
│  │  send_events(event_types)    - Main event dispatcher   │ │
│  │    ↓                                                    │ │
│  │    Constructs OpenFloor Envelope                        │ │
│  │    Determines target URLs                               │ │
│  │    Delegates to event_handlers                          │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │           UI Callback Handlers                          │ │
│  │                                                         │ │
│  │  send_utterance()            - Button click handler    │ │
│  │  get_manifests()             - Request agent caps      │ │
│  │  invite()                    - Invite button handler   │ │
│  │  update_agent_textboxes()    - Refresh agent display   │ │
│  │  update_conversation_history() - Add to history        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2. UI Components (`ui_components.py`)

```
┌─────────────────────────────────────────────────────────────┐
│                    ui_components.py                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                  UI Layout                              │ │
│  │                                                         │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Text Entry Box                                   │  │ │
│  │  │  (User types utterances here)                     │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  [Send Utterance Button]                          │  │ │
│  │  │  (Disabled when no agents invited)                │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Conversation History                             │  │ │
│  │  │  1. [USER] Hello                                  │  │ │
│  │  │  2. [STELLA] Hi, I'm Stella...                    │  │ │
│  │  │  3. [VERITY] Thanks for the invitation...         │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Agent URL Combobox ▼                             │  │ │
│  │  │  (Select agent to invite/query)                   │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  ☐ Send to all agents                             │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  [Get Manifests]  [Invite]  [Show Event]          │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Invited Agents:                                  │  │ │
│  │  │  ☑ Stella - localhost:8767                        │  │ │
│  │  │     [Uninvite] [Grant Floor] [Revoke Floor]       │  │ │
│  │  │  ☑ Verity - localhost:8768                        │  │ │
│  │  │     [Uninvite] [Grant Floor] [Revoke Floor]       │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  [Start Floor]                                    │  │ │
│  │  │  Floor Status: GRANTED to Stella                  │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Display Functions                          │ │
│  │                                                         │ │
│  │  display_response_json()     - Show JSON in window     │ │
│  │  display_response_html()     - Open HTML in browser    │ │
│  │  display_floor_status()      - Update floor state      │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3. Event Handlers (`event_handlers.py`)

```
┌─────────────────────────────────────────────────────────────────┐
│                     event_handlers.py                            │
│                  Three-Phase Message Processing                  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  PHASE 1: Broadcast to Agents                              │ │
│  │  send_broadcast_to_agents(urls, envelope, ...)             │ │
│  │                                                             │ │
│  │  For each target URL:                                       │ │
│  │    try:                                                     │ │
│  │      ┌─────────────────────────────────────────┐           │ │
│  │      │  POST envelope to agent URL              │           │ │
│  │      │  Timeout: 5 seconds                      │           │ │
│  │      └─────────────────────────────────────────┘           │ │
│  │      ├─ Success → Collect response                          │ │
│  │      ├─ ConnectionError → Show error dialog                 │ │
│  │      ├─ Timeout → Show timeout message                      │ │
│  │      └─ Other Exception → Log and continue                  │ │
│  │                                                             │ │
│  │  Returns: all_responses[]                                   │ │
│  │    - (target_url, response_data, sender, events)           │ │
│  └────────────────────────────────────────────────────────────┘ │
│                             ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  PHASE 2: Process Agent Responses                          │ │
│  │  process_agent_responses(all_responses, ...)               │ │
│  │                                                             │ │
│  │  For each response:                                         │ │
│  │    For each event in response:                              │ │
│  │      ┌──────────────────────────────────────┐              │ │
│  │      │  Event Type: publishManifests?       │              │ │
│  │      └──────────────────────────────────────┘              │ │
│  │                  │ YES                                      │ │
│  │                  ▼                                          │ │
│  │      ┌──────────────────────────────────────┐              │ │
│  │      │  Extract conversationalName          │              │ │
│  │      │  Add to floor_manager                │              │ │
│  │      │  Cache agent identity                │              │ │
│  │      └──────────────────────────────────────┘              │ │
│  │                                                             │ │
│  │      ┌──────────────────────────────────────┐              │ │
│  │      │  Event Type: utterance?              │              │ │
│  │      └──────────────────────────────────────┘              │ │
│  │                  │ YES                                      │ │
│  │                  ▼                                          │ │
│  │      ┌──────────────────────────────────────┐              │ │
│  │      │  Extract speakerUri                  │              │ │
│  │      │  Lookup conversationalName           │              │ │
│  │      │    (from manifest or floor_manager)  │              │ │
│  │      │  Extract text/html features          │              │ │
│  │      │  Check for duplicates                │              │ │
│  │      │  Update conversation history         │              │ │
│  │      │  Display HTML if present             │              │ │
│  │      └──────────────────────────────────────┘              │ │
│  │                                                             │ │
│  │  Returns: Updated UI with agent responses                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                             ▼                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  PHASE 3: Forward Responses to Other Agents                │ │
│  │  forward_responses_to_agents(all_responses, ...)           │ │
│  │                                                             │ │
│  │  For each agent A's response:                               │ │
│  │    For each other agent B in conversation:                  │ │
│  │      if B != A:                                             │ │
│  │        ┌────────────────────────────────────┐              │ │
│  │        │  Create forwarding envelope        │              │ │
│  │        │  Include conversation history      │              │ │
│  │        │  POST to agent B                   │              │ │
│  │        └────────────────────────────────────┘              │ │
│  │                     ▼                                       │ │
│  │        ┌────────────────────────────────────┐              │ │
│  │        │  Collect agent B's responses       │              │ │
│  │        │  Update conversation history       │              │ │
│  │        │  Display B's utterances            │              │ │
│  │        └────────────────────────────────────┘              │ │
│  │                     ▼                                       │ │
│  │        ┌────────────────────────────────────┐              │ │
│  │        │  RECURSIVE: Forward B's responses  │              │ │
│  │        │  to other agents (if any)          │              │ │
│  │        └────────────────────────────────────┘              │ │
│  │                                                             │ │
│  │  Result: Multi-agent conversation propagation               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Message Flow Diagrams

### Utterance Flow (Simple)

```
User
 │
 │ Types "What is Mars?"
 │
 ▼
┌────────────────────┐
│ assistantClient.py │
│ send_utterance()   │
└────────────────────┘
 │
 │ Create Envelope with utterance event
 │
 ▼
┌────────────────────┐
│ event_handlers.py  │
│ send_events()      │
└────────────────────┘
 │
 ├──────────────────────────────────┐
 │ PHASE 1: Broadcast               │
 ▼                                  ▼
[Stella]                        [Verity]
localhost:8767                  localhost:8768
 │                                  │
 │ Process utterance                │ Process utterance
 │ Generate response                │ Generate response
 │                                  │
 ▼                                  ▼
Response:                       Response:
"Mars is the 4th planet..."     "That is correct."
 │                                  │
 └──────────────┬───────────────────┘
                │
                │ PHASE 2: Process
                ▼
        ┌───────────────────┐
        │ Update UI:         │
        │ [STELLA] Mars is...│
        │ [VERITY] That is...│
        └───────────────────┘
                │
                │ PHASE 3: Forward
                ▼
        Forward Stella's response → Verity
        Forward Verity's response → Stella
                │
                ▼
        (Agents may respond again)
```

### Invite Flow

```
User
 │
 │ Selects "http://localhost:8767" from dropdown
 │ Clicks "Invite"
 │
 ▼
┌────────────────────┐
│ assistantClient.py │
│ invite_agent()     │
└────────────────────┘
 │
 │ Create Envelope with:
 │  - invite event
 │  - conversation history (context)
 │  - conversation object with participants
 │
 ▼
┌────────────────────┐
│ Stella Agent       │
│ bot_on_invite()    │
└────────────────────┘
 │
 │ Process invite
 │ Check for "joining floor"
 │ Generate greeting
 │
 ▼
Response Envelope:
 - publishManifests (agent capabilities)
 - utterance (greeting: "Hi, I'm Stella...")
 │
 ▼
┌────────────────────┐
│ event_handlers.py  │
│ Phase 2: Process   │
└────────────────────┘
 │
 ├─ Extract manifest → Add to floor_manager
 ├─ Extract utterance → Update conversation history
 │
 ▼
┌────────────────────┐
│ UI Update:         │
│ ☑ Stella - 8767    │
│ [STELLA] Hi, I'm...│
└────────────────────┘
```

### Floor Management Flow

```
User clicks "Grant Floor" for Stella
 │
 ▼
┌────────────────────┐
│ assistantClient.py │
│ grant_floor_to...()│
└────────────────────┘
 │
 │ floor_manager.grant_floor(stella_uri)
 │ Create grantFloor event
 │
 ▼
┌────────────────────┐
│ Stella Agent       │
│ bot_on_grant_floor │
└────────────────────┘
 │
 │ agent.grantedFloor = True
 │ agent.floorRevoked = False
 │
 ▼
Now only Stella can respond to utterances
(Other agents ignore utterances when not granted floor)

User clicks "Revoke Floor" for Stella
 │
 ▼
┌────────────────────┐
│ assistantClient.py │
│ revoke_floor_from()│
└────────────────────┘
 │
 │ floor_manager.revoke_floor(stella_uri)
 │ Create revokeFloor event
 │
 ▼
┌────────────────────┐
│ Stella Agent       │
│ bot_on_revoke_floor│
└────────────────────┘
 │
 │ agent.grantedFloor = False
 │ agent.floorRevoked = True
 │
 ▼
Stella now ignores all utterance events
(bot_on_utterance returns early)
```

## Data Flow

### Global State Management

```
┌─────────────────────────────────────────────────────────────┐
│                    Global Variables                          │
│                                                              │
│  global_conversation: Conversation                           │
│    ├─ id: "conversation-12345"                              │
│    └─ conversants: List[Conversant]                         │
│         ├─ identification                                    │
│         │    ├─ speakerUri: "openFloor:stella"              │
│         │    ├─ serviceUrl: "http://localhost:8767"         │
│         │    └─ conversationalName: "Stella"                │
│         └─ (repeated for each agent)                        │
│                                                              │
│  invited_agents: List[str]                                   │
│    ├─ "http://localhost:8767"                               │
│    └─ "http://localhost:8768"                               │
│                                                              │
│  agent_checkboxes: Dict[str, Widget]                        │
│    ├─ "http://localhost:8767" → CTkCheckBox(Stella)        │
│    └─ "http://localhost:8768" → CTkCheckBox(Verity)        │
│                                                              │
│  revoked_agents: List[str]                                   │
│    └─ "http://localhost:8768"  (Verity's floor revoked)    │
│                                                              │
│  conversation_history_for_context: List[Tuple]              │
│    ├─ ("USER", client_uri, "Hello")                        │
│    ├─ ("Stella", stella_uri, "Hi, I'm Stella...")          │
│    └─ ("Verity", verity_uri, "Thanks for asking...")        │
│                                                              │
│  floor_manager: FloorManager                                 │
│    ├─ conversants: Dict[uri, Conversant]                    │
│    ├─ current_floor_holder: "openFloor:stella"             │
│    ├─ floor_state: FloorState.GRANTED                       │
│    └─ pending_requests: List[FloorRequest]                  │
└─────────────────────────────────────────────────────────────┘
```

### OpenFloor Envelope Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenFloor Envelope                        │
│                                                              │
│  {                                                           │
│    "openFloor": {                                            │
│      "conversation": {                                       │
│        "id": "conv-12345",                                   │
│        "conversants": [                                      │
│          {                                                   │
│            "identification": {                               │
│              "speakerUri": "openFloor:stella",              │
│              "serviceUrl": "http://localhost:8767",         │
│              "conversationalName": "Stella"                  │
│            }                                                 │
│          }                                                   │
│        ]                                                     │
│      },                                                      │
│      "sender": {                                             │
│        "speakerUri": "tag:assistantClient,2025:client",     │
│        "serviceUrl": "http://localhost:5000"                │
│      },                                                      │
│      "events": [                                             │
│        {                                                     │
│          "eventType": "utterance",                           │
│          "to": { "serviceUrl": "http://localhost:8767" },   │
│          "parameters": {                                     │
│            "dialogEvent": {                                  │
│              "speakerUri": "tag:assistantClient,2025:...",  │
│              "features": {                                   │
│                "text": {                                     │
│                  "tokens": [                                 │
│                    { "value": "What is Mars?" }              │
│                  ]                                           │
│                }                                             │
│              }                                               │
│            }                                                 │
│          }                                                   │
│        }                                                     │
│      ]                                                       │
│    }                                                         │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
```

## Security & State Management

```
┌─────────────────────────────────────────────────────────────┐
│                  Security Features                           │
│                                                              │
│  Button State Management:                                    │
│  ┌──────────────────────────────────────┐                   │
│  │  update_send_utterance_button_state()│                   │
│  └──────────────────────────────────────┘                   │
│         │                                                    │
│         ├─ Check if any agents invited                       │
│         │                                                    │
│         ├─ YES → Enable "Send Utterance" button             │
│         │                                                    │
│         └─ NO  → Disable button (grayed out)                │
│                                                              │
│  Message Routing:                                            │
│  ┌──────────────────────────────────────┐                   │
│  │  Determine target URLs                │                   │
│  └──────────────────────────────────────┘                   │
│         │                                                    │
│         ├─ Event type: invite/getManifests?                 │
│         │    YES → Use URL from combobox                     │
│         │                                                    │
│         └─ Event type: utterance?                            │
│              YES → Use only invited agents list              │
│                    Filter by checked checkboxes              │
│                                                              │
│  Speaker Identification:                                     │
│  ┌──────────────────────────────────────┐                   │
│  │  Lookup conversationalName            │                   │
│  └──────────────────────────────────────┘                   │
│         │                                                    │
│         ├─ Check publishManifests in response               │
│         │                                                    │
│         ├─ Fallback: Query floor_manager by speakerUri      │
│         │                                                    │
│         └─ Fallback: Use speakerUri directly                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│               Error Handling Strategy                        │
│                                                              │
│  Connection Errors (Phase 1: Broadcast)                     │
│  ┌──────────────────────────────────────┐                   │
│  │  try: POST to agent                  │                   │
│  │  except ConnectionError:              │                   │
│  │    Show error dialog                  │                   │
│  │    Continue with other agents         │                   │
│  │  except Timeout:                      │                   │
│  │    Show timeout message               │                   │
│  │    Continue with other agents         │                   │
│  │  except Exception as e:               │                   │
│  │    Log error                          │                   │
│  │    Continue with other agents         │                   │
│  └──────────────────────────────────────┘                   │
│                                                              │
│  JSON Parsing Errors (Phase 2: Process)                     │
│  ┌──────────────────────────────────────┐                   │
│  │  try: Parse response JSON             │                   │
│  │  except JSONDecodeError:              │                   │
│  │    Show error dialog with context     │                   │
│  │    Skip this response                 │                   │
│  │    Continue with other responses      │                   │
│  └──────────────────────────────────────┘                   │
│                                                              │
│  Deduplication (Prevent repeated messages)                   │
│  ┌──────────────────────────────────────┐                   │
│  │  if utterance_id in processed_ids:   │                   │
│  │    Skip (already displayed)           │                   │
│  │  else:                                │                   │
│  │    Add to conversation history        │                   │
│  │    Mark utterance_id as processed     │                   │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

## Conclusion

The Assistant Client architecture is designed with:
- **Modularity**: Three separate files for coordination, UI, and event processing
- **Robustness**: Comprehensive error handling at every layer
- **Flexibility**: Optional floor management for conversation control
- **Scalability**: Supports any number of OpenFloor-compatible agents
- **User-Friendly**: Clear visual feedback and intuitive controls
