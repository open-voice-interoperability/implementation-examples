#!/usr/bin/env python3
"""
Flask HTTP server for the Gemini OpenFloor agent.
"""

import os
import sys
import logging
from flask import Flask, request, Response, jsonify

from template_agent import GeminiAgent, load_manifest_from_config
import envelope_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

try:
    logger.info("Loading agent configuration...")
    manifest = load_manifest_from_config()
    agent = GeminiAgent(manifest)
    logger.info("Agent initialized: %s", manifest.identification.conversationalName)
    logger.info("Service URL: %s", manifest.identification.serviceUrl)
except Exception as exc:
    logger.error("Failed to initialize agent: %s", exc)
    sys.exit(1)


@app.route("/", methods=["POST"])
def handle_envelope():
    try:
        json_payload = request.get_data(as_text=True)
        if not json_payload:
            return Response("{\"error\": \"Empty request body\"}", status=400, mimetype="application/json")

        logger.info("Received envelope: %s...", json_payload[:100])

        in_envelope = envelope_handler.parse_incoming_envelope(json_payload)
        conv_id = envelope_handler.extract_conversation_id(in_envelope)
        sender = envelope_handler.extract_sender_name(in_envelope)
        logger.info("Processing conversation %s from %s", conv_id, sender)

        out_envelope = agent.process_envelope(in_envelope)
        response_json = envelope_handler.serialize_envelope(out_envelope)

        return Response(response_json, status=200, mimetype="application/json")

    except ValueError as exc:
        logger.error("Invalid envelope format: %s", exc)
        return Response(
            f"{{\"error\": \"Invalid envelope format: {str(exc)}\"}}",
            status=400,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.exception("Error processing envelope: %s", exc)
        return Response(
            f"{{\"error\": \"Internal server error\", \"detail\": \"{str(exc)}\"}}",
            status=500,
            mimetype="application/json",
        )


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "agent": manifest.identification.conversationalName,
        "serviceUrl": manifest.identification.serviceUrl,
        "version": "1.0.0",
        "openfloor_schema": "1.1",
    })


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8769))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    logger.info("=" * 60)
    logger.info("Gemini OpenFloor Agent Server")
    logger.info("=" * 60)
    logger.info("Agent: %s", manifest.identification.conversationalName)
    logger.info("Service URL: %s", manifest.identification.serviceUrl)
    logger.info("Speaker URI: %s", manifest.identification.speakerUri)
    logger.info("Server starting on http://%s:%s", host, port)
    logger.info("=" * 60)
    logger.info("Endpoints:")
    logger.info("  POST /       - OpenFloor envelope processing")
    logger.info("  GET  /health - Health check")
    logger.info("=" * 60)

    app.run(host=host, port=port, debug=debug)
