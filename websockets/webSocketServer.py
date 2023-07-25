import asyncio
import websockets
import whisper
from assistant import *
from gtts import gTTS

transcription = "initial transcription"
assistant = Assistant()
serverPort = 8765

async def audio_server(websocket, path):
    try:
        while True:
            audio_data = b''
            
            # Receive data from the client
            while True:
                data = await websocket.recv()
                if data == 'end_stream':
                    break
                audio_data += data
               
            if audio_data:
                # recognize the input audio stream and create transcription
                print("Received audio stream length:", len(audio_data))
                with open('received_audio.wav', 'wb') as audio_file:
                   audio_file.write(audio_data)
                   print("Audio file saved successfully")
                   transcription = transcribe_file("received_audio.wav")
                    # Send the transcription back to display to the user
                   await websocket.send(transcription)
                   print("transcription sent to client")
                   print(transcription)
                   assistant.invoke_assistant(transcription)
                if assistant.transfer:
                # let the user know the request is being transferred
                    assistant_message = assistant.get_primary_assistant_response()
                    print(assistant_message)
                    await websocket.send(assistant_message)
                    # Send primary assistant TTS response audio back to the client
                    primary_assistant_audio = gTTS(assistant_message)
                    primary_assistant_audio.save("primary_assistant_audio.wav")
                    with open("primary_assistant_audio.wav", "rb") as audio_file:
                        await websocket.send(audio_file.read())
                what_to_say = assistant.get_output_transcription()
                output_audio = gTTS(what_to_say)
                output_audio.save("output_audio_file.wav")
                with open("output_audio_file.wav", "rb") as audio_file:
                    await websocket.send(audio_file.read())
				# send text response back to client
                await websocket.send(what_to_say)
                # the client doesn't actually use this message, it only
                # uses the TTS, but we send it here so that it can be
                # displayed to a user (probably a developer)
                # send OVON-formatted input message back to the client for display
                message_to_client = assistant.get_input_message()
                print(message_to_client)
                string_message = str(message_to_client)
                to_send = "dialog event (from user input): " + string_message
				# send input message back to client for user to look at
                await websocket.send(to_send)
                # send OVON-formatted output message back to the client for display
                system_response_message = assistant.get_output_message()
                output_to_send = "dialog event (from system output): " + system_response_message
                await websocket.send(output_to_send)
                                 
    except websockets.exceptions.ConnectionClosed:
        print("WebSocket connection closed")
    except Exception as e:
        print("Error:", e)

    
# call speech recognizer (in this case Whisper) to transcribe file 
def transcribe_file(name):
    print("transcribing file")
    print(name)
    print("loading model")
    model = whisper.load_model("base.en")
    print("loaded model")
    result = model.transcribe(name)
    print("transcribed file")
    transcription = result["text"]
    return(transcription)
  

# Create a WebSocket server
print("starting websocket server on port " + str(serverPort))
start_server = websockets.serve(audio_server, 'localhost', serverPort)
 

# Start the server
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()