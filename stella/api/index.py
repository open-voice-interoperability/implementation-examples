#!/usr/bin/env python3
"""
Vercel-ready Flask server for Stella.
Runs the same TemplateAgent as flask_server.py (the local server), so local
and Vercel deployments behave identically.
Supports local testing (flask run) and deployment on Vercel.
"""
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
import sys
import os
import traceback

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
        # Defer imports so module import failures are surfaced as runtime
        # startup errors instead of crashing Vercel entrypoint loading.
        from template_agent import TemplateAgent, load_manifest_from_config

        manifest = load_manifest_from_config()
        agent = TemplateAgent(manifest)
        return agent, None
    except Exception as exc:
        startup_error = f"{exc.__class__.__name__}: {exc}"
        print(f"ERROR server.py: Agent startup failed: {startup_error}", flush=True)
        print(traceback.format_exc(), flush=True)
        return None, startup_error

@app.route("/", methods=["POST"])
@app.route("/api", methods=["POST"])
@app.route("/api/", methods=["POST"])
def handle_request():
    payload_text = request.get_data(as_text=True)
    if not payload_text:
        return Response("Invalid OpenFloor payload: empty request body", status=400)

    current_agent, init_error = _get_agent()
    if init_error:
        return Response(f"Agent startup error: {init_error}", status=500)
    
    # Identify as whatever host this request reached (production alias or a
    # preview URL), matching flask_server.py's _apply_runtime_identity, so
    # TemplateAgent's _is_addressed_to_me recognizes events sent to it.
    host = request.headers.get("Host")
    if host:
        base_url = f"https://{host}"
        identification = current_agent._manifest.identification
        identification.serviceUrl = base_url
        speaker_uri = getattr(identification, "speakerUri", "") or ""
        if speaker_uri.startswith("http://") or speaker_uri.startswith("https://"):
            identification.speakerUri = base_url

    import envelope_handler

    # Parse incoming envelope
    try:
        in_envelope = envelope_handler.parse_incoming_envelope(payload_text)
    except Exception as e:
        return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process and serialize response
    try:
        out_envelope = current_agent.process_envelope(in_envelope)
        payload_str = envelope_handler.serialize_envelope(out_envelope)
    except Exception as exc:
        error_text = f"{exc.__class__.__name__}: {exc}"
        print(f"ERROR server.py: Envelope processing failed: {error_text}", flush=True)
        print(traceback.format_exc(), flush=True)
        return Response(f"Envelope processing error: {error_text}", status=500)

    return Response(payload_str, mimetype="application/json")


@app.route("/health", methods=["GET"])
def health():
    current_agent, init_error = _get_agent()
    if init_error:
        return jsonify({"status": "unhealthy", "error": init_error}), 500

    return jsonify({
        "status": "healthy",
        "agent": getattr(current_agent._manifest.identification, "conversationalName", "stella"),
        "serviceUrl": getattr(current_agent._manifest.identification, "serviceUrl", ""),
    })


# Vercel WSGI handler - this is the correct way to expose Flask for Vercel
app = app

# -----------------------
# Local test entrypoint
# -----------------------
if __name__ == "__main__":
    print("Starting local Flask server on http://localhost:8767")
    app.run(host="localhost", port=8767, debug=True)
