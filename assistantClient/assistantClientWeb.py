# assistantClientWeb.py
from flask import Flask, render_template_string, request, jsonify, send_from_directory
import requests
import socket
from datetime import date
import os

app = Flask(__name__)

# Ensure static folder exists
STATIC_FOLDER = os.path.join(os.path.dirname(__file__), 'static')
if not os.path.isdir(STATIC_FOLDER):
    os.makedirs(STATIC_FOLDER, exist_ok=True)

# ─── CONFIGURATION ───────────────────────────────────────────────────────────
authority = socket.getfqdn()
ip_address = socket.gethostbyname('localhost')  # avoids hostname resolution issues
client_url = f"http://{ip_address}"

def get_current_date_tag_format():
    return date.today().isoformat()

def get_tag_uri():
    today_str = get_current_date_tag_format()
    return f"tag:{authority},{today_str}:AssistantClientWeb"

# Serve static files (logo, fractal background)
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(STATIC_FOLDER, filename)

# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────
PAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Open-Floor Hallucination Factual Check</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      background: url('/static/fractal.png') no-repeat center center fixed;
      background-size: cover;
      font-family: Arial, sans-serif;
      color: #333;
    }
    .container {
      background: rgba(255, 255, 255, 0.85);
      max-width: 700px;
      margin: 32px auto;
      padding: 24px;
      border-radius: 8px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    label { display: block; margin-top: 16px; }
    input, button {
      width: 100%;
      padding: 8px;
      font-size: 1rem;
      margin-top: 6px;
      box-sizing: border-box;
    }
    button {
      margin-top: 20px;
      background-color: #007bff;
      color: white;
      border: none;
      cursor: pointer;
      border-radius: 4px;
    }
    button:disabled {
      background-color: #999;
      cursor: default;
    }
    #response-json {
      margin-top: 30px;
      white-space: pre-wrap;
      background: #f8f8f8;
      border: 1px solid #ccc;
      padding: 12px;
      font-family: Consolas, monospace;
      max-height: 400px;
      overflow-y: auto;
      border-radius: 4px;
    }
    #status-message {
      margin-top: 16px;
      font-style: italic;
      color: gray;
    }
    #logo {
      float: right;
      width: 200px;
      margin-top: -16px;
      margin-right: -16px;
    }
    /* Header styling: 150% size, Open-Floor in blue */
    h1 {
      font-size: 1.5em;
      margin-bottom: 16px;
    }
    h1 .open-floor {
      color: blue;
    }
  </style>
</head>
<body>
  <div class="container">
    <img id="logo" src="/static/voiceinteroperability_logo.png" alt="Open Voice Interoperability" />

    <h1><span class="open-floor">Open-Floor</span> Hallucination Factual Check</h1>

    <label for="utterance">Enter Text:</label>
    <input type="text" id="utterance" placeholder="Type your utterance here…" />

    <label for="assistant-url">Assistant URL:</label>
    <input type="text" id="assistant-url" placeholder="http://secondAssistant.pythonanywhere.com/verity" value="http://secondAssistant.pythonanywhere.com/verity" />

    <button id="send-btn">Send Utterance</button>

    <div id="status-message"></div>

    <div id="response-json">
      <!-- JSON response will appear here -->
    </div>
  </div>

  <script>
    function highlightValues(jsonString) {
      const escaped = jsonString
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      return escaped.replace(/("value"\s*:\s*")([^\"]*)(\")/g,
        '$1<span style="color:green; font-weight:bold;">$2</span>$3');
    }

    const utteranceInput = document.getElementById('utterance');
    const sendBtn = document.getElementById('send-btn');
    const statusDiv = document.getElementById('status-message');
    const responseDiv = document.getElementById('response-json');

    async function sendUtterance() {
      const textInput = utteranceInput.value.trim();
      const assistantUrl = document.getElementById('assistant-url').value.trim();
      statusDiv.textContent = '';
      responseDiv.innerHTML = '';
      if (!assistantUrl) { alert('Please enter a valid Assistant URL.'); return; }
      if (!textInput) { alert('Please type something in the text field.'); return; }
      statusDiv.textContent = '⏳ Please wait…';
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending…';
      const timestamp = new Date().toISOString();
      const convo_id = 'convoID_' + timestamp;
      const envelope = {
        openFloor: {
          conversation: { id: convo_id, startTime: timestamp },
          schema: {
            version: '1.0.0',
            url: 'https://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.0.0/conversation-envelope-schema.json'
          },
          sender: { speakerUri: {{ tag_uri|tojson }}, serviceUrl: {{ client_url|tojson }} },
          events: [{
            to: { serviceUrl: assistantUrl, private: false },
            eventType: 'utterance',
            parameters: { dialogEvent: { speakerUri: {{ tag_uri|tojson }}, features: { text: { mimeType: 'text/plain', tokens: [{ value: textInput }] } } } }
          }]
        }
      };
      try {
        const resp = await fetch('/send_event', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ assistant_url: assistantUrl, envelope })
        });
        if (!resp.ok) throw new Error('Server returned ' + resp.status + ': ' + await resp.text());
        const data = await resp.json();
        responseDiv.innerHTML = highlightValues(JSON.stringify(data, null, 2));
        statusDiv.textContent = '✅ Response received.';
      } catch (err) {
        alert('Error sending request: ' + err.message);
        statusDiv.textContent = '❌ Error occurred.';
      } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send Utterance';
        setTimeout(() => { statusDiv.textContent = ''; }, 5000);
      }
    }

    sendBtn.addEventListener('click', sendUtterance);
    utteranceInput.addEventListener('keydown', event => { if (event.key === 'Enter') sendUtterance(); });
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(PAGE_HTML, client_url=client_url, tag_uri=get_tag_uri())

@app.route("/send_event", methods=["POST"])
def send_event():
    body = request.get_json()
    assistant_url = body.get("assistant_url")
    envelope = body.get("envelope")

    if not assistant_url or not envelope:
        return jsonify({"error": "assistant_url and envelope are required"}), 400

    try:
        r = requests.post(assistant_url, json=envelope, timeout=8)
        r.raise_for_status()
        return jsonify(r.json())
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

if __name__ == "__main__":
    app.run(port=5555)
