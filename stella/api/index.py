#!/usr/bin/env python3
"""
Vercel-ready Flask server for StellaAgent.
Supports local testing (flask run) and deployment on Vercel.
"""
from flask import Flask, request, Response
from flask_cors import CORS
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Agent imports
from stella_agent import load_manifest_from_config, StellaAgent
from openfloor.envelope import Envelope

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

manifest = None
agent = None
startup_error = None


def _get_agent():
    global manifest, agent, startup_error
    if agent is not None:
        return agent, None
    if startup_error is not None:
        return None, startup_error

    try:
        manifest = load_manifest_from_config()
        agent = StellaAgent(manifest)
        return agent, None
    except Exception as exc:
        startup_error = str(exc)
        print(f"ERROR server.py: Agent startup failed: {startup_error}", flush=True)
        return None, startup_error

@app.route("/", methods=["POST"])
@app.route("/api", methods=["POST"])
@app.route("/api/", methods=["POST"])
def handle_request():
    payload_text = request.get_data(as_text=True)

    current_agent, init_error = _get_agent()
    if init_error:
        return Response(f"Agent startup error: {init_error}", status=500)
    
    # Dynamically update the manifest serviceUrl
    host = request.headers.get("Host")
    print(f"DEBUG server.py: Host header={host}", flush=True)
    if host:
        current_agent._manifest.identification.serviceUrl = f"https://{host}"
        print(f"DEBUG server.py: Updated serviceUrl to {current_agent._manifest.identification.serviceUrl}", flush=True)

    # Parse incoming envelope
    try:
        in_envelope = Envelope.from_json(payload_text, as_payload=True)
    except Exception:
        try:
            in_envelope = Envelope.from_json(json.dumps(request.get_json()), as_payload=True)
        except Exception as e:
            return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process and serialize response
    out_envelope = current_agent.process_envelope(in_envelope)
    payload_str = out_envelope.to_json(as_payload=True)

    return Response(payload_str, mimetype="application/json")


# Vercel WSGI handler - this is the correct way to expose Flask for Vercel
app = app

# -----------------------
# Local test entrypoint
# -----------------------
if __name__ == "__main__":
    print("Starting local Flask server on http://localhost:8767")
    app.run(host="localhost", port=8767, debug=True)
