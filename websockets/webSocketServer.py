import asyncio
import websockets
from assistant import *
from audioProcessing import *

transcription = "initial transcription"

audio_processing = AudioProcessing()
serverPort = 8765
server_url = "ws:localhost:8765"
assistant = Assistant(server_url)

async def audio_server(websocket, path):
    try:
        while True:
            audio_data = b''
            
            # Receive data from the client
            while True:
                data = await websocket.recv()
                if isinstance(data, str):
                    if data == 'end_stream':
                        break
                    else:
                        print("Received string data:", data)
                        transcription = data
                        break
                else:
                    audio_data += data
               
            if audio_data:
                # recognize the input audio stream and create transcription using ASR
                print("Received audio stream length:", len(audio_data))
                with open("received_audio.wav", 'wb') as audio_file:
                   audio_file.write(audio_data)
                   print("Audio file saved successfully")
                   audio_processing.transcribe_file("received_audio.wav")
                   transcription = audio_processing.get_transcription()
            # Send the transcription back to display to the user
            await websocket.send(transcription)
            print("transcription sent to client")
            print(transcription)
            # notify the user that the response will take a little time
            delay_message = assistant.warn_delay(transcription)
            await websocket.send(delay_message)
            # Send primary assistant TTS response audio back to the client
            audio_processing.text_to_speech(delay_message)
            print("server url is " + server_url)
            primary_assistant_audio = audio_processing.get_tts_file_name()
            with open(primary_assistant_audio, "rb") as audio_file:
                await websocket.send(audio_file.read())
            print("sent delay warning")
            assistant.invoke_assistant(transcription)
            if assistant.transfer:
                # let the user know the request is being transferred
                assistant_message = assistant.get_primary_assistant_response()
                print(assistant_message)
                await websocket.send(assistant_message)
                # Send primary assistant TTS response audio back to the client
                audio_processing.text_to_speech(assistant_message)
                primary_assistant_audio = audio_processing.get_tts_file_name()
                with open(primary_assistant_audio, "rb") as audio_file:
                    await websocket.send(audio_file.read())
            what_to_say = assistant.get_output_transcription()
            audio_processing.text_to_speech(what_to_say)
            output_audio_file = audio_processing.get_tts_file_name()
            with open(output_audio_file, "rb") as audio_file:
                await websocket.send(audio_file.read())
            # send text response back to client
            await websocket.send(what_to_say)
            # the client doesn't actually use the OVON message, it only
            # uses the TTS, but we send it here so that it can be
            # displayed to a user (probably a developer)
            # send OVON-formatted input message back to the client for display
            message_to_client = assistant.get_input_message()
            string_message = str(message_to_client)
            to_send = "dialog event (from user input): " + string_message
            # send input message back to client for user to look at
            await websocket.send(to_send)
            # send OVON-formatted output message back to the client for display
            system_response_message = assistant.get_output_message()
            output_to_send = "dialog event (from system output): " + str(system_response_message)
            await websocket.send(output_to_send)
                                 
    except websockets.exceptions.ConnectionClosed:
        print("WebSocket connection closed")
    except Exception as e:
        print("Error:", e)
  

# Create a WebSocket server
print("starting websocket server on port " + str(serverPort))
start_server = websockets.serve(audio_server, 'localhost', serverPort)
 

# Start the server
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()