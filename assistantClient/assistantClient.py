# Set True to enable very verbose console debug output (HTTP payloads, headers, etc.)
DEBUG_CONSOLE_HTTP = False
import openfloor

import json
import requests
import re
import threading
import time
from datetime import datetime
import socket
import traceback

from openfloor import DialogEvent, Conversation
from openfloor import UtteranceEvent, UninviteEvent, RevokeFloorEvent, GrantFloorEvent
from openfloor import Envelope, Sender, To, Conversant
from openfloor.manifest import Identification

from known_agents import KNOWN_AGENTS
import ui_components
import event_handlers

# -----------------------------------------------------------------------------
# Networking configuration
# -----------------------------------------------------------------------------

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}

client_uri = ""
client_url = ""  
private = False
# construct a uri for the client
authority = socket.getfqdn()
hostname = socket.gethostname()
ip_address = socket.gethostbyname(hostname)
client_name = "AssistantClientConvener"
client_url = f"http://{ip_address}"
client_uri = f"openFloor://{ip_address}/" + client_name

assistantConversationalName = ""
floor_manager = None
invited_agents = []  # List to keep track of invited agents
agent_textboxes = []  # List to keep track of individual agent textboxes
revoked_agents = []  # List to keep track of agents whose floor has been revoked
agent_checkboxes = {}  # Dictionary to track checkboxes: {agent_url: checkbox_widget}
manifest_cache = {}  # Dictionary to cache conversational names from manifests: {url: conversational_name}

AGENT_STATUS_IDLE = "idle"
AGENT_STATUS_WORKING = "working"
AGENT_STATUS_ERROR = "error"
AGENT_STATUS_COLORS = {
    AGENT_STATUS_IDLE: "blue",
    AGENT_STATUS_ERROR: "red",
}
AGENT_STATUS_PULSE_COLORS = ("#1f9d55", "#3cb371")

agent_status_by_url = {}  # {agent_url: idle|working|error}
agent_status_widgets = {}  # {agent_url: status_dot_widget}
agent_status_pulse_jobs = {}  # {agent_url: root.after job id}
agent_status_pulse_phase = {}  # {agent_url: 0/1}

# -----------------------------------------------------------------------------
# Known-agent display and mapping utilities
# -----------------------------------------------------------------------------

def _extract_known_agent_url(agent_info):
    if isinstance(agent_info, dict):
        return agent_info.get("url", "")
    return agent_info

def _extract_known_agent_name(agent_info):
    if isinstance(agent_info, dict):
        return agent_info.get("conversational_name", "")
    return ""

def _build_known_agent_urls(known_agents):
    urls = []
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if url and url not in urls:
            urls.append(url)
    return urls

def _build_known_agent_name_map(known_agents):
    name_map = {}
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        name = _extract_known_agent_name(agent_info)
        if name:
            name_map[url] = name
    return name_map

def _format_known_agent_display(url, conversational_name):
    if conversational_name:
        return f"{conversational_name} | {url}"
    return url

def _build_known_agent_displays(known_agents):
    displays = []
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        display = _format_known_agent_display(url, _extract_known_agent_name(agent_info))
        if display not in displays:
            displays.append(display)
    return displays

def _build_display_to_url_map(known_agents):
    display_map = {}
    for agent_info in known_agents:
        url = _extract_known_agent_url(agent_info)
        if not url:
            continue
        display = _format_known_agent_display(url, _extract_known_agent_name(agent_info))
        display_map[display] = url
        display_map[url] = url
    return display_map

def _display_for_url(url):
    name = KNOWN_AGENT_NAME_BY_URL.get(url, "")
    if not name:
        name = resolve_conversational_name(f"agent:{url}", url) or ""
    if not name:
        for agent_info in invited_agents:
            if extract_url_from_agent_info(agent_info) == url:
                if isinstance(agent_info, dict):
                    name = agent_info.get("conversational_name", "")
                break
    return _format_known_agent_display(url, name)

def _build_unique_urls(*url_lists):
    ordered = []
    seen = set()
    for urls in url_lists:
        for url in urls:
            if url and url not in seen:
                ordered.append(url)
                seen.add(url)
    return ordered

def refresh_agent_combobox():
    all_urls = _build_unique_urls(KNOWN_AGENT_URLS, previous_urls)
    all_displays = [_display_for_url(url) for url in all_urls]
    url_combobox.configure(values=all_displays)

KNOWN_AGENT_URLS = _build_known_agent_urls(KNOWN_AGENTS)
KNOWN_AGENT_NAME_BY_URL = _build_known_agent_name_map(KNOWN_AGENTS)
KNOWN_AGENT_DISPLAYS = _build_known_agent_displays(KNOWN_AGENTS)
KNOWN_AGENT_DISPLAY_TO_URL = _build_display_to_url_map(KNOWN_AGENTS)

# -----------------------------------------------------------------------------
# Conversational name and speaker resolution
# -----------------------------------------------------------------------------

def _resolve_assistant_url(value):
    if not value:
        return value
    resolved = KNOWN_AGENT_DISPLAY_TO_URL.get(value)
    if resolved:
        return resolved
    if " | " in value:
        return value.split(" | ", 1)[-1].strip()
    return value

def _normalize_agent_id(value):
    if not value:
        return value
    if value.startswith("agent:"):
        value = value[len("agent:"):]
    return value.rstrip("/").lower()


def _url_from_speaker_uri(speaker_uri):
    if not speaker_uri:
        return None

    candidate = _clean_url_candidate(speaker_uri)
    if candidate.startswith("agent:http://") or candidate.startswith("agent:https://"):
        return candidate[len("agent:"):]
    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate
    return None


def _clean_url_candidate(value):
    if not value or not isinstance(value, str):
        return ""
    cleaned = value.strip().strip("[]()<>{}\"'")
    cleaned = cleaned.rstrip("\"'.,:;!?)]}>")
    return cleaned


def _is_url_like(value):
    if not value or not isinstance(value, str):
        return False
    lowered = _clean_url_candidate(value).lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered.startswith("agent:http://") or lowered.startswith("agent:https://")


def _known_name_for_url(target_url):
    if not target_url:
        return ""

    direct_name = KNOWN_AGENT_NAME_BY_URL.get(target_url, "")
    if direct_name:
        return direct_name

    normalized_target = _normalize_agent_id(target_url)
    for known_url, known_name in KNOWN_AGENT_NAME_BY_URL.items():
        if known_name and _normalize_agent_id(known_url) == normalized_target:
            return known_name

    return ""


