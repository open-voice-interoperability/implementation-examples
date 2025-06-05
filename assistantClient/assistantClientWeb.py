# web_client.py
from flask import Flask, render_template_string, request, jsonify
import requests
import socket
import json
from datetime import datetime, date

app = Flask(__name__)

#
# ─── CONFIGURATION ───────────────────────────────────────────────────────────
#
# (1) Build your “speakerUri” tag and your local client_url, exactly as in assistantClient.py
#
authority = socket.getfqdn()
hostname = socket.gethostname()
ip_address = socket.gethostbyname(hostname)
client_url = f"http://{ip_address}"

def get_current_date_tag_format():
    return date.today().isoformat()

def get_tag_uri():
    today_str = get_current_date_tag_format()
    return f"tag:{authority},{today_str}:AssistantClientWeb"

#
# ─── HTML TEMPLATE ────────────────────────────────────────────────────────────
#
# We embed a tiny bit of JavaScript so that clicking “Send Utterance” will:
#   1) grab the two inputs (text + assistant-URL)
#   2) call our Flask endpoint /send_event via fetch()
#   3) dump the JSON response onto the page
#
PAGE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Open Floor Web Client</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      margin: 32px;
      max-width: 700px;
    }
    label { display: block; margin-top: 16px; }
    input, select, button, textarea {
      width: 100%;
      padding: 8px;
      font-size: 1rem;
      margin-top: 6px;
      box-sizing: border-box;
    }
    button { margin-top: 20px; }
    #response-json {
      margin-top: 30px;
      white-space: pre-wrap;
      background: #f8f8f8;
      border: 1px solid #ccc;
      padding: 12px;
      font-family: Consolas, monospace;
      max-height: 400px;
      overflow-y: auto;
    }
  </style>
</head>
<body>
  <h1>Open Floor Web Client</h1>

  <label for="utterance">Enter Text:</label>
  <input type="text" id="utterance" placeholder="Type your utterance here…" />

  <label for="assistant-url">Assistant URL:</label>
  <input type="text" id="assistant-url" placeholder="http://localhost:5000/openfloor" />

  <button id="send-btn">Send Utterance</button>

  <div id="response-json">
    <!-- JSON response will appear here -->
  </div>

  <script>
    document.getElementById('send-btn').addEventListener('click', async () => {
      const textInput = document.getElementById('utterance').value.trim();
      const assistantUrl = document.getElementById('assistant-url').value.trim();

      if (!assistantUrl) {
        alert("Please enter a valid Assistant URL.");
        return;
      }
      if (!textInput) {
        alert("Please type something in the text field.");
        return;
      }

      // Build the envelope exactly as your desktop client would:
      const timestamp = new Date().toISOString();
      const convo_id = "convoID_" + timestamp;

      const envelope = {
        openFloor: {
          conversation: {
            id: convo_id,
            startTime: timestamp
          },
          schema: {
            version: "1.0.0",
            url: "https://github.com/open-voice-interoperability/openfloor-docs/blob/main/schemas/conversation-envelope/1.0.0/conversation-envelope-schema.json"
          },
          sender: {
            speakerUri: "{{ tag_uri }}",
            serviceUrl: "{{ client_url }}"
          },
          events: [
            {
              to: {
                serviceUrl: assistantUrl,
                private: false
              },
              eventType: "utterance",
              parameters: {
                dialogEvent: {
                  speakerUri: "{{ tag_uri }}",
                  features: {
                    text: {
                      mimeType: "text/plain",
                      tokens: [ { value: textInput } ]
                    }
                  }
                }
              }
            }
          ]
        }
      };

      try {
        // Call our Flask route (/send_event)
        const resp = await fetch('/send_event', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            assistant_url: assistantUrl,
            envelope: envelope
          })
        });
        if (!resp.ok) {
          const txt = await resp.text();
          throw new Error("Server returned " + resp.status + ": " + txt);
        }
        const data = await resp.json();
        document.getElementById('response-json').textContent =
          JSON.stringify(data, null, 2);
      } catch (err) {
        alert("Error sending request: " + err.message);
      }
    });
  </script>
</body>
</html>
"""

#
# ─── FLASK ROUTES ───────────────────────────────────────────────────────────────
#
@app.route("/")
def index():
    """
    Serves the single‐page HTML. We inject the client_url and tag_uri so that the JS can build
    the proper “openFloor” envelope just as the desktop client did.
    """
    return render_template_string(
        PAGE_HTML,
        client_url=client_url,
        tag_uri=get_tag_uri()
    )


@app.route("/send_event", methods=["POST"])
def send_event():
    """
    Receives a JSON payload of the form:
        {
          "assistant_url": "<the URL the user typed in>",
          "envelope": { ... }   # full openFloor envelope built in JS
        }
    We then forward that envelope to the assistant URL (using Python's requests),
    grab its JSON response, and re‐send it back to the browser.
    """
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
        # Return error as JSON so the page can display it
        return jsonify({"error": str(e)}), 502


#
# ─── LAUNCH FLASK ON PORT 5555 ─────────────────────────────────────────────────
#
if __name__ == "__main__":
    # By default, Flask binds to 127.0.0.1:5000. We override port=5555.
    # You can also add host="0.0.0.0" if you want to allow other machines on your LAN.
    app.run(port=5555)

