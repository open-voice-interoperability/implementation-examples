import whisper
# see https://github.com/openai/whisper for whisper documentation
from gtts import gTTS

english_recognition_model = "base.en"
multilingual_speech_recognition_model = "base"
#change model to "base" for multilingual recognition
current_speech_recognition_model = "base.en"
tts_voice = "en-us"


class AudioProcessing:
    def __init__(self):
        self.transcription = ""
        self.tts_file_name = "output_audio_file.wav"
        self.current_recognition_language = ""
        self.current_tts_language = ""
        
    # call speech recognizer (in this case Whisper) to transcribe file 
    def transcribe_file(self,file_name):
        print("transcribing file")
        print(file_name)
        print("loading model")
        model = whisper.load_model(current_speech_recognition_model)
        print("loaded model")
        result = model.transcribe(file_name)
        print("transcribed file")
        self.transcription = result["text"]
      
    # call text to speech (in this case gTTS) to create a speech file      
    def text_to_speech(self,text):
        output_audio = gTTS(text)
        output_audio.save(self.tts_file_name)
        
    def detect_language(self,file_name):
        # load audio and pad/trim it to fit 30 seconds
        audio = whisper.load_audio(file_name)
        audio = whisper.pad_or_trim(audio)
        model = whisper.load_model(current_speech_recognition_model)
        # make log-Mel spectrogram and move to the same device as the model
        mel = whisper.log_mel_spectrogram(audio).to(model.device)

        # detect the spoken language
        _, probs = model.detect_language(mel)
        print(f"Detected language: {max(probs, key=probs.get)}")
    

    def get_transcription(self):
        return(self.transcription)
    
    def get_tts_file_name(self):
        return(self.tts_file_name)
        
    def get_current_recognition_language(self):
        return(self.current_recognition_language)
    
    def get_current_tts_language(self):
        return(self.current_tts_language)