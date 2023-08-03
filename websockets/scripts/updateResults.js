function appendText(messageWindow,newText){
    console.log(messageWindow);
	var textBox = document.getElementById(messageWindow);
	var currentText = textBox.value;
	textBox.value = currentText+ "\n" + newText;
    textBox.scrollTop = 0;
}

function decideMessageType(message){
    var messageType;
    if(message.startsWith("dialog event (from user input):")){
        messageType = "dialogEventUser";
    }
    else if(message.startsWith("dialog event (from system output): ")){
        messageType = "dialogEventSystem";
    }
    else{
        messageType = "conversationTurn";
    }
   
    return messageType;
}