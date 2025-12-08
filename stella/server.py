#!/usr/bin/env python3
"""
Minimal Flask server for StellaAgent.
Handles a single POST endpoint at '/' that accepts an OpenFloor envelope.
Works locally and on Vercel.
"""

from flask import Flask, request, Response
from flask_cors import CORS
import os
import json

from stella_agent import load_manifest_from_config, StellaAgent
from openfloor.envelope import Envelope

# ----------------------------
# Setup
# ----------------------------
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Use Vercel's assigned port or default to 8767 for local testing
port = int(os.environ.get("PORT", 8767))

# Load the agent once at startup
manifest = load_manifest_from_config()
agent = StellaAgent(manifest)

# ----------------------------
# Routes
# ----------------------------
@app.route("/", methods=["POST"])
def handle_post():
    payload_text = request.get_data(as_text=True)
    # Dynamically update the manifest serviceUrl
    host = request.headers.get("Host")
    print(f"DEBUG server.py: Host header={host}", flush=True)
    if host:
        agent._manifest.identification.serviceUrl = f"https://{host}"
        print(f"DEBUG server.py: Updated serviceUrl to {agent._manifest.identification.serviceUrl}", flush=True)
    # Convert incoming JSON to Envelope
    try:
        in_envelope = Envelope.from_json(payload_text, as_payload=True)
    except Exception:
        try:
            in_envelope = Envelope.from_json(json.dumps(request.get_json()), as_payload=True)
        except Exception as e:
            return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process
    out_envelope = agent.process_envelope(in_envelope)
    payload_str = out_envelope.to_json(as_payload=True)

    print(f"Incoming payload length: {len(payload_text)}")
    print(f"Outgoing payload length: {len(payload_str)}")

    resp = Response(payload_str, mimetype="application/json")
    resp.headers["X-Outgoing-Length"] = str(len(payload_str))
    return resp


# ----------------------------
# Run server
# ----------------------------
if __name__ == "__main__":
    # Listen on all interfaces for Vercel (0.0.0.0)
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
