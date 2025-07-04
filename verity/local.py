# The latest working min Server code 20231105
# =================================================
# Note!!!! you will need to install flask_cors
#    open a bash console and do this
#    pip3.10 install --user flask_cors

from flask import Flask
from flask import request
from flask_cors import CORS
import json
import assistant
import datetime


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
port = 8767

@app.route('/verity/', methods=['POST'])
def home():
    print("=== /verity/ called ===")
    print("Time:", datetime.datetime.now())
    print("Request from:", request.remote_addr)
    inputOPENFLOOR = json.loads( request.data )

    host = request.host.split(":")[0]
    #sender_from = f"http://{host}"
    sender_from = request.url 
    print("Calling generate_response")
    openfloor_response = assistant.generate_response(inputOPENFLOOR, sender_from)

    return openfloor_response

if __name__ == '__main__':
    app.run(host="localhost",port=port, debug=True, use_reloader=False)