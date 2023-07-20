function appendText(messageWindow,newText){
    console.log(messageWindow);
	var textBox = document.getElementById(messageWindow);
    console.log(textBox);
	var currentText = textBox.value;
	textBox.value = currentText+ "\n" + newText;
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