var socket;
var mediaRecorder;


function startScript(){
// Creating a WebSocket connection
console.log("opening a socket")
socket = new WebSocket('ws://localhost:8765');
   console.log('WebSocket connection opened');
// Handle WebSocket connection open event
socket.binaryType = 'blob';
socket.onopen = event => {
    console.log("[open] websocket connection established");
    navigator.mediaDevices
        .getUserMedia({ audio: true, video: false })
        .then(stream => {
            mediaRecorder = new MediaRecorder(stream, {
                mimeType: 'audio/webm;codecs=pcm',
            });
            mediaRecorder.addEventListener('dataavailable', event => {
                if (event.data.size > 0) {
					console.log("sending data")
                    socket.send(event.data);
                }
            });
            mediaRecorder.start(1000);
        });
};

// Handle WebSocket errors
socket.onerror = error => {
  console.error('WebSocket error:', error);
};

// the message can contain either a dialog event, the text transcription or an audio Blob
socket.onmessage = function(event) {
  if (typeof event.data === 'string') {
    // Handle text data
    var receivedText = event.data;
    console.log("Received text:", receivedText);
	//console.log(event.data);
    messageType = decideMessageType(event.data);
    processedMessage = processMessage(messageType,event.data);
    messageWindow = getWindow(messageType);
    appendText(messageWindow,processedMessage);
    
    // Use the received text as needed
  } else if (event.data instanceof Blob) {
    // play the received data
    // Create an audio element
       const audio = new Audio();
  
  // Set the received audio data as the audio source
       audio.src = URL.createObjectURL(event.data);
  
  // Play the audio
  audio.play();
  } else {
    // Handle other types of data (if applicable)
    console.log("Received data of unknown type");
  }
};
// Handle WebSocket connection close event
socket.onclose = () => {
  console.log('WebSocket connection closed');
}

}


function stopRecording(){
	console.log("finished recording");
	mediaRecorder.stop();
	socket.send("end_stream");
}

function closeSocket(){
    socket.close();
}

// clean up message for display
function processMessage(messageType,message){
    var formattedMessage = message;
    if(messageType == "dialogEventUser"){
        messageToFormat = message.replace("dialog event (from user input): ","");
         messageToFormat = messageToFormat.replace(/'/g, '"');
        var parseJSON = JSON.parse(messageToFormat);
        var formattedMessage = JSON.stringify(parseJSON, undefined, 4);  
    }
    else if(messageType == "dialogEventSystem"){
        messageToFormat = message.replace("dialog event (from system output): ","");
        messageToFormat = messageToFormat.replace(/'/g, '"');
        var parseJSON = JSON.parse(messageToFormat);
        var formattedMessage = JSON.stringify(parseJSON, undefined, 4);  
    }
    // no formatting required for conversationTurn
    console.log(formattedMessage);
    return formattedMessage;
}

//decide where to display the text result vs the dialog event
function getWindow(messageType){
    console.log("messageType is " + messageType);
    displayWindowName = ""
    if(messageType == "dialogEventUser"){
        displayWindowName = "toMessages";
    }
    else if(messageType == "dialogEventSystem"){
        displayWindowName = "fromMessages";
    }
    else{
        displayWindowName = "conversationBox";
    }
    console.log("displayWindow is " + displayWindowName);
    return displayWindowName;
}      
