#!/usr/bin/env python3
"""
Stella Flask server entry point.

This wrapper keeps backwards compatibility with deployments that invoke
server.py directly while delegating the implementation to flask_server.py.
"""

import os

from flask_server import app, manifest


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8767))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    print("=" * 60, flush=True)
    print(f"Stella server starting on http://{host}:{port}", flush=True)
    print(f"Agent: {manifest.identification.conversationalName}", flush=True)
    print(f"Service URL: {manifest.identification.serviceUrl}", flush=True)
    print("=" * 60, flush=True)

    app.run(host=host, port=port, debug=debug, use_reloader=False)
