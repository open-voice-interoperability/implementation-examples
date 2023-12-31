from flask import Flask
from flask import request
from flask_cors import CORS
import json
from secondaryAssistant import *

app = Flask(__name__)
CORS(app)

secondaryAssistant = SecondaryAssistant()
@app.route('/', methods=['POST'])

def home():
    data = json.loads(request.data)
    print(data)
    response_data = secondaryAssistant.invoke_assistant(data)
    return response_data

if __name__ == '__main__':
    app.run(host="0.0.0.0",port=8766, debug=True)

