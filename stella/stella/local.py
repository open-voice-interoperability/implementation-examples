#!/usr/bin/env python3
"""
Local Flask server for StellaAgent. Provides a single POST endpoint that
accepts an OpenFloor envelope, runs the agent, and returns the agent's
serialized envelope. Includes diagnostics to detect path-like strings in
the outgoing payload.
"""
from flask import Flask, request, Response
from flask_cors import CORS
import json
import re

from stella_agent import load_manifest_from_config, StellaAgent
from openfloor.envelope import Envelope
import tempfile
import uuid
import os


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
port = 8767

# Create and cache the agent at module import time so it's reused across requests
manifest = load_manifest_from_config()
agent = StellaAgent(manifest)


@app.route('/', methods=['POST'])
def home():
    print("Headers:", dict(request.headers))
    payload_text = request.get_data(as_text=True)
    #print("Payload text:", payload_text[:200])
    
    # Accept raw JSON payloads containing an OpenFloor 'openFloor' wrapper
    payload_text = request.get_data(as_text=True)

    # Convert to an Envelope (expecting the payload to be the OpenFloor wrapper)
    try:
        in_envelope = Envelope.from_json(payload_text, as_payload=True)
    except Exception:
        # Fallback: try to build from a dict (Flask already parsed JSON)
        try:
            in_envelope = Envelope.from_json(json.dumps(request.get_json()), as_payload=True)
        except Exception as e:
            return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process the envelope and produce an outgoing envelope
    out_envelope = agent.process_envelope(in_envelope)
    # Ensure we return a real JSON object (the OpenFloor wrapper) so clients
    # always receive the full payload with events.
    payload_str = out_envelope.to_json(as_payload=True)
    # Keep a copy of the raw outgoing payload (before any sanitization)
    raw_payload_str = payload_str
    try:
        raw_len = len(raw_payload_str or "")
    except Exception:
        raw_len = -1
    try:
        tmp_dir = tempfile.gettempdir()
        dump_name = f"stella_outgoing_raw_{uuid.uuid4().hex}.json"
        dump_path = os.path.join(tmp_dir, dump_name)
        with open(dump_path, "w", encoding="utf-8") as dumpf:
            dumpf.write(raw_payload_str)
        print(f"Wrote raw outgoing payload to: {dump_path} (chars: {raw_len})")
    except Exception as e:
        print("Failed to write raw outgoing payload to temp file:", e)
    try:
        payload_obj = json.loads(payload_str)
    except Exception:
        # If for some reason the envelope serialization is not valid JSON,
        # fall back to returning the raw string (rare).
        payload_obj = None

    # Log outgoing payload for debugging
    try:
        print("Outgoing payload:", json.dumps(payload_obj or payload_str))
    except Exception:
        print("Outgoing payload (raw):", payload_str)

    # Diagnostic scan: look for string fields that look like relative paths.
    # Many clients convert path-like strings to file:// URIs and will raise
    # "relative path can't be expressed as a file uri" when they encounter
    # a relative path. This scanner prints any suspicious values with their
    # JSON path so you can identify the offending field.
    def _is_url_like(s: str) -> bool:
        s = s.strip()
        return s.startswith("http://") or s.startswith("https://") or s.startswith("file:") or s.startswith("data:") or s.startswith("mailto:")

    def _is_windows_abs(s: str) -> bool:
        # e.g. C:\ or C:/
        return bool(re.match(r"^[A-Za-z]:[\\/].*", s))

    def _looks_like_mime(s: str) -> bool:
        # common mime type pattern like text/plain or application/json
        return bool(re.match(r"^[A-Za-z0-9!#$&^_\.+-]+\/[A-Za-z0-9!#$&^_\.+-]+$", s))

    def _scan(obj, path="$"):
        findings = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                findings += _scan(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                findings += _scan(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            s = obj.strip()
            # Avoid false positives: skip obvious non-filesystem things
            if not s:
                return findings
            # If it's a URL, a MIME type, or contains HTML markers or whitespace, skip
            if _is_url_like(s) or _is_windows_abs(s) or _looks_like_mime(s):
                return findings
            if "<" in s or ">" in s or re.search(r"\s", s):
                # Contains HTML or whitespace/newlines (likely not a filesystem path)
                return findings

            # Now apply heuristics for filesystem-like strings
            #  - relative segments (./, ../)
            #  - contains backslashes (Windows-style relative)
            #  - contains slashes and looks short-ish (no spaces) and contains dot segments or extensions
            if s.startswith("./") or s.startswith("../") or ".." in s:
                findings.append((path, s))
            elif "\\" in s and not _is_url_like(s):
                findings.append((path, s))
            elif "/" in s:
                # Heuristic: treat as suspicious only if it looks like a path (has extension or multiple segments)
                parts = s.split("/")
                if len(parts) >= 2:
                    last = parts[-1]
                    if "." in last or len(parts) >= 3:
                        findings.append((path, s))
        return findings

    try:
        parsed = json.loads(payload_str)
        rel_paths = _scan(parsed)
        if rel_paths:
            print("Detected potential relative path-like strings in outgoing envelope:")
            for p, val in rel_paths:
                print(f"  {p}: {val}")
        else:
            print("No suspicious relative path-like strings detected in outgoing envelope.")
    except Exception as e:
        print("Could not parse outgoing payload for diagnostics:", e)

    # Optional sanitization pass: remove embedded HTML-like or very large
    # multiline strings which some clients attempt to treat as filesystem
    # paths or write to temp files. We only run this when the toggle is set.
    
    # Return the original serialized envelope string to preserve exact formatting
    # Extra debug info: print sizes so we can see if the response is empty/truncated
    try:
        incoming_len = len(payload_text or "")
    except Exception:
        incoming_len = -1
    try:
        outgoing_len = len(payload_str or "")
    except Exception:
        outgoing_len = -1
    print(f"Incoming payload length: {incoming_len}")
    print(f"Outgoing payload length (chars): {outgoing_len}")
    preview = (payload_str or "")[:300]
    print("Outgoing payload preview:", preview.replace("\n", "\\n")[:1000])
    resp = Response(payload_str, mimetype='application/json')
    # Explicit header to help clients/debuggers
    try:
        resp.headers['X-Outgoing-Length'] = str(outgoing_len)
    except Exception:
        pass
    return resp


if __name__ == '__main__':
    app.run(host="localhost", port=port, debug=True, use_reloader=False)