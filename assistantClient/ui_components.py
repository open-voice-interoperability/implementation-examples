"""UI components for the Assistant Client application."""

import tkinter as tk
import sys
from customtkinter import (
    CTk, CTkLabel, CTkEntry, CTkButton, CTkTextbox, CTkToplevel, 
    CTkComboBox, CTkCheckBox, CTkScrollableFrame, CTkFrame,
    set_appearance_mode, set_default_color_theme
)
import json
import re
from pathlib import Path
import webbrowser
import floor

_APP_ICON_SOURCE_PATH = Path(__file__).resolve().parent / "assets" / "Interoperability_Logo_icon_color.png"
_APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "Interoperability_Logo_icon_color_bold.png"
_APP_ICON_ICO_PATH = Path(__file__).resolve().parent / "assets" / "Interoperability_Logo_icon_color_bold.ico"
_APP_ICON_ICO_META_PATH = Path(__file__).resolve().parent / "assets" / "Interoperability_Logo_icon_color_bold.ico.meta.json"
_APP_ICON_ICO_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (96, 96), (128, 128), (256, 256)]
_APP_ICON_BOLDEN_PASSES = 2
_APP_ICON_WHITE_BACKGROUND = True
_APP_ICON_PADDING_RATIO = 0.16
_APP_ICON_PADDING_MIN_PX = 2
_APP_ICON_PADDING_MAX_PX = 64
_app_icon_photo = None
_app_icon_ico_ready = False


def _ensure_windows_ico() -> None:
    """Create a Windows .ico from the PNG if needed (best-effort)."""
    global _app_icon_ico_ready
    if _app_icon_ico_ready:
        return
    _app_icon_ico_ready = True

    try:
        if not _APP_ICON_SOURCE_PATH.exists():
            return

        # Regenerate if the ICO is missing or if our desired parameters have changed.
        # - trimTransparent: makes the icon fill the titlebar slot better
        # - boldenPasses: thickens strokes for readability at 16x16
        desired_meta = {
            "sizes": _APP_ICON_ICO_SIZES,
            "trimTransparent": True,
            "boldenPasses": _APP_ICON_BOLDEN_PASSES,
            "boldenMethod": "stroke",
            "whiteBackground": bool(_APP_ICON_WHITE_BACKGROUND),
            "paddingRatio": float(_APP_ICON_PADDING_RATIO),
            "paddingMinPx": int(_APP_ICON_PADDING_MIN_PX),
            "paddingMaxPx": int(_APP_ICON_PADDING_MAX_PX),
        }
        if _APP_ICON_ICO_PATH.exists() and _APP_ICON_ICO_META_PATH.exists():
            try:
                existing_meta = json.loads(_APP_ICON_ICO_META_PATH.read_text(encoding="utf-8"))
                if existing_meta == desired_meta:
                    return
            except Exception:
                pass

        # Pillow is commonly available; use it to generate a proper multi-size ICO.
        from PIL import Image

        def _translated_rgba(src: "Image.Image", dx: int, dy: int) -> "Image.Image":
            dst = Image.new("RGBA", src.size, (0, 0, 0, 0))
            if dx == 0 and dy == 0:
                dst.alpha_composite(src)
                return dst

            src_w, src_h = src.size
            w = src_w - abs(dx)
            h = src_h - abs(dy)
            if w <= 0 or h <= 0:
                return dst

            src_x0 = max(-dx, 0)
            src_y0 = max(-dy, 0)
            dst_x0 = max(dx, 0)
            dst_y0 = max(dy, 0)
            crop = src.crop((src_x0, src_y0, src_x0 + w, src_y0 + h))
            dst.paste(crop, (dst_x0, dst_y0), crop)
            return dst

        def _stroke_thicken(src: "Image.Image", passes: int) -> "Image.Image":
            # Build a thicker "stroke" by compositing small translations.
            # This preserves color and reliably increases perceived thickness
            # at tiny sizes (e.g., 16x16) without washing out dark outlines.
            offsets = [
                (0, 0),
                (1, 0), (-1, 0),
                (0, 1), (0, -1),
                (1, 1), (1, -1),
                (-1, 1), (-1, -1),
            ]
            out = src
            for _ in range(max(0, int(passes))):
                base = out
                out = Image.new("RGBA", base.size, (0, 0, 0, 0))
                for dx, dy in offsets:
                    out.alpha_composite(_translated_rgba(base, dx, dy))
            return out

        with Image.open(_APP_ICON_SOURCE_PATH) as im:
            im = im.convert("RGBA")

            # If the source image has lots of transparent padding, Windows will
            # render it looking "small" inside the 16x16 titlebar icon slot.
            # Cropping to the alpha bounding box makes it fill the icon box.
            try:
                alpha = im.getchannel("A")
                bbox = alpha.getbbox()
                if bbox:
                    im = im.crop(bbox)
            except Exception:
                pass

            try:
                im = _stroke_thicken(im, _APP_ICON_BOLDEN_PASSES)
            except Exception:
                pass

            # Add some whitespace padding so the icon isn't visually cramped in
            # the small titlebar icon slot.
            try:
                w, h = im.size
                base = max(w, h)
                pad = int(round(base * float(_APP_ICON_PADDING_RATIO)))
                pad = max(int(_APP_ICON_PADDING_MIN_PX), min(int(_APP_ICON_PADDING_MAX_PX), pad))
                if pad > 0:
                    padded = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
                    padded.alpha_composite(im, (pad, pad))
                    im = padded
            except Exception:
                pass

            # Make the background explicitly white (opaque) so the icon has
            # strong contrast against dark titlebars.
            if _APP_ICON_WHITE_BACKGROUND:
                try:
                    white = Image.new("RGBA", im.size, (255, 255, 255, 255))
                    white.alpha_composite(im)
                    im = white
                except Exception:
                    pass

            # Save derived bold PNG so iconphoto() matches the Windows ICO.
            try:
                im.save(_APP_ICON_PATH, format="PNG")
            except Exception:
                pass

            # Provide multiple icon sizes so Windows can pick the best match for
            # the current DPI/titlebar/taskbar context.
            im.save(_APP_ICON_ICO_PATH, format="ICO", sizes=_APP_ICON_ICO_SIZES)

        try:
            _APP_ICON_ICO_META_PATH.write_text(json.dumps(desired_meta, indent=2), encoding="utf-8")
        except Exception:
            pass
    except Exception:
        # If conversion fails, fall back to iconphoto-only.
        return


def apply_app_icon(window):
    """Apply the official Interoperability Initiative color icon to a Tk/CTk window."""
    global _app_icon_photo
    try:
        # Windows: iconbitmap with .ico is the most reliable way to update the
        # top-left/titlebar icon and taskbar icon.
        if sys.platform.startswith("win"):
            _ensure_windows_ico()
            if _APP_ICON_ICO_PATH.exists():
                try:
                    window.iconbitmap(default=str(_APP_ICON_ICO_PATH))
                except Exception:
                    pass

        if _app_icon_photo is None:
            if _APP_ICON_PATH.exists():
                _app_icon_photo = tk.PhotoImage(file=str(_APP_ICON_PATH))
        if _app_icon_photo is not None:
            window.iconphoto(True, _app_icon_photo)
    except Exception:
        # Icon setting is best-effort; don't break the UI if unsupported.
        pass


