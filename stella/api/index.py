# The latest working min Server code 20231105
# =================================================
# Note!!!! you will need to install flask_cors
#    open a bash console and do this
#    pip3.10 install --user flask_cors

from flask import Flask
from flask import request
from flask_cors import CORS
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
import json
import sys
import os

# Get the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Get the parent directory
parent_dir = os.path.dirname(current_dir)

# Add the parent directory to the system path
sys.path.append(parent_dir)

# Now you can import modules from the parent directory 
import assistant

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


@app.route('/', methods=['GET','POST'])
def home():
    inputOVON = json.loads( request.data )
    host = request.host.split(":")[0]
    sender_from = f"http://{host}"
    ovon_response = assistant.generate_response(inputOVON, sender_from)

    # return ovon_response
    return ovon_response

# def handler(environ, start_response):
#     return app(environ, start_response)


