from flask import Flask, request, Response
from flask_cors import CORS
import json
import re
import tempfile
import uuid
import os

from stella_agent import load_manifest_from_config, StellaAgent
from openfloor.envelope import Envelope

# Flask app instance
app = Flask(__name__)
CORS(app)

# Cache the agent at import time
manifest = load_manifest_from_config()
agent = StellaAgent(manifest)


@app.route("/", methods=["POST"])
def home():
    payload_text = request.get_data(as_text=True)

    # Convert to Envelope
    try:
        in_envelope = Envelope.from_json(payload_text, as_payload=True)
    except Exception:
        try:
            in_envelope = Envelope.from_json(json.dumps(request.get_json()), as_payload=True)
        except Exception as e:
            return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process envelope
    out_envelope = agent.process_envelope(in_envelope)
    payload_str = out_envelope.to_json(as_payload=True)
    raw_payload_str = payload_str

    # Write a temp copy for debugging
    try:
        tmp_dir = tempfile.gettempdir()
        dump_name = f"stella_outgoing_raw_{uuid.uuid4().hex}.json"
        dump_path = os.path.join(tmp_dir, dump_name)
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(raw_payload_str)
        print(f"Wrote raw outgoing payload to: {dump_path} (chars: {len(raw_payload_str)})")
    except Exception as e:
        print("Failed to write raw payload:", e)

    # Log outgoing payload
    try:
        payload_obj = json.loads(payload_str)
        print("Outgoing payload:", json.dumps(payload_obj))
    except Exception:
        payload_obj = None
        print("Outgoing payload (raw):", payload_str)

    # Diagnostic scan for relative paths
    def _is_url_like(s: str) -> bool:
        s = s.strip()
        return s.startswith(("http://", "https://", "file:", "data:", "mailto:"))

    def _is_windows_abs(s: str) -> bool:
        return bool(re.match(r"^[A-Za-z]:[\\/].*", s))

    def _looks_like_mime(s: str) -> bool:
        return bool(re.match(r"^[\w!#$&^_\.+-]+/[\w!#$&^_\.+-]+$", s))

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
            if not s or _is_url_like(s) or _is_windows_abs(s) or _looks_like_mime(s):
                return findings
            if s.startswith(("./", "../")) or ".." in s or "\\" in s or ("/" in s and (len(s.split("/")) >= 2)):
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
            print("No suspicious relative path-like strings detected.")
    except Exception as e:
        print("Could not parse outgoing payload for diagnostics:", e)

    # Return the JSON response
    resp = Response(payload_str, mimetype="application/json")
    try:
        resp.headers["X-Outgoing-Length"] = str(len(payload_str))
    except Exception:
        pass
    return resp