def show_app_message(root, title: str, message: str, *, modal: bool = True):
    """Show a simple message window that uses the app icon.

    This is used instead of CTkMessagebox/tkinter.messagebox so popups match the
    main window icon on Windows.
    """
    window = CTkToplevel(root)
    window.title(title)
    window.geometry("520x200")
    window.resizable(False, False)
    apply_app_icon(window)

    try:
        window.transient(root)
    except Exception:
        pass

    container = CTkFrame(window)
    container.pack(fill="both", expand=True, padx=12, pady=12)

    label = CTkLabel(container, text=message, justify="left", anchor="w", wraplength=490)
    label.pack(fill="both", expand=True, padx=6, pady=(6, 12))

    def _close():
        try:
            window.destroy()
        except Exception:
            pass

    ok_btn = CTkButton(container, text="OK", command=_close, text_color=BUTTON_TEXT_COLOR)
    ok_btn.pack(anchor="e", padx=6, pady=(0, 6))

    try:
        window.lift()
        window.focus_force()
    except Exception:
        pass

    if modal:
        try:
            window.grab_set()
        except Exception:
            pass
        try:
            window.wait_window()
        except Exception:
            pass


def setup_appearance():
    """Configure the UI appearance settings."""
    set_appearance_mode("light")
    set_default_color_theme("blue")


BUTTON_TEXT_COLOR = "#FFFFFF"
HEADING_FONT = ("Arial", 14, "bold")


def create_main_window():
    """Create and configure the main application window."""
    root = CTk()
    root.title("Open Floor Client Assistant")
    # Shorter by default now that errors are shown in a separate window.
    root.geometry("750x850")
    apply_app_icon(root)
    return root


def create_ui_elements(root, known_agents):
    """Create all UI elements and return references to important widgets.
    
    Returns:
        dict: Dictionary containing references to all UI widgets
    """
    widgets = {}

    # Main content frame (everything except the bottom event controls).
    # This keeps the bottom controls visible even when the window is small.
    content_frame = CTkFrame(root)
    content_frame.pack(side="top", fill="both", expand=True)
    
    # Conversation history
    CTkLabel(content_frame, text="Conversation History:", font=HEADING_FONT).pack(pady=(5, 0))
    widgets['conversation_text'] = CTkTextbox(content_frame, wrap='word', height=150)
    widgets['conversation_text'].configure(state='disabled')
    widgets['conversation_text'].pack(pady=5, padx=20, fill="both")
    
    # Text entry
    CTkLabel(content_frame, text="Enter text for utterance:", font=HEADING_FONT).pack(pady=(10, 0))
    widgets['entry'] = CTkEntry(content_frame, width=400)
    widgets['entry'].pack(pady=5, padx=20)
    
    # Send utterance button (directly below text entry)
    widgets['send_utterance_button'] = CTkButton(
        content_frame,
        text="Send Utterance",
        text_color=BUTTON_TEXT_COLOR,
        text_color_disabled=BUTTON_TEXT_COLOR,
    )
    widgets['send_utterance_button'].pack(pady=5)
    
    # URL combobox
    CTkLabel(content_frame, text="Assistant URL:", font=HEADING_FONT).pack(pady=(10, 0))
    widgets['url_combobox'] = CTkComboBox(content_frame, width=400, values=known_agents, state="normal")
    widgets['url_combobox'].set(known_agents[0] if known_agents else "http://localhost:8767/")
    widgets['url_combobox'].pack(pady=5, padx=20)
    
    # Send to all checkbox
    widgets['send_to_all_checkbox'] = CTkCheckBox(content_frame, text="Send to all invited agents")
    widgets['send_to_all_checkbox'].select()  # Checked by default
    widgets['send_to_all_checkbox'].pack(pady=5)

    
    # Top buttons frame
    buttons_frame = CTkFrame(content_frame)
    buttons_frame.pack(pady=(10, 5))
    
    widgets['get_manifests_button'] = CTkButton(buttons_frame, text="Get Manifests", text_color=BUTTON_TEXT_COLOR)
    widgets['get_manifests_button'].pack(side="left", padx=5)
    
    widgets['invite_button'] = CTkButton(buttons_frame, text="Invite", text_color=BUTTON_TEXT_COLOR)
    widgets['invite_button'].pack(side="left", padx=5)
    
    # Agent list section
    CTkLabel(content_frame, text="Agents invited to the floor:", font=HEADING_FONT).pack(pady=(10, 0))
    CTkLabel(content_frame, text="Send private message to this agent", 
             font=("Arial", 9), anchor="e").pack(pady=(0, 0), padx=20, anchor="e")
    
    widgets['agents_frame'] = CTkScrollableFrame(content_frame, height=200, fg_color="white")
    widgets['agents_frame'].pack(pady=5, padx=20, fill="both", expand=False)
    
    widgets['no_agents_label'] = CTkLabel(widgets['agents_frame'], text="No agents invited yet")
    widgets['no_agents_label'].pack(pady=10)
    
    # Bottom buttons frame
    bottom_buttons_frame = CTkFrame(root)
    bottom_buttons_frame.pack(side="bottom", fill="x", pady=(10, 5))

    widgets['show_outgoing_events_checkbox'] = CTkCheckBox(bottom_buttons_frame, text="show outgoing events")
    # Unchecked by default
    widgets['show_outgoing_events_checkbox'].deselect()
    widgets['show_outgoing_events_checkbox'].pack(side="left", padx=5)

    widgets['show_incoming_events_checkbox'] = CTkCheckBox(bottom_buttons_frame, text="show incoming events")
    # Unchecked by default (do not auto-pop incoming events)
    widgets['show_incoming_events_checkbox'].deselect()
    widgets['show_incoming_events_checkbox'].pack(side="left", padx=5)

    widgets['show_error_log_checkbox'] = CTkCheckBox(bottom_buttons_frame, text="show error log")
    # Unchecked by default
    widgets['show_error_log_checkbox'].deselect()
    widgets['show_error_log_checkbox'].pack(side="left", padx=5)
    
    widgets['start_floor_button'] = CTkButton(bottom_buttons_frame, text="Start Floor Manager", text_color=BUTTON_TEXT_COLOR)
    # widgets['start_floor_button'].pack(side="left", padx=5)  # Hidden - auto-started on launch
    
    return widgets