def _name_from_url_path(url_value):
    if not _is_url_like(url_value):
        return ""

    normalized_url = _url_from_speaker_uri(url_value) or url_value
    tail = normalized_url.rstrip("/").rsplit("/", 1)[-1].strip()
    if not tail:
        return ""

    for known_name in KNOWN_AGENT_NAME_BY_URL.values():
        if known_name and tail.lower() == known_name.strip().lower():
            return known_name

    if tail.lower() == "verity":
        return "Verity"

    return ""

def _cache_conversational_name(conversational_name, *keys):
    if not conversational_name:
        return
    for key in keys:
        normalized = _normalize_agent_id(key)
        if normalized:
            manifest_cache[normalized] = conversational_name

def resolve_conversational_name(speaker_uri, target_url=None):
    """Resolve a friendly name for a speaker using floor manager or manifest cache."""
    normalized_speaker = _normalize_agent_id(speaker_uri)
    normalized_target = _normalize_agent_id(target_url)

    if floor_manager is not None and normalized_speaker:
        try:
            conversant = floor_manager.conversants.get(speaker_uri)
            if conversant and conversant.conversational_name:
                return conversant.conversational_name
        except Exception:
            pass

    if normalized_speaker and normalized_speaker in manifest_cache:
        return manifest_cache.get(normalized_speaker)
    if normalized_target and normalized_target in manifest_cache:
        return manifest_cache.get(normalized_target)

    return None

def resolve_display_name_for_target(target_url, speaker_uri=None):
    target_url = _clean_url_candidate(target_url)

    if speaker_uri:
        name = resolve_conversational_name(speaker_uri, target_url)
        if name and not _is_url_like(name):
            return name
    for agent_info in invited_agents:
        if _normalize_agent_id(extract_url_from_agent_info(agent_info)) == _normalize_agent_id(target_url):
            if isinstance(agent_info, dict):
                name = agent_info.get("conversational_name", "")
                if name and not _is_url_like(name):
                    return name
            break
    name = _known_name_for_url(target_url)
    if name:
        return name
    name = resolve_conversational_name(f"agent:{target_url}", target_url)
    if name and not _is_url_like(name):
        return name
    path_name = _name_from_url_path(target_url)
    if path_name:
        return path_name
    path_name = _name_from_url_path(speaker_uri or "")
    if path_name:
        return path_name
    return target_url or _url_from_speaker_uri(speaker_uri) or "Unknown"

def _normalize_display_name(name):
    if not name:
        return name
    if _is_url_like(name):
        path_name = _name_from_url_path(name)
        if path_name:
            return path_name
    if name.strip().lower().startswith("verity"):
        return "Verity"
    return name


def _resolve_history_speaker_name(speaker, speaker_uri=None):
    candidate_url = _url_from_speaker_uri(speaker_uri) or _url_from_speaker_uri(speaker) or (speaker if _is_url_like(speaker) else None)
    if candidate_url:
        display = resolve_display_name_for_target(candidate_url, speaker_uri=speaker_uri)
        if display and not _is_url_like(display):
            return _normalize_display_name(display)
    return _normalize_display_name(speaker)


def _resolve_speaker_uri_for_agent_url(agent_url):
    if not agent_url:
        return None

    for conversant in global_conversation.conversants:
        identification = getattr(conversant, "identification", None)
        if identification is None:
            continue
        if getattr(identification, "serviceUrl", None) == agent_url:
            speaker_uri = getattr(identification, "speakerUri", None)
            if speaker_uri:
                return speaker_uri

    return f"agent:{agent_url}"


def _is_name_prefix_match(user_input, candidate_name):
    if not user_input or not candidate_name:
        return False
    trimmed_input = user_input.lstrip()
    pattern = rf"^{re.escape(candidate_name)}(?:\b|[\s,:;.!?\-])"
    return re.match(pattern, trimmed_input, flags=re.IGNORECASE) is not None


def _find_addressed_conversant_by_prefix(user_input):
    if not user_input:
        return None

    matches = []
    for conversant in global_conversation.conversants:
        identification = getattr(conversant, "identification", None)
        if identification is None:
            continue

        conversational_name = (getattr(identification, "conversationalName", "") or "").strip()
        speaker_uri = getattr(identification, "speakerUri", None)
        service_url = getattr(identification, "serviceUrl", None)

        if _is_url_like(conversational_name):
            conversational_name = resolve_display_name_for_target(service_url or _url_from_speaker_uri(speaker_uri), speaker_uri=speaker_uri)

        if not conversational_name or not speaker_uri:
            continue
        if _is_url_like(conversational_name):
            continue
        if _is_name_prefix_match(user_input, conversational_name):
            matches.append((len(conversational_name), service_url, conversational_name, speaker_uri))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    _, target_url, conversational_name, speaker_uri = matches[0]
    return {
        "url": target_url,
        "name": conversational_name,
        "speaker_uri": speaker_uri,
    }


def _find_addressed_agent_in_utterance(user_input):
    if not user_input:
        return None

    conversant_match = _find_addressed_conversant_by_prefix(user_input)
    if conversant_match:
        return conversant_match

    matches = []

    for agent_info in invited_agents:
        target_url = extract_url_from_agent_info(agent_info)
        if not target_url:
            continue

        conversational_name = ""
        if isinstance(agent_info, dict):
            conversational_name = (agent_info.get("conversational_name") or "").strip()
        if not conversational_name:
            conversational_name = resolve_conversational_name(f"agent:{target_url}", target_url) or ""
        if not conversational_name:
            conversational_name = KNOWN_AGENT_NAME_BY_URL.get(target_url, "")

        if not conversational_name:
            continue

        if _is_name_prefix_match(user_input, conversational_name):
            matches.append((len(conversational_name), target_url, conversational_name))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    _, target_url, conversational_name = matches[0]

    return {
        "url": target_url,
        "name": conversational_name,
        "speaker_uri": _resolve_speaker_uri_for_agent_url(target_url),
    }


