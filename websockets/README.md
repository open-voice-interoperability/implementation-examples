# Demonstration of using websockets to do server-side speech recognition and TTS
The client is a web browser and the server is a websocket server.
The ASR and TTS are performed on the websocket server. There is no need for the browser to have any speech capabilities.
ASR is done locally on this server by the OpenAI Whisper speech recognizer.
Currently TTS is done in the cloud.
This could be used for the channeling pattern.

## Server-side code (Python):
1. webSocketServer.py (primary assistant/websocket server)
2. Start the server at the command line with "python webSocketServer.py"
3. The server is set up to run on localhost, port 8765
4. The server waits for audio to be sent over a websocket
5. when it receives the audio, it transcribes it with the open source OpenAI Whisper ASR software, which must be installed on the server, but which doesn't require internet access at runtime.
6. More information about Whisper and instructions for installing can be found at https://github.com/openai/whisper. Note that Whisper can be configured to use many models and supports many languages.
7. After the audio is transcribed, the transcription, TTS wav file and associated dialog event are returned to the client, where they are displayed in a browser window. 
8. Note that the only reason the dialog event is sent to the browser is so a developer can inspect it. The browser doesn't use it.
9. TTS is performed by the gTTS library
10. Tested on Chrome and Edge on Windows

## Client-side code (HTML/Javascript):
### sendAudioToServer.html
1. Click on "start listening" to start streaming audio to the server
2. Give the application permission to use the microphone
3. Speak your request
4. Click "Stop listening" when finished speaking
5. The result will be displayed in the textarea in the browser
6. Plays the audio output from the server

### captureAudio.js
1. sends the audio stream to the server
2. waits for the transcription from the server and updates the results

### updateResults.js
1. updates the conversationBox textarea with the transcription
2. updates the toMessages textarea with the dialog event

## assistant.py
1. start of assistant functions
2. generate dialog events

## secondaryAssistantHTTP.py
1. an HTTP server that accepts OVON messages from a primary assistant and sends them to a secondary assistant

## secondaryAssistant.py
1. processes OVON messages from a primary assistant and returns a response

## todo:
1. write a rudimentary discovery placeholder
1. add ASR confidence to OVON messages
1. provide for text input
1. change languages
1. find local TTS



