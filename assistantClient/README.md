# Assistant Client #

AssistantClient is a simple Python desktop client for testing Open Voice assistants. In addition to supporting text traffic between the client and an assistant server (like the assistants in [https://github.com/open-voice-interoperability/assistants]), it can also display HTML in a separate window if HTML is sent by the server.
The Stella assistant at https://stella-alpha.vercel.app is an example of an assistant that returns HTML.

There are several Python libraries to support the user interface that might need to be installed if they haven't already been installed:

1. customtkinter
2. tkinter
3. tkhtmlview
4. CTkMessagebox

Run the client at the command line with "python assistantClient.py".

# AssistantClientSpeech #
AssistantClientSpeech is mostly the same as AssistantClient, except that it supports speech input and output.
In addition to the libraries above, it needs: 
1. for TTS: pyttsx3
2. for ASR: SpeechRecognition

Note that it doesn't support text input or output, just speech.
Run the client at the command line with "python assistantClientSpeech.py".
