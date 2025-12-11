"""UI components for the Assistant Client application."""

from tkinterweb import HtmlFrame
from customtkinter import (
    CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, 
    CTkComboBox, CTkCheckBox, CTkScrollableFrame, CTkFrame,
    set_appearance_mode, set_default_color_theme
)
import tkinter.messagebox as messagebox
from CTkMessagebox import CTkMessagebox
import json
import requests
import re
from pathlib import Path
import webbrowser
import floor


def setup_appearance():
    """Configure the UI appearance settings."""
    set_appearance_mode("light")
    set_default_color_theme("blue")


def create_main_window():
    """Create and configure the main application window."""
    root = CTk()
    root.title("Open Floor Client Assistant")
    root.geometry("600x850")
    return root


def create_ui_elements(root, known_agents):
    """Create all UI elements and return references to important widgets.
    
    Returns:
        dict: Dictionary containing references to all UI widgets
    """
    widgets = {}
    
    # Text entry
    CTkLabel(root, text="Enter text for utterance:").pack(pady=(5, 0))
    widgets['entry'] = CTkEntry(root, width=400)
    widgets['entry'].pack(pady=5, padx=20)
    
    # Send utterance button (directly below text entry)
    widgets['send_utterance_button'] = CTkButton(root, text="Send Utterance")
    widgets['send_utterance_button'].pack(pady=5)
    
    # Conversation history
    CTkLabel(root, text="Conversation History:").pack(pady=(10, 0))
    widgets['conversation_text'] = CTkTextbox(root, wrap='word', height=150)
    widgets['conversation_text'].configure(state='disabled')
    widgets['conversation_text'].pack(pady=5, padx=20, fill="both")
    
    # URL combobox
    CTkLabel(root, text="Assistant URL:").pack(pady=(10, 0))
    widgets['url_combobox'] = CTkComboBox(root, width=400, values=known_agents, state="normal")
    widgets['url_combobox'].set(known_agents[0] if known_agents else "http://localhost:8767/")
    widgets['url_combobox'].pack(pady=5, padx=20)
    
    # Send to all checkbox
    widgets['send_to_all_checkbox'] = CTkCheckBox(root, text="Send to all invited agents")
    widgets['send_to_all_checkbox'].select()  # Checked by default
    widgets['send_to_all_checkbox'].pack(pady=5)
    
    # Top buttons frame
    buttons_frame = CTkFrame(root)
    buttons_frame.pack(pady=(10, 5))
    
    widgets['get_manifests_button'] = CTkButton(buttons_frame, text="Get Manifests")
    widgets['get_manifests_button'].pack(side="left", padx=5)
    
    widgets['invite_button'] = CTkButton(buttons_frame, text="Invite")
    widgets['invite_button'].pack(side="left", padx=5)
    
    # Agent list section
    CTkLabel(root, text="Agents invited to the floor:").pack(pady=(10, 0))
    CTkLabel(root, text="Send private message to this agent", 
             font=("Arial", 9), anchor="e").pack(pady=(0, 0), padx=20, anchor="e")
    
    widgets['agents_frame'] = CTkScrollableFrame(root, height=200, fg_color="white")
    widgets['agents_frame'].pack(pady=5, padx=20, fill="both", expand=False)
    
    widgets['no_agents_label'] = CTkLabel(widgets['agents_frame'], text="No agents invited yet")
    widgets['no_agents_label'].pack(pady=10)
    
    # Bottom buttons frame
    bottom_buttons_frame = CTkFrame(root)
    bottom_buttons_frame.pack(pady=(10, 5))
    
    widgets['show_event_button'] = CTkButton(bottom_buttons_frame, text="Show Outgoing Events")
    widgets['show_event_button'].pack(side="left", padx=5)
    
    widgets['start_floor_button'] = CTkButton(bottom_buttons_frame, text="Start Floor Manager")
    widgets['start_floor_button'].pack(side="left", padx=5)
    
    return widgets


def create_agent_textbox_ui(agents_frame, agent_info, agent_url, 
                            is_revoked, grant_floor_callback, 
                            revoke_floor_callback, uninvite_callback):
    """Create a frame with buttons and textbox for a specific agent.
    
    Args:
        agents_frame: Parent frame to contain the agent UI
        agent_info: Agent information string
        agent_url: Agent's service URL
        is_revoked: Whether the agent's floor has been revoked
        grant_floor_callback: Function to call when granting floor
        revoke_floor_callback: Function to call when revoking floor
        uninvite_callback: Function to call when uninviting
        
    Returns:
        tuple: (agent_frame, textbox, uninvite_btn, floor_btn, checkbox)
    """
    # Create a frame to hold both button and textbox
    agent_frame = CTkFrame(agents_frame)
    agent_frame.pack(pady=2, padx=5, fill="x")
    
    # Determine button text and command based on revoked status
    if is_revoked:
        floor_btn_text = "Grant Floor"
        floor_btn_command = grant_floor_callback
    else:
        floor_btn_text = "Revoke Floor"
        floor_btn_command = revoke_floor_callback
    
    # Create revoke/grant floor button
    floor_btn = CTkButton(agent_frame, text=floor_btn_text, width=90, height=25,
                         command=floor_btn_command)
    floor_btn.pack(side="left", padx=5, pady=5)
    
    # Create uninvite button
    uninvite_btn = CTkButton(agent_frame, text="Uninvite", width=80, height=25,
                            command=uninvite_callback)
    uninvite_btn.pack(side="left", padx=(0,5), pady=5)
    
    # Create textbox for agent info
    textbox = CTkEntry(agent_frame, placeholder_text=agent_info)
    textbox.insert(0, agent_info)
    
    # Apply strikethrough if floor has been revoked
    if is_revoked:
        # Create a struck-through version of the text
        struck_text = ''.join([char + '\u0336' for char in agent_info])
        textbox.delete(0, 'end')
        textbox.insert(0, struck_text)
    
    textbox.configure(state="disabled")
    textbox.pack(side="left", fill="x", expand=True, padx=(0,5), pady=5)
    
    # Create checkbox for private messaging when send_to_all is unchecked
    agent_checkbox = CTkCheckBox(agent_frame, text="", width=30)
    agent_checkbox.pack(side="left", padx=(0,5), pady=5)
    
    return agent_frame, textbox, uninvite_btn, floor_btn, agent_checkbox


