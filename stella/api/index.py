#!/usr/bin/env python3
"""
Vercel-ready Flask server for StellaAgent.
Supports local testing (flask run) and deployment on Vercel.
"""
from flask import Flask, request, Response
from flask_cors import CORS
import json
import re
import tempfile
import uuid
import os

# Your agent imports
from stella_agent import load_manifest_from_config, StellaAgent
from openfloor.envelope import Envelope

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Load agent once
manifest = load_manifest_from_config()
agent = StellaAgent(manifest)

@app.route("/", methods=["POST"])
def handle_request():
    payload_text = request.get_data(as_text=True)

    # Parse incoming envelope
    try:
        in_envelope = Envelope.from_json(payload_text, as_payload=True)
    except Exception:
        try:
            in_envelope = Envelope.from_json(json.dumps(request.get_json()), as_payload=True)
        except Exception as e:
            return Response(f"Invalid OpenFloor payload: {e}", status=400)

    # Process and serialize response
    out_envelope = agent.process_envelope(in_envelope)
    payload_str = out_envelope.to_json(as_payload=True)

    # Optional: save raw payload for debugging
    try:
        tmp_dir = tempfile.gettempdir()
        dump_name = f"stella_outgoing_raw_{uuid.uuid4().hex}.json"
        dump_path = os.path.join(tmp_dir, dump_name)
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(payload_str)
        print(f"Wrote raw outgoing payload to: {dump_path}")
    except Exception:
        pass

    return Response(payload_str, mimetype="application/json")


# -----------------------
# Local test entrypoint
# -----------------------
if __name__ == "__main__":
    print("Starting local Flask server on http://localhost:8767")
    app.run(host="localhost", port=8767, debug=True)
