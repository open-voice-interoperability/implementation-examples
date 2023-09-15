from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from secondaryAssistant import *
secondaryAssistant = SecondaryAssistant()
serverPort = 8766

# HTTPRequestHandler class
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    # POST request handler
    def do_POST(self):
        # Set response status code
        self.send_response(200)

        # Set response headers
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Read the request body
        print("reading the request body")
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        # Process the received data
        try:
            # Assuming the received data is JSON
            data = json.loads(post_data)
            # Access and print the received JSON data
            print("Received data:", data)
            # Prepare the response data
            # response_data = {'message': 'POST request received successfully'}
           
            response_data = secondaryAssistant.invoke_assistant(data)
            print("response data is")
            print(response_data)
            # Send the response back to the client
            response_bytes = json.dumps(response_data).encode('utf-8')
            self.wfile.write(response_bytes)
        except json.JSONDecodeError:
            # If the received data is not valid JSON
            response_data = {'error': 'Invalid JSON data'}
            response_bytes = json.dumps(response_data).encode('utf-8')
            self.wfile.write(response_bytes)
        return
    def do_OPTIONS(self):
        print("handling options ")
        print(self.request)
    # Set response status code
        self.send_response(200)
      # Set response headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            response_data = {"test":"got options"}
            print("response data is")
            print(response_data)
            # Send the response back to the client
            response_bytes = json.dumps(response_data).encode('utf-8')
            self.wfile.write(response_bytes)
        except json.JSONDecodeError:
            # If the received data is not valid JSON
            response_data = {'error': 'Invalid JSON data'}
            response_bytes = json.dumps(response_data).encode('utf-8')
            self.wfile.write(response_bytes)
        return

        


# Define the server address and port
server_address = ('', serverPort)

# Create an HTTP server instance
httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)

# Start the server
print("HTTP Server started on port " + str(serverPort))
httpd.serve_forever()

def respond_to_query():
    return