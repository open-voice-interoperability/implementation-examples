#!/usr/bin/env python3
"""
Flask HTTP Server for Verity (OpenFloor)
"""

import os
import sys
import logging
from flask import Flask, request, Response, jsonify
from flask_cors import CORS

from template_agent import TemplateAgent, load_manifest_from_config
import envelope_handler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

try:
    logger.info("Loading agent configuration...")
    manifest = load_manifest_from_config()
    agent = TemplateAgent(manifest)
    logger.info("Agent initialized: %s", manifest.identification.conversationalName)
    logger.info("Service URL: %s", manifest.identification.serviceUrl)
except Exception as e:
    logger.error("Failed to initialize agent: %s", e)
    sys.exit(1)


def _handle_openfloor_request() -> Response:
    try:
        json_payload = request.get_data(as_text=True)
        if not json_payload:
            logger.warning("Received empty request body")
            return Response(
                '{"error": "Empty request body"}',
                status=400,
                mimetype='application/json'
            )

        logger.info("Received envelope: %s...", json_payload[:100])

        try:
            in_envelope = envelope_handler.parse_incoming_envelope(json_payload)
            conv_id = envelope_handler.extract_conversation_id(in_envelope)
            sender = envelope_handler.extract_sender_name(in_envelope)
            logger.info("Processing conversation %s from %s", conv_id, sender)

            out_envelope = agent.process_envelope(in_envelope)
            response_json = envelope_handler.serialize_envelope(out_envelope)

            logger.info("Returning response for conversation %s", conv_id)

            return Response(
                response_json,
                status=200,
                mimetype='application/json'
            )

        except ValueError as e:
            logger.error("Invalid envelope format: %s", e)
            return Response(
                f'{{"error": "Invalid envelope format: {str(e)}"}}',
                status=400,
                mimetype='application/json'
            )

    except Exception as e:
        logger.exception("Error processing envelope: %s", e)
        return Response(
            f'{{"error": "Internal server error", "detail": "{str(e)}"}}',
            status=500,
            mimetype='application/json'
        )


@app.route('/verity/', methods=['POST'])
def handle_verity_envelope():
    return _handle_openfloor_request()


@app.route('/', methods=['POST'])
def handle_envelope():
    return _handle_openfloor_request()


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'agent': manifest.identification.conversationalName,
        'serviceUrl': manifest.identification.serviceUrl,
        'version': '1.0.0',
        'openfloor_schema': '1.1'
    })


@app.route('/manifest', methods=['POST'])
def get_manifest():
    try:
        manifest_dict = {
            'identification': {
                'conversationalName': manifest.identification.conversationalName,
                'speakerUri': manifest.identification.speakerUri,
                'serviceUrl': manifest.identification.serviceUrl,
                'organization': manifest.identification.organization,
                'role': manifest.identification.role,
                'synopsis': manifest.identification.synopsis,
                'department': manifest.identification.department
            },
            'capabilities': {
                'keyphrases': manifest.capabilities[0].keyphrases,
                'languages': manifest.capabilities[0].languages,
                'descriptions': manifest.capabilities[0].descriptions,
                'supportedLayers': manifest.capabilities[0].supportedLayers
            }
        }
        return jsonify(manifest_dict)
    except Exception as e:
        logger.exception("Error returning manifest: %s", e)
        return Response(
            '{"error": "Failed to retrieve manifest"}',
            status=500,
            mimetype='application/json'
        )


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 8768))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'

    logger.info("=" * 60)
    logger.info("Verity OpenFloor Agent Server")
    logger.info("=" * 60)
    logger.info("Agent: %s", manifest.identification.conversationalName)
    logger.info("Service URL: %s", manifest.identification.serviceUrl)
    logger.info("Speaker URI: %s", manifest.identification.speakerUri)
    logger.info("Server starting on http://%s:%s", host, port)
    logger.info("=" * 60)
    logger.info("Endpoints:")
    logger.info("  POST /verity/ - OpenFloor envelope processing")
    logger.info("  POST /        - OpenFloor envelope processing")
    logger.info("  GET  /health  - Health check")
    logger.info("  POST /manifest - Agent manifest")
    logger.info("=" * 60)

    app.run(
        host=host,
        port=port,
        debug=debug
    )