def _prepend_direct_address_context(text, addressed_agent, *, speaker_name=None, speaker_uri=None, speaker_url=None):
    if not text or not addressed_agent:
        return text

    def _replace_leading_url_with_name(raw_text):
        trimmed = raw_text.lstrip()
        leading_ws = raw_text[: len(raw_text) - len(trimmed)]
        match = re.match(r"^(?:agent:)?https?://[^\s]+", trimmed, flags=re.IGNORECASE)
        if not match:
            return raw_text

        raw_url = match.group(0)
        candidate_url = _url_from_speaker_uri(raw_url) or _clean_url_candidate(raw_url)
        resolved_name = resolve_display_name_for_target(candidate_url, speaker_uri=speaker_uri)
        if not resolved_name or _is_url_like(resolved_name):
            return raw_text

        remainder = trimmed[match.end():]
        remainder = re.sub(r"^[\s,:;.!?\-]+", "", remainder)
        if not remainder:
            return f"{leading_ws}{resolved_name}"
        return f"{leading_ws}{resolved_name}: {remainder}"

    normalized_text = text
    normalized_text = _replace_leading_url_with_name(normalized_text)
    stripped_text = text.strip()
    if _is_url_like(stripped_text):
        candidate_url = _url_from_speaker_uri(stripped_text) or _clean_url_candidate(stripped_text)
        resolved_text = resolve_display_name_for_target(candidate_url, speaker_uri=speaker_uri)
        if resolved_text and not _is_url_like(resolved_text):
            normalized_text = resolved_text

    addressee_name = (addressed_agent.get("name") or "").strip()
    if _is_url_like(addressee_name):
        addressee_name = resolve_display_name_for_target(
            addressed_agent.get("url") or _url_from_speaker_uri(addressed_agent.get("speaker_uri")),
            speaker_uri=addressed_agent.get("speaker_uri"),
        )
    if not addressee_name:
        return normalized_text

    if speaker_name:
        normalized_speaker_name = speaker_name.strip()
        if normalized_speaker_name:
            if normalized_text.strip().lower() == normalized_speaker_name.lower():
                return normalized_text
            if re.match(
                rf"^{re.escape(normalized_speaker_name)}(?:\b|[\s,:;.!?\-])",
                normalized_text.strip(),
                flags=re.IGNORECASE,
            ):
                return normalized_text

    if speaker_name and speaker_name.strip().lower() == addressee_name.lower():
        return normalized_text

    addressee_speaker_uri = addressed_agent.get("speaker_uri")
    if addressee_speaker_uri and speaker_uri:
        if _normalize_agent_id(addressee_speaker_uri) == _normalize_agent_id(speaker_uri):
            return normalized_text

    addressee_url = addressed_agent.get("url")
    if addressee_url:
        normalized_addressee_url = _normalize_agent_id(addressee_url)
        if speaker_url and _normalize_agent_id(speaker_url) == normalized_addressee_url:
            return normalized_text
        if speaker_uri and _normalize_agent_id(speaker_uri) == normalized_addressee_url:
            return normalized_text

    if re.match(rf"^{re.escape(addressee_name)}(?:\b|[\s,:;.!?\-])", normalized_text.lstrip(), flags=re.IGNORECASE):
        return normalized_text

    return f"{addressee_name}, {normalized_text}"


# Global conversation to track conversants across the session
global_conversation = Conversation()

# Track full conversation history for context events
conversation_history_for_context = []  # List of (speaker_name, speaker_uri, text) tuples

# Track utterance IDs we've already added to conversation history to avoid duplicates
processed_utterance_ids = set()

# Setup UI appearance
print("=" * 60)
print("🚀 STARTING ASSISTANT CLIENT...")
print("=" * 60)
ui_components.setup_appearance()

previous_urls = []
# Initialize the outgoing_events variable globally to track all sent events
outgoing_events = []

# Create main window and UI elements
print("📱 Creating main window UI...")
root = ui_components.create_main_window()
print("✅ Main window created - should be visible now")
widgets = ui_components.create_ui_elements(root, KNOWN_AGENT_DISPLAYS)
print("✅ UI elements created - application ready")

# Extract widget references for easier access
entry = widgets['entry']
url_combobox = widgets['url_combobox']
send_to_all_checkbox = widgets['send_to_all_checkbox']
show_incoming_events_checkbox = widgets['show_incoming_events_checkbox']
conversation_text = widgets['conversation_text']
get_manifests_button = widgets['get_manifests_button']
invite_button = widgets['invite_button']
send_utterance_button = widgets['send_utterance_button']
reset_conversation_button = widgets['reset_conversation_button']
agents_frame = widgets['agents_frame']
no_agents_label = widgets['no_agents_label']
show_outgoing_events_checkbox = widgets['show_outgoing_events_checkbox']
start_floor_button = widgets['start_floor_button']
show_error_log_checkbox = widgets['show_error_log_checkbox']

# Error log window state (shown/hidden via checkbox)
error_log_window = None
error_log_textbox = None
error_log_buffer = []  # list[str]

# Initialize send utterance button as disabled (no agents yet)
send_utterance_button.configure(state="disabled")

def reset_conversation_history():
    """Clear the conversation history and reset numbering."""
    global conversation_history_for_context, processed_utterance_ids
    conversation_history_for_context = []
    processed_utterance_ids = set()
    try:
        conversation_text.configure(state='normal')
        conversation_text.delete('1.0', 'end')
        conversation_text.configure(state='disabled')
    except Exception:
        pass

reset_conversation_button.configure(command=reset_conversation_history)

