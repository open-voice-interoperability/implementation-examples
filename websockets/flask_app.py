
# A very simple Flask Hello World app for you to get started with...
import sys
sys.path.append('/home/secondAssistant/implementation-examples/websockets/')
from flask_cors import CORS

from secondaryAssistant import app as application

from flask import Flask
from flask import request
import json
from secondaryAssistant import *

app = Flask(__name__)
CORS(app)

@app.route('/',methods=['POST'])
@cross_origin()
def runAssistant():
    secondaryAssistant = SecondaryAssistant()
    return secondaryAssistant.invoke_assistant(request.json)

if __name__ == '__main__':
    app.run()