def update_agent_textbox_ui(textbox, new_info):
    """Update an agent textbox with new information."""
    textbox.configure(state="normal")
    textbox.delete(0, 'end')
    textbox.insert(0, new_info)
    textbox.configure(state="disabled")


def display_response_json(root, response_data, assistant_name, assistant_url):
    """Display JSON response in a new window."""
    response_window = CTkToplevel(root)
    title = f"Assistant Response from {assistant_name} at {assistant_url}"
    response_window.title(title)
    response_window.geometry("600x400")
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(response_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)


def display_response_html(html_content):
    """Display HTML response in a browser."""
    file_path = Path.cwd() / "cards.html"
    file_path.write_text(html_content, encoding="utf-8")
    webbrowser.open(file_path.as_uri())


def show_outgoing_event_window(root, outgoing_events, invited_agents, extract_url_func):
    """Display all outgoing events in a window and send to invited agents."""
    if not outgoing_events:
        messagebox.showinfo("Info", "No outgoing events to show")
        return
    
    # Send all events to all invited agents
    if invited_agents:
        target_urls = [extract_url_func(agent) for agent in invited_agents]
        for event in outgoing_events:
            for url in target_urls:
                try:
                    response = requests.post(url, json=event.to_json(as_payload=True))
                    print(f"Sent event to {url}: {response.status_code}")
                except Exception as e:
                    print(f"Error sending to {url}: {e}")
    
    # Display all events
    event_window = CTkToplevel(root)
    event_window.title("Outgoing Events")
    event_text = CTkTextbox(event_window, wrap='word', width=600, height=400)
    
    # Combine all events into a single display
    all_events_text = ""
    for i, event in enumerate(outgoing_events, 1):
        all_events_text += f"\n{'='*60}\nEvent {i}:\n{'='*60}\n"
        all_events_text += event.to_json(as_payload=True, indent=2) + "\n"
    
    event_text.insert('insert', all_events_text)
    event_text.configure(state='disabled')
    event_text.pack(pady=10, padx=10)


def escape_blanks_in_url(url):
    """Escape blanks (spaces) in URLs by replacing them with %20."""
    blank_pattern = r'\s+'
    escaped_url = re.sub(blank_pattern, '%20', url)
    return escaped_url


def convert_text_to_html(text):
    """Convert text to HTML with URL detection and blank escaping."""
    # Check if the text already contains HTML tags (like img tags)
    if '<' in text and '>' in text:
        # If it's already HTML, don't process it further to avoid breaking image links
        return text
    
    # Only process plain text for URL detection
    # Improved URL detection to prevent trailing punctuation issues
    url_pattern = r'(?<!\w)(https?://[^\s<>"\'()]+[^\s<>"\'().,])(?!\w)'

    def url_replacer(match):
        url = match.group(0)
        # Escape any blanks in the URL before creating the link
        escaped_url = escape_blanks_in_url(url)
        return f'<a href="{escaped_url}" target="_blank">{url}</a>'
    
    text_with_links = re.sub(url_pattern, url_replacer, text)
    return text_with_links


def start_floor_manager_ui(root, client_uri, client_url, client_name):
    """Start a new floor manager and show its window."""
    try:
        # Create floor manager with current client as convener
        floor_manager = floor.create_floor_manager(convener_uri=client_uri)
        
        # Add the client as a conversant
        floor_manager.add_conversant(
            speaker_uri=client_uri,
            service_url=client_url,
            conversational_name=client_name,
            roles={floor.FloorRole.CONVENER}
        )
        
        # Show floor manager window
        show_floor_manager_window(root, floor_manager)
        
        CTkMessagebox(title="Floor Manager", 
                     message="Floor manager started successfully!", 
                     icon="info")
        
        return floor_manager
    except Exception as e:
        CTkMessagebox(title="Error", 
                     message=f"Failed to start floor manager: {str(e)}", 
                     icon="cancel")
        return None


def show_floor_manager_window(root, floor_manager):
    """Show the floor manager status window."""
    if not floor_manager:
        CTkMessagebox(title="Error", 
                     message="No floor manager is running", 
                     icon="cancel")
        return
        
    floor_window = CTkToplevel(root)
    floor_window.title("Floor Manager Status")
    floor_window.geometry("500x400")
    
    # Get floor status
    status = floor_manager.get_floor_status()
    
    # Create text widget to display status
    status_text = CTkTextbox(floor_window, wrap="word", width=480, height=350)
    status_text.insert("0.0", json.dumps(status, indent=2))
    status_text.configure(state="disabled")
    status_text.pack(padx=10, pady=10)
    
    # Add refresh button
    def refresh_status():
        status = floor_manager.get_floor_status()
        status_text.configure(state="normal")
        status_text.delete("0.0", "end")
        status_text.insert("0.0", json.dumps(status, indent=2))
        status_text.configure(state="disabled")
    
    refresh_button = CTkButton(floor_window, text="Refresh", command=refresh_status)
    refresh_button.pack(pady=5)