def log_error(message):
    """Log error message to the error log textbox."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}\n" + ("-" * 80) + "\n"
    error_log_buffer.append(entry)

    # If the error log window is open, append to it.
    global error_log_textbox
    if error_log_textbox is not None:
        try:
            error_log_textbox.configure(state='normal')
            error_log_textbox.insert('end', entry)
            error_log_textbox.see('end')
            error_log_textbox.configure(state='disabled')
        except Exception:
            pass
    print(message)  # Also print to console


def _stop_agent_status_pulse(agent_url):
    job_id = agent_status_pulse_jobs.pop(agent_url, None)
    if job_id is not None:
        try:
            root.after_cancel(job_id)
        except Exception:
            pass


def _pulse_agent_status(agent_url):
    if agent_status_by_url.get(agent_url) != AGENT_STATUS_WORKING:
        return

    status_widget = agent_status_widgets.get(agent_url)
    if status_widget is None:
        agent_status_pulse_jobs.pop(agent_url, None)
        return
    try:
        if not status_widget.winfo_exists():
            agent_status_pulse_jobs.pop(agent_url, None)
            return
    except Exception:
        agent_status_pulse_jobs.pop(agent_url, None)
        return

    pulse_phase = agent_status_pulse_phase.get(agent_url, 0)
    color = AGENT_STATUS_PULSE_COLORS[pulse_phase % len(AGENT_STATUS_PULSE_COLORS)]
    try:
        status_widget.configure(text_color=color)
    except Exception:
        return

    agent_status_pulse_phase[agent_url] = (pulse_phase + 1) % len(AGENT_STATUS_PULSE_COLORS)
    try:
        agent_status_pulse_jobs[agent_url] = root.after(420, lambda: _pulse_agent_status(agent_url))
    except Exception:
        pass


def _apply_agent_status(agent_url):
    status_widget = agent_status_widgets.get(agent_url)
    if status_widget is None:
        return

    state = agent_status_by_url.get(agent_url, AGENT_STATUS_IDLE)
    if state == AGENT_STATUS_WORKING:
        _stop_agent_status_pulse(agent_url)
        agent_status_pulse_phase[agent_url] = 0
        _pulse_agent_status(agent_url)
        return

    _stop_agent_status_pulse(agent_url)
    color = AGENT_STATUS_COLORS.get(state, AGENT_STATUS_COLORS[AGENT_STATUS_IDLE])
    try:
        status_widget.configure(text_color=color)
    except Exception:
        pass


def _register_agent_status_widget(agent_url, status_widget):
    if not agent_url or status_widget is None:
        return
    agent_status_widgets[agent_url] = status_widget
    if agent_url not in agent_status_by_url:
        agent_status_by_url[agent_url] = AGENT_STATUS_IDLE
    _apply_agent_status(agent_url)


def _set_agent_status(agent_url, status):
    if not agent_url:
        return
    if status not in (AGENT_STATUS_IDLE, AGENT_STATUS_WORKING, AGENT_STATUS_ERROR):
        status = AGENT_STATUS_IDLE
    agent_status_by_url[agent_url] = status
    _apply_agent_status(agent_url)


def _set_status_for_agents(agent_urls, status):
    seen_urls = set()
    for agent_url in agent_urls or []:
        if agent_url and agent_url not in seen_urls:
            seen_urls.add(agent_url)
            _set_agent_status(agent_url, status)


def _pump_ui_once():
    try:
        root.update()
    except Exception:
        pass


def _post_with_ui_pulse(target_url, payload_obj, *, headers=None, timeout=None):
    result = {}

    def _worker():
        try:
            response = requests.post(
                target_url,
                json=payload_obj,
                timeout=timeout,
                headers=headers,
            )
            result["response"] = response
        except Exception as exc:
            result["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    while worker.is_alive():
        _pump_ui_once()
        time.sleep(0.05)

    if "error" in result:
        raise result["error"]

    return result["response"]


def update_error_log_visibility():
    """Show/hide the error log window based on the checkbox."""
    global error_log_window, error_log_textbox
    try:
        if show_error_log_checkbox.get():
            if error_log_window is None or not error_log_window.winfo_exists():
                error_log_window, error_log_textbox = ui_components.create_error_log_window(root)

                # Populate with buffered log entries
                try:
                    error_log_textbox.configure(state='normal')
                    error_log_textbox.delete('0.0', 'end')
                    error_log_textbox.insert('end', ''.join(error_log_buffer))
                    error_log_textbox.see('end')
                    error_log_textbox.configure(state='disabled')
                except Exception:
                    pass

                # If user closes via X, reflect in checkbox state
                def _on_close():
                    global error_log_window, error_log_textbox
                    try:
                        show_error_log_checkbox.deselect()
                    except Exception:
                        pass
                    try:
                        if error_log_window is not None and error_log_window.winfo_exists():
                            error_log_window.destroy()
                    except Exception:
                        pass
                    error_log_window = None
                    error_log_textbox = None

                try:
                    error_log_window.protocol("WM_DELETE_WINDOW", _on_close)
                except Exception:
                    pass
        else:
            if error_log_window is not None and error_log_window.winfo_exists():
                error_log_window.destroy()
            error_log_window = None
            error_log_textbox = None
    except Exception:
        # UI should never crash on a visibility toggle
        pass

def add_invited_agent(agent_url, conversational_name='', update_ui=True):
    """Add an agent to the invited agents list."""
    # Check manifest cache for conversational name if not provided
    if not conversational_name and agent_url in manifest_cache:
        conversational_name = manifest_cache[agent_url]
    if not conversational_name:
        conversational_name = KNOWN_AGENT_NAME_BY_URL.get(agent_url, "")
    
    agent_info = {'url': agent_url, 'conversational_name': conversational_name}
    # Check if URL already exists in list
    for existing_agent in invited_agents:
        if extract_url_from_agent_info(existing_agent) == agent_url:
            # Update with conversational name if we now have one
            if conversational_name:
                existing_agent['conversational_name'] = conversational_name
                if update_ui:
                    update_agent_textboxes()
            return
    invited_agents.append(agent_info)
    add_conversant_to_global(agent_url)
    if agent_url not in agent_status_by_url:
        agent_status_by_url[agent_url] = AGENT_STATUS_IDLE
    if update_ui:
        update_agent_textboxes()

def create_agent_textbox(agent_info):
    """Create a frame with uninvite button and textbox for a specific agent."""
    agent_url = extract_url_from_agent_info(agent_info)
    
    is_revoked = agent_url in revoked_agents
    
    # Create UI elements using ui_components
    agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, agent_checkbox, status_dot = ui_components.create_agent_textbox_ui(
        agents_frame=agents_frame,
        agent_info=agent_info,
        agent_url=agent_url,
        is_revoked=is_revoked,
        grant_floor_callback=lambda: grant_floor_to_agent(agent_info, agent_url),
        revoke_floor_callback=lambda: revoke_floor_from_agent(agent_info, agent_url),
        uninvite_callback=lambda: uninvite_agent(agent_info, agent_url)
    )

    # UX rule: selecting any per-agent "send private" checkbox should turn off
    # the global "Send to all invited agents" mode.
    def _on_private_checkbox_toggle(url=agent_url, checkbox=agent_checkbox):
        try:
            if checkbox.get():
                send_to_all_checkbox.deselect()
        except Exception:
            pass

    try:
        agent_checkbox.configure(command=_on_private_checkbox_toggle)
    except Exception:
        pass
    
    # Store checkbox reference
    agent_checkboxes[agent_url] = agent_checkbox
    _register_agent_status_widget(agent_url, status_dot)
    
    agent_textboxes.append((agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, agent_checkbox, status_dot))
    return agent_frame

def extract_url_from_agent_info(agent_info):
    """Extract URL from agent info."""
    if isinstance(agent_info, dict):
        return agent_info.get('url', '')
    # Backwards compatibility: if agent_info is just a string URL
    return agent_info

def add_conversant_to_global(agent_url):
    """Add a conversant to the global conversation."""
    global global_conversation
    # Check if already exists
    for conversant in global_conversation.conversants:
        if conversant.identification.serviceUrl == agent_url:
            existing_name = getattr(conversant.identification, "conversationalName", "")
            if not existing_name or _is_url_like(existing_name):
                better_name = resolve_display_name_for_target(agent_url, f"agent:{agent_url}")
                if better_name and not _is_url_like(better_name):
                    conversant.identification.conversationalName = better_name
            return  # Already exists
    
    # Add new conversant
    conversational_name = resolve_display_name_for_target(agent_url, f"agent:{agent_url}")
    if not conversational_name:
        conversational_name = agent_url
    conversant = Conversant(
        identification=Identification(
            speakerUri=f"agent:{agent_url}",
            serviceUrl=agent_url,
            conversationalName=conversational_name
        )
    )
    global_conversation.conversants.append(conversant)

def remove_conversant_from_global(agent_url):
    """Remove a conversant from the global conversation."""
    global global_conversation
    global_conversation.conversants = [
        c for c in global_conversation.conversants 
        if c.identification.serviceUrl != agent_url
    ]

def update_conversation_history(speaker, text, speaker_uri=None, utterance_id=None):
    """Update the conversation history text area with a new utterance."""
    global conversation_history_for_context, processed_utterance_ids

    speaker = _resolve_history_speaker_name(speaker, speaker_uri)
    
    # Skip if we've already processed this utterance
    if utterance_id and utterance_id in processed_utterance_ids:
        return
    
    # Add to context history
    conversation_history_for_context.append((speaker, speaker_uri or speaker, text))
    
    # Mark as processed
    if utterance_id:
        processed_utterance_ids.add(utterance_id)
    
    # Get the utterance number (1-indexed based on how many we've added)
    utterance_number = len(conversation_history_for_context)
    
    conversation_text.configure(state='normal')
    current_text = conversation_text.get("1.0", "end-1c")
    if current_text:
        conversation_text.insert("end", "\n\n")  # Double newline for more spacing
    # Use uppercase and special formatting to make speaker names stand out, with number
    conversation_text.insert("end", f"{utterance_number}. [{speaker.upper()}] {text}")
    conversation_text.configure(state='disabled')
    # Auto-scroll to bottom
    conversation_text.see("end")

def grant_floor_to_agent(agent_info, agent_url):
    """Send grant floor message to agent."""
    _set_agent_status(agent_url, AGENT_STATUS_WORKING)
    try:
        root.update_idletasks()
    except Exception:
        pass
    try:
        # Create grant floor envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create grant floor event
        grant_event = GrantFloorEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(grant_event)
        
        # Send grant floor message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = _post_with_ui_pulse(
            agent_url,
            payload_obj,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Grant floor failed with status {response.status_code}: {response.text[:300]}")
        
        print(f"Grant floor sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Update floor manager if active
        if floor_manager is not None:
            try:
                floor_manager.grant_floor(agent_url)
            except Exception as e:
                print(f"Could not grant floor in floor manager: {e}")
        
        # Remove from revoked agents list
        if agent_url in revoked_agents:
            revoked_agents.remove(agent_url)
        
        # Update the display to remove strikethrough and change button
        update_agent_textboxes()
        _set_agent_status(agent_url, AGENT_STATUS_IDLE)
        
    except Exception as e:
        _set_agent_status(agent_url, AGENT_STATUS_ERROR)
        error_msg = f"Failed to grant floor to agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to grant floor to agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error granting floor to agent: {e}")

def revoke_floor_from_agent(agent_info, agent_url):
    """Send revoke floor message to agent."""
    _set_agent_status(agent_url, AGENT_STATUS_WORKING)
    try:
        root.update_idletasks()
    except Exception:
        pass
    try:
        # Create revoke floor envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create revoke floor event
        revoke_event = RevokeFloorEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(revoke_event)
        
        # Send revoke floor message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = _post_with_ui_pulse(
            agent_url,
            payload_obj,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Revoke floor failed with status {response.status_code}: {response.text[:300]}")
        
        print(f"Revoke floor sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Update floor manager if active
        if floor_manager is not None:
            try:
                floor_manager.revoke_floor(agent_url)
            except Exception as e:
                print(f"Could not revoke floor in floor manager: {e}")
        
        # Track that this agent's floor has been revoked
        if agent_url not in revoked_agents:
            revoked_agents.append(agent_url)
        
        # Update the display to show strikethrough
        update_agent_textboxes()
        _set_agent_status(agent_url, AGENT_STATUS_IDLE)
        
    except Exception as e:
        _set_agent_status(agent_url, AGENT_STATUS_ERROR)
        error_msg = f"Failed to revoke floor from agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to revoke floor from agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error revoking floor from agent: {e}")

def uninvite_agent(agent_info, agent_url):
    """Send uninvite message to agent and remove from list."""
    _set_agent_status(agent_url, AGENT_STATUS_WORKING)
    try:
        root.update_idletasks()
    except Exception:
        pass
    try:
        # Create uninvite envelope using global conversation
        global global_conversation
        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )
        
        # Create uninvite event
        uninvite_event = UninviteEvent(to=To(serviceUrl=agent_url))
        envelope.events.append(uninvite_event)
        
        # Send uninvite message
        envelope_to_send = envelope.to_json(as_payload=True)
        payload_obj = json.loads(envelope_to_send)
        
        response = _post_with_ui_pulse(
            agent_url,
            payload_obj,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Uninvite failed with status {response.status_code}: {response.text[:300]}")
        
        print(f"Uninvite sent to {agent_url}, status: {response.status_code}")
        
        # Store outgoing event for display
        global outgoing_events
        outgoing_events.append(envelope)
        
        # Remove from global conversation
        remove_conversant_from_global(agent_url)
        
        # Remove from invited agents list by URL (since agent_info might be a reference issue)
        invited_agents[:] = [agent for agent in invited_agents if extract_url_from_agent_info(agent) != agent_url]
        
        # Remove from revoked agents list if present
        if agent_url in revoked_agents:
            revoked_agents.remove(agent_url)

        _stop_agent_status_pulse(agent_url)
        agent_status_by_url.pop(agent_url, None)
        agent_status_widgets.pop(agent_url, None)
        agent_status_pulse_phase.pop(agent_url, None)
        agent_status_pulse_jobs.pop(agent_url, None)
            
        # Remove from floor manager if active
        if floor_manager is not None:
            # Try to find and remove agent from floor manager
            # Note: This is a simple approach, might need refinement
            try:
                floor_manager.remove_conversant(agent_url)
            except Exception as e:
                print(f"Could not remove agent from floor manager: {e}")
        
        # Update display
        update_agent_textboxes()
        
    except Exception as e:
        _set_agent_status(agent_url, AGENT_STATUS_ERROR)
        error_msg = f"Failed to uninvite agent: {str(e)}\n\n{traceback.format_exc()}"
        log_error(error_msg)
        ui_components.show_app_message(root, "Error", f"Failed to uninvite agent: {str(e)}\n\nSee Error Log for details")
        print(f"Error uninviting agent: {e}")

def update_send_utterance_button_state():
    """Enable or disable the send utterance button based on whether there are invited agents."""
    if invited_agents:
        send_utterance_button.configure(state="normal")
    else:
        send_utterance_button.configure(state="disabled")

def update_agent_textboxes():
    """Update all agent textboxes to match the invited agents list."""
    # Clear all existing textboxes
    for item in agent_textboxes:
        if len(item) >= 3:  # Handle both old and new tuple formats
            agent_frame = item[0]
            agent_frame.destroy()
    agent_textboxes.clear()

    invited_urls = {
        extract_url_from_agent_info(agent_info)
        for agent_info in invited_agents
        if extract_url_from_agent_info(agent_info)
    }

    for tracked_url in list(agent_checkboxes.keys()):
        if tracked_url not in invited_urls:
            agent_checkboxes.pop(tracked_url, None)

    for tracked_url in list(agent_status_by_url.keys()):
        if tracked_url not in invited_urls:
            _stop_agent_status_pulse(tracked_url)
            agent_status_by_url.pop(tracked_url, None)
            agent_status_widgets.pop(tracked_url, None)
            agent_status_pulse_phase.pop(tracked_url, None)
    
    # Show or hide the no agents label
    if invited_agents:
        no_agents_label.pack_forget()
        # Create new textboxes for each agent
        for agent_info in invited_agents:
            create_agent_textbox(agent_info)
    else:
        no_agents_label.pack(pady=10)
    
    # Update send utterance button state
    update_send_utterance_button_state()


# -----------------------------------------------------------------------------
# Send orchestration and preflight
# -----------------------------------------------------------------------------

def send_utterance():
    send_events(["utterance"])

def get_manifests():
    send_events(["getManifests"])

def _collect_target_urls(event_types, assistant_url, send_to_all):
    """Return target URLs based on event type and current checkbox state."""
    if "invite" in event_types or "getManifests" in event_types:
        return [assistant_url] if assistant_url else []

    if send_to_all and invited_agents:
        return [extract_url_from_agent_info(agent) for agent in invited_agents]

    target_urls = []
    for agent_url, checkbox in agent_checkboxes.items():
        if checkbox.get() and any(extract_url_from_agent_info(agent) == agent_url for agent in invited_agents):
            target_urls.append(agent_url)
    return target_urls


def _collect_new_invite_urls(event_types, target_urls):
    """Return invite targets that are not already invited."""
    if "invite" not in event_types:
        return []
    already_invited_urls = [extract_url_from_agent_info(agent) for agent in invited_agents]
    return [url for url in target_urls if url not in already_invited_urls]


def _apply_utterance_preflight(event_types, user_input, target_urls):
    """Validate utterance input, update local history, and resolve optional addressing."""
    addressed_agent = None
    if "utterance" not in event_types:
        return addressed_agent, target_urls, user_input

    if not user_input:
        ui_components.show_app_message(root, "Warning", "Please enter some text before sending an utterance.")
        return None, None, None

    addressed_agent = _find_addressed_agent_in_utterance(user_input)
    if addressed_agent and invited_agents:
        if _is_url_like(addressed_agent.get("name", "")):
            addressed_agent["name"] = resolve_display_name_for_target(
                addressed_agent.get("url") or _url_from_speaker_uri(addressed_agent.get("speaker_uri")),
                speaker_uri=addressed_agent.get("speaker_uri"),
            )
        target_urls = [extract_url_from_agent_info(agent) for agent in invited_agents]

    update_conversation_history("You", user_input)
    return addressed_agent, target_urls, user_input


def _warn_for_missing_targets(event_types):
    """Show the appropriate warning when no destination agents are available."""
    if "invite" in event_types or "getManifests" in event_types:
        ui_components.show_app_message(root, "Warning", "No Assistant URL specified.")
    elif not invited_agents:
        ui_components.show_app_message(root, "Warning", "No invited agents to send to. Invite an agent first.")
    else:
        ui_components.show_app_message(
            root,
            "Warning",
            "No agents selected. Enable 'Send to all invited agents' or select an agent checkbox.",
        )


def invite():
    # Check if the agent in the URL combobox is already invited
    assistant_url = _resolve_assistant_url(url_combobox.get())
    if assistant_url:
        # Check if this URL is already in the invited agents list
        for agent_info in invited_agents:
            if extract_url_from_agent_info(agent_info) == assistant_url:
                # Agent already invited, do nothing
                return
    
    events_to_send = ["invite"]
    user_input = entry.get().strip()
    if user_input:
        events_to_send.append("utterance")
    send_events(events_to_send)


# -----------------------------------------------------------------------------
# Network send paths (broadcast/direct)
# -----------------------------------------------------------------------------

def _send_events_broadcast(event_types, user_input, target_urls, new_invite_urls, addressed_agent):
    global private, outgoing_events

    conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))
    sender = Sender(
        speakerUri=client_uri,
        serviceUrl=client_url
    )
    envelope = Envelope(
        conversation=conversation,
        sender=sender
    )

    for event_type in event_types:
        if event_type == "invite":
            inviteEvent = openfloor.events.InviteEvent()
            private = True
            envelope.events.append(inviteEvent)

            for target_url in new_invite_urls:
                add_invited_agent(target_url, update_ui=True)
        elif event_type == "getManifests":
            getManifestsEvent = openfloor.events.GetManifestsEvent()
            envelope.events.append(getManifestsEvent)
        elif event_type == "utterance":
            dialog = DialogEvent(
                speakerUri=client_uri,
                features={
                    "text": {
                        "mimeType": "text/plain",
                        "tokens": [{"value": user_input}]
                    }
                }
            )
            if addressed_agent and addressed_agent.get("speaker_uri"):
                envelope.events.append(
                    UtteranceEvent(
                        dialogEvent=dialog,
                        to=To(speakerUri=addressed_agent["speaker_uri"]),
                    )
                )
            else:
                envelope.events.append(UtteranceEvent(dialogEvent=dialog))

    outgoing_events.append(envelope)
    envelope_to_send = envelope.to_json(as_payload=True)

    try:
        payload_obj = json.loads(envelope_to_send)
        if DEBUG_CONSOLE_HTTP:
            print("Payload to send (BROADCAST):", json.dumps(payload_obj, indent=2))

        if show_outgoing_events_checkbox.get():
            ui_components.display_outgoing_envelope_json(root, payload_obj, target_label="broadcast")

        urls_to_send = new_invite_urls if "invite" in event_types else target_urls
        _set_status_for_agents(urls_to_send, AGENT_STATUS_WORKING)
        try:
            root.update_idletasks()
        except Exception:
            pass

        all_responses = event_handlers.send_broadcast_to_agents(
            payload_obj,
            urls_to_send,
            status_callback=_set_agent_status,
            ui_pump_callback=_pump_ui_once,
        )

        event_handlers.process_agent_responses(
            root,
            all_responses,
            floor_manager,
            update_conversation_history,
            invited_agents,
            update_agent_textboxes,
            extract_url_from_agent_info,
            manifest_cache,
            show_incoming_events=bool(show_incoming_events_checkbox.get()),
            directed_addressee=addressed_agent,
            display_name_resolver=resolve_display_name_for_target,
        )

        event_handlers.forward_responses_to_agents(
            all_responses,
            urls_to_send,
            global_conversation,
            update_conversation_history,
            status_callback=_set_agent_status,
            ui_pump_callback=_pump_ui_once,
            directed_addressee=addressed_agent,
            display_name_resolver=resolve_display_name_for_target,
        )

    except Exception as e:
        _set_status_for_agents(target_urls, AGENT_STATUS_ERROR)
        error_details = traceback.format_exc()
        print(f"Error processing incoming event: {error_details}")
        ui_components.show_app_message(root, "Error", f"Error processing incoming event: {str(e)}\n\nCheck console for details.")


# -----------------------------------------------------------------------------
# Direct-response event parsing
# -----------------------------------------------------------------------------

def _process_direct_response_events(response_data, target_url, assistant_url, addressed_agent=None):
    global assistantConversationalName, assistant_uri

    incoming_events = response_data.get("openFloor", {}).get("events", [])
    for event in incoming_events:
        if event.get("eventType") == "publishManifests":
            manifests = event.get("parameters", {}).get("servicingManifests", [])
            if manifests:
                manifest = manifests[0]
                assistantConversationalName = manifest.get("identification", {}).get("conversationalName", "")
                assistant_uri = manifest.get("identification", {}).get("uri", "")
                manifest_speaker_uri = manifest.get("identification", {}).get("speakerUri", "")
                manifest_service_url = manifest.get("identification", {}).get("serviceUrl", assistant_url)

                _cache_conversational_name(
                    assistantConversationalName,
                    manifest_service_url,
                    target_url,
                    assistant_uri,
                    manifest_speaker_uri,
                )

                for agent_info in invited_agents:
                    agent_info_url = extract_url_from_agent_info(agent_info)
                    if agent_info_url == manifest_service_url or agent_info_url == target_url:
                        if assistantConversationalName:
                            if DEBUG_CONSOLE_HTTP:
                                print(f"Updating agent {agent_info_url} with conversational name: {assistantConversationalName}")
                            agent_info['conversational_name'] = assistantConversationalName
                            if DEBUG_CONSOLE_HTTP:
                                print(f"Agent info after update: {agent_info}")
                            update_agent_textboxes()
                        break

                if manifest_service_url and manifest_service_url not in previous_urls and manifest_service_url not in KNOWN_AGENT_URLS:
                    previous_urls.append(manifest_service_url)
                    refresh_agent_combobox()

                if floor_manager is not None and assistant_uri:
                    try:
                        floor_manager.add_conversant(
                            speaker_uri=assistant_uri,
                            service_url=manifest_service_url,
                            conversational_name=assistantConversationalName
                        )
                        if DEBUG_CONSOLE_HTTP:
                            print(f"Added {assistantConversationalName or assistant_uri} to floor manager")
                    except Exception as e:
                        if DEBUG_CONSOLE_HTTP:
                            print(f"Failed to add agent to floor manager: {e}")
            else:
                ui_components.show_app_message(root, "Error", "No servicing manifests found in the response.")
        elif event.get("eventType") == "utterance":
            parameters = event.get("parameters", {})
            dialog_event = parameters.get("dialogEvent", {})
            features = dialog_event.get("features", {})
            text_features = features.get("text", {})
            html_features = features.get("html", {})

            speaker_uri = dialog_event.get("speakerUri", "Unknown")

            resolved_name = resolve_conversational_name(speaker_uri, target_url)
            display_name = resolve_display_name_for_target(target_url, speaker_uri)
            if not assistantConversationalName and resolved_name:
                assistantConversationalName = resolved_name

            if html_features:
                html_tokens = html_features.get("tokens", [])
                if html_tokens:
                    html_value = html_tokens[0].get("value", "")
                    if html_value:
                        ui_components.display_response_html(html_value)

            mime_type = text_features.get("mimeType", "")
            tokens = text_features.get("tokens", [])
            if tokens:
                extracted_value = tokens[0].get("value", "No value found")
                extracted_value = _prepend_direct_address_context(
                    extracted_value,
                    addressed_agent,
                    speaker_name=display_name,
                    speaker_uri=speaker_uri,
                    speaker_url=target_url,
                )

                utterance_id = dialog_event.get("id")
                update_conversation_history(display_name, extracted_value, speaker_uri, utterance_id)

                if mime_type != "text/plain":
                    html_content = f"{ui_components.convert_text_to_html(extracted_value)}"
                    ui_components.display_response_html(html_content)

    if show_incoming_events_checkbox.get():
        ui_components.display_incoming_envelope_json(
            root,
            response_data,
            assistantConversationalName,
            assistant_url,
        )


def _send_events_direct(event_types, user_input, target_urls, addressed_agent, use_private, assistant_url):
    global private, outgoing_events, assistantConversationalName, assistant_uri

    for target_url in target_urls:
        _set_agent_status(target_url, AGENT_STATUS_WORKING)
        try:
            root.update_idletasks()
        except Exception:
            pass

        conversation = Conversation(id=global_conversation.id, conversants=list(global_conversation.conversants))

        sender = Sender(
            speakerUri=client_uri,
            serviceUrl=client_url
        )
        envelope = Envelope(
            conversation=conversation,
            sender=sender
        )

        for event_type in event_types:
            if event_type == "invite":
                inviteEvent = openfloor.events.InviteEvent(to=To(serviceUrl=target_url))
                private = True
                envelope.events.append(inviteEvent)
                add_invited_agent(target_url, update_ui=True)
            elif event_type == "getManifests":
                getManifestsEvent = openfloor.events.GetManifestsEvent(to=To(serviceUrl=target_url))
                envelope.events.append(getManifestsEvent)
            elif event_type == "utterance":
                dialog = DialogEvent(
                    speakerUri=client_uri,
                    features={
                        "text": {
                            "mimeType": "text/plain",
                            "tokens": [{"value": user_input}]
                        }
                    }
                )
                if addressed_agent and addressed_agent.get("speaker_uri"):
                    envelope.events.append(
                        UtteranceEvent(
                            dialogEvent=dialog,
                            to=To(speakerUri=addressed_agent["speaker_uri"], private=use_private or private),
                        )
                    )
                else:
                    envelope.events.append(
                        UtteranceEvent(
                            dialogEvent=dialog,
                            to=To(serviceUrl=target_url, private=use_private or private),
                        )
                    )

        outgoing_events.append(envelope)
        envelope_to_send = envelope.to_json(as_payload=True)

        try:
            payload_obj = json.loads(envelope_to_send)
            if DEBUG_CONSOLE_HTTP:
                print("="*80)
                print("OUTGOING ENVELOPE JSON:")
                print("="*80)
                print(json.dumps(payload_obj, indent=2))
                print("="*80)

            if show_outgoing_events_checkbox.get():
                ui_components.display_outgoing_envelope_json(root, payload_obj, target_label=target_url)

            if DEBUG_CONSOLE_HTTP:
                print(f"\nSending to: {target_url}")
            try:
                response = _post_with_ui_pulse(
                    target_url,
                    payload_obj,
                    timeout=10,
                    headers=DEFAULT_REQUEST_HEADERS,
                )
            except requests.RequestException as exc:
                _set_agent_status(target_url, AGENT_STATUS_ERROR)
                error_msg = f"Failed to reach {target_url}: {exc}"
                log_error(error_msg)
                ui_components.show_app_message(
                    root,
                    "Error",
                    f"Failed to reach {target_url}. See Error Log for details.",
                )
                continue
            if DEBUG_CONSOLE_HTTP:
                print(f"HTTP status from {target_url}: {response.status_code}")
                print("Response headers:", dict(response.headers))
                print("Response text (first 500 chars):", response.text[:500])

            if response.status_code != 200:
                _set_agent_status(target_url, AGENT_STATUS_ERROR)
                error_msg = f"Server {target_url} returned status {response.status_code}\n\nFull Response:\n{response.text}"
                log_error(error_msg)
                ui_components.show_app_message(
                    root,
                    "Error",
                    f"Server {target_url} returned status {response.status_code}\n\nSee Error Log for full response",
                )
                continue

            try:
                response_data = response.json()
            except json.JSONDecodeError as e:
                _set_agent_status(target_url, AGENT_STATUS_ERROR)
                error_msg = f"Server {target_url} did not return valid JSON.\n\nStatus: {response.status_code}\n\nFull Response:\n{response.text}\n\nJSON Error: {str(e)}"
                log_error(error_msg)
                ui_components.show_app_message(
                    root,
                    "Error",
                    f"Server {target_url} did not return valid JSON.\n\nSee Error Log for full response",
                )
                continue

            if DEBUG_CONSOLE_HTTP:
                print("Response JSON:", json.dumps(response_data, indent=2))
            _process_direct_response_events(response_data, target_url, assistant_url, addressed_agent=addressed_agent)
            _set_agent_status(target_url, AGENT_STATUS_IDLE)

        except Exception as e:
            _set_agent_status(target_url, AGENT_STATUS_ERROR)
            error_details = traceback.format_exc()
            print(f"Error processing incoming event: {error_details}")
            ui_components.show_app_message(root, "Error", f"Error processing incoming event: {str(e)}\n\nCheck console for details.")

# The main function to send events

def send_events(event_types):
    global client_url,client_uri,assistant_url, assistant_uri, assistantConversationalName, previous_urls, outgoing_events, private, global_conversation
    user_input = entry.get().strip()
    assistant_url = _resolve_assistant_url((url_combobox.get() or "").strip())
    send_to_all = send_to_all_checkbox.get()
    target_urls = _collect_target_urls(event_types, assistant_url, send_to_all)
    new_invite_urls = _collect_new_invite_urls(event_types, target_urls)
    if "invite" in event_types and len(event_types) == 1 and not new_invite_urls:
        return

    addressed_agent, target_urls, user_input = _apply_utterance_preflight(event_types, user_input, target_urls)
    if target_urls is None:
        return
    
    if not target_urls:
        _warn_for_missing_targets(event_types)
        return
    
    # Update previous_urls while keeping KNOWN_AGENTS
    if assistant_url and assistant_url not in previous_urls:
        previous_urls.append(assistant_url)
    # Merge known and previous URLs, preserving order and removing duplicates
    refresh_agent_combobox()
    
    # When sending to all, use broadcast (no 'to' field) and send same envelope to all URLs
    # Each agent will process it as a broadcast message
    is_broadcast = send_to_all and len(target_urls) > 1
    
    # Messages sent via individual checkboxes should be private
    use_private = not send_to_all
    
    if is_broadcast:
        _send_events_broadcast(event_types, user_input, target_urls, new_invite_urls, addressed_agent)
    
    else:
        _send_events_direct(event_types, user_input, target_urls, addressed_agent, use_private, assistant_url)


# user interface functions

def start_floor_manager():
    """Start a new floor manager for the current conversation."""
    global floor_manager
    floor_manager = ui_components.start_floor_manager_ui(root, client_uri, client_url, client_name, show_window=False, show_message=False)

def _bind_ui_commands():
    """Bind UI controls to command handlers."""
    get_manifests_button.configure(command=get_manifests)
    invite_button.configure(command=invite)
    send_utterance_button.configure(command=send_utterance)
    start_floor_button.configure(command=start_floor_manager)
    show_error_log_checkbox.configure(command=update_error_log_visibility)

    def _on_entry_submit(_event=None):
        try:
            send_utterance_button.invoke()
        except Exception:
            send_utterance()
        return "break"

    # Bind Enter in the utterance entry to behave like clicking Send Utterance.
    entry.bind("<Return>", _on_entry_submit, add="+")
    entry.bind("<KP_Enter>", _on_entry_submit, add="+")

    # CTkEntry wraps an internal tk.Entry; bind there too for reliability.
    inner_entry = getattr(entry, "_entry", None)
    if inner_entry is not None:
        inner_entry.bind("<Return>", _on_entry_submit, add="+")
        inner_entry.bind("<KP_Enter>", _on_entry_submit, add="+")


def _initialize_application_state():
    """Run one-time startup initialization after UI creation."""
    start_floor_manager()
    update_error_log_visibility()


def main():
    _bind_ui_commands()
    _initialize_application_state()
    root.mainloop()


if __name__ == "__main__":
    main()
