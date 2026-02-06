#!/usr/bin/env python3
"""
Flask HTTP Server for OpenFloor Agent

Provides HTTP endpoint for OpenFloor envelope processing.
Uses envelope_handler for all JSON parsing and serialization.

Usage:
    python flask_server.py

The server will start on http://localhost:8080 by default.
Configure host and port via environment variables:
    HOST=0.0.0.0 PORT=5000 python flask_server.py
"""

import os
import sys
import logging
from flask import Flask, request, Response, jsonify

# Import our agent components
from template_agent import TemplateAgent, load_manifest_from_config
import envelope_handler


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Initialize Flask app
app = Flask(__name__)


# Initialize agent at module level (loaded once at startup)
try:
    logger.info("Loading agent configuration...")
    manifest = load_manifest_from_config()
    agent = TemplateAgent(manifest)
    logger.info(f"Agent initialized: {manifest.identification.conversationalName}")
    logger.info(f"Service URL: {manifest.identification.serviceUrl}")
except Exception as e:
    logger.error(f"Failed to initialize agent: {e}")
    sys.exit(1)


@app.route('/', methods=['POST'])
def handle_envelope():
    """
    Main endpoint for OpenFloor envelope processing.
    
    Accepts POST requests with JSON OpenFloor envelopes.
    Returns OpenFloor envelope responses.
    """
    try:
        # Get JSON payload from request
        json_payload = request.get_data(as_text=True)
        
        if not json_payload:
            logger.warning("Received empty request body")
            return Response(
                '{"error": "Empty request body"}',
                status=400,
                mimetype='application/json'
            )
        
        # Log incoming request (abbreviated for security)
        logger.info(f"Received envelope: {json_payload[:100]}...")
        
        # Extract conversation ID for logging
        try:
            in_envelope = envelope_handler.parse_incoming_envelope(json_payload)
            conv_id = envelope_handler.extract_conversation_id(in_envelope)
            sender = envelope_handler.extract_sender_name(in_envelope)
            logger.info(f"Processing conversation {conv_id} from {sender}")
            
            # Process envelope
            out_envelope = agent.process_envelope(in_envelope)
            
            # Serialize response
            response_json = envelope_handler.serialize_envelope(out_envelope)
            
            logger.info(f"Returning response for conversation {conv_id}")
            
            return Response(
                response_json,
                status=200,
                mimetype='application/json'
            )
            
        except ValueError as e:
            # Parsing error
            logger.error(f"Invalid envelope format: {e}")
            return Response(
                f'{{"error": "Invalid envelope format: {str(e)}"}}',
                status=400,
                mimetype='application/json'
            )
        
    except Exception as e:
        # Unexpected error
        logger.exception(f"Error processing envelope: {e}")
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"Full traceback: {error_detail}")
        return Response(
            f'{{"error": "Internal server error", "detail": "{str(e)}"}}',
            status=500,
            mimetype='application/json'
        )


@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns agent status and basic information.
    """
    return jsonify({
        'status': 'healthy',
        'agent': manifest.identification.conversationalName,
        'serviceUrl': manifest.identification.serviceUrl,
        'version': '1.0.0',
        'openfloor_schema': '1.1'
    })


@app.route('/manifest', methods=['POST'])
def get_manifest():
    """
    Return agent manifest.
    
    Responds to POST requests (OpenFloor getManifests event pattern).
    """
    try:
        manifest_dict = {
            'identification': {
                'conversationalName': manifest.identification.conversationalName,
                'speakerUri': manifest.identification.speakerUri,
                'serviceUrl': manifest.identification.serviceUrl,
                'organization': manifest.identification.organization,
                'role': manifest.identification.role,
                'synopsis': manifest.identification.synopsis
            },
            'capabilities': {
                'keyphrases': manifest.capabilities.keyphrases,
                'languages': manifest.capabilities.languages,
                'descriptions': manifest.capabilities.descriptions,
                'supportedLayers': manifest.capabilities.supportedLayers
            }
        }
        return jsonify(manifest_dict)
    except Exception as e:
        logger.exception(f"Error returning manifest: {e}")
        return Response(
            f'{{"error": "Failed to retrieve manifest"}}',
            status=500,
            mimetype='application/json'
        )


# Entry point
if __name__ == '__main__':
    # Get configuration from environment
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    logger.info("=" * 60)
    logger.info("OpenFloor Agent Server")
    logger.info("=" * 60)
    logger.info(f"Agent: {manifest.identification.conversationalName}")
    logger.info(f"Service URL: {manifest.identification.serviceUrl}")
    logger.info(f"Speaker URI: {manifest.identification.speakerUri}")
    logger.info(f"Server starting on http://{host}:{port}")
    logger.info("=" * 60)
    logger.info("Endpoints:")
    logger.info(f"  POST /        - OpenFloor envelope processing")
    logger.info(f"  GET  /health  - Health check")
    logger.info(f"  GET  /manifest - Agent manifest")
    logger.info("=" * 60)
    
    # Start Flask server
    app.run(
        host=host,
        port=port,
        debug=debug
    )