def create_error_log_window(root):
    """Create an error log window with a read-only textbox."""
    window = CTkToplevel(root)
    window.title("Error Log")
    window.geometry("700x450")
    apply_app_icon(window)

    text = CTkTextbox(window, wrap='word', width=700, height=450)
    text.configure(state='disabled')
    text.pack(padx=10, pady=10, fill="both", expand=True)
    return window, text


def create_agent_textbox_ui(agents_frame, agent_info, agent_url, 
                            is_revoked, grant_floor_callback, 
                            revoke_floor_callback, uninvite_callback):
    """Create a frame with buttons and textbox for a specific agent.
    
    Args:
        agents_frame: Parent frame to contain the agent UI
        agent_info: Agent information dict with 'url' and 'conversational_name'
        agent_url: Agent's service URL
        is_revoked: Whether the agent's floor has been revoked
        grant_floor_callback: Function to call when granting floor
        revoke_floor_callback: Function to call when revoking floor
        uninvite_callback: Function to call when uninviting
        
    Returns:
        tuple: (agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, checkbox)
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
                         command=floor_btn_command, text_color=BUTTON_TEXT_COLOR)
    floor_btn.pack(side="left", padx=5, pady=5)
    
    # Create uninvite button
    uninvite_btn = CTkButton(agent_frame, text="Uninvite", width=80, height=25,
                            command=uninvite_callback, text_color=BUTTON_TEXT_COLOR)
    uninvite_btn.pack(side="left", padx=(0,5), pady=5)
    
    # Extract conversational name and URL from agent_info
    if isinstance(agent_info, dict):
        conversational_name = agent_info.get('conversational_name', '')
        url_display = agent_info.get('url', agent_url)
    else:
        # Backwards compatibility: if agent_info is just a string URL
        conversational_name = ''
        url_display = agent_info
    
    # Create textbox for conversational name (left side)
    name_textbox = CTkEntry(agent_frame, placeholder_text="Name", width=150)
    if conversational_name:
        name_textbox.insert(0, conversational_name)
    
    # Apply strikethrough if floor has been revoked
    if is_revoked and conversational_name:
        struck_text = ''.join([char + '\u0336' for char in conversational_name])
        name_textbox.delete(0, 'end')
        name_textbox.insert(0, struck_text)
    
    name_textbox.configure(state="disabled")
    name_textbox.pack(side="left", padx=(0,5), pady=5)
    
    # Create textbox for URL (right side, expandable)
    url_textbox = CTkEntry(agent_frame, placeholder_text=url_display)
    url_textbox.insert(0, url_display)
    
    # Apply strikethrough if floor has been revoked
    if is_revoked:
        struck_text = ''.join([char + '\u0336' for char in url_display])
        url_textbox.delete(0, 'end')
        url_textbox.insert(0, struck_text)
    
    url_textbox.configure(state="disabled")
    url_textbox.pack(side="left", fill="x", expand=True, padx=(0,5), pady=5)
    
    # Create checkbox for private messaging when send_to_all is unchecked
    agent_checkbox = CTkCheckBox(agent_frame, text="", width=30)
    agent_checkbox.pack(side="left", padx=(0,5), pady=5)
    
    return agent_frame, url_textbox, name_textbox, uninvite_btn, floor_btn, agent_checkbox


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
    apply_app_icon(response_window)
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(response_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)


def display_incoming_event_json(root, event_data, assistant_name, assistant_url):
    """Display a single incoming event (dict) in its own window."""
    response_window = CTkToplevel(root)
    apply_app_icon(response_window)
    event_type = ""
    try:
        if isinstance(event_data, dict):
            event_type = event_data.get("eventType", "")
    except Exception:
        event_type = ""

    title = f"Incoming Event{f' ({event_type})' if event_type else ''} from {assistant_name} at {assistant_url}"
    response_window.title(title)
    response_window.geometry("600x400")
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(event_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)


def display_outgoing_envelope_json(root, envelope_data, target_label: str = ""):
    """Display a single outgoing envelope (dict) in its own window."""
    response_window = CTkToplevel(root)
    title = "Outgoing Envelope"
    if target_label:
        title += f" to {target_label}"
    response_window.title(title)
    response_window.geometry("600x400")
    apply_app_icon(response_window)
    response_text = CTkTextbox(response_window, wrap="word", width=600, height=400)
    response_text.insert("0.0", json.dumps(envelope_data, indent=2))
    response_text.configure(state="disabled")
    response_text.pack(padx=10, pady=10)


def display_response_html(html_content):
    """Display HTML response in a browser."""
    file_path = Path.cwd() / "cards.html"
    file_path.write_text(html_content, encoding="utf-8")
    webbrowser.open(file_path.as_uri())


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


def start_floor_manager_ui(root, client_uri, client_url, client_name, show_window=True, show_message=True):
    """Start a new floor manager and optionally show its window."""
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
        
        # Show floor manager window only if requested
        if show_window:
            show_floor_manager_window(root, floor_manager)
        
        if show_message:
            show_app_message(root, "Floor Manager", "Floor manager started successfully!")
        
        return floor_manager
    except Exception as e:
        show_app_message(root, "Error", f"Failed to start floor manager: {str(e)}")
        return None


def show_floor_manager_window(root, floor_manager):
    """Show the floor manager status window."""
    if not floor_manager:
        show_app_message(root, "Error", "No floor manager is running")
        return
        
    floor_window = CTkToplevel(root)
    floor_window.title("Floor Manager Status")
    floor_window.geometry("500x400")
    apply_app_icon(floor_window)
    
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
    
    refresh_button = CTkButton(floor_window, text="Refresh", command=refresh_status, text_color=BUTTON_TEXT_COLOR)
    refresh_button.pack(pady=5)
