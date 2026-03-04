#!/usr/bin/env python3
"""
Vercel entrypoint for TimeAgent.
"""

import os
import sys
from flask import request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask_server import app as app
from flask_server import agent, manifest


@app.before_request
def _update_manifest_service_url() -> None:
    host = request.headers.get("Host")
    if host:
        service_url = f"https://{host}"
        if hasattr(agent, "_manifest"):
            agent._manifest.identification.serviceUrl = service_url
        manifest.identification.serviceUrl = service_url


if __name__ == "__main__":
    app.run(host="localhost", port=8081, debug=True)
