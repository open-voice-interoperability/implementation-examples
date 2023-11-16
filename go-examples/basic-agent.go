package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type ovonMess struct {
	Ovon struct {
		Conversation struct {
			ID string `json:"id"`
		} `json:"conversation"`
		Sender struct {
			From string `json:"from"`
		} `json:"sender"`
		ResponseCode int     `json:"responseCode"`
		Events       []Event `json:"events"`
	} `json:"ovon"`
}

type Event struct {
	EventType  string `json:"eventType"`
	Parameters struct {
		DialogEvent struct {
			SpeakerID string `json:"speakerId"`
			Span      struct {
				StartTime string `json:"startTime"`
			} `json:"span"`
			Features struct {
				Text struct {
					MimeType string  `json:"mimeType"`
					Tokens   []Token `json:"tokens"`
				} `json:"text"`
			} `json:"features"`
		} `json:"dialogEvent"`
	} `json:"parameters"`
}

type Token struct {
	Value string `json:"value"`
}

//---------------- end of OVON messages -----------------------

var sendJson string
var recvJson string

func handler(w http.ResponseWriter, r *http.Request) {
	mthd := r.Method
	fmt.Fprintf(w, "basic agent is alive.\nRequest method is: %s", mthd)
}

func respHandler(w http.ResponseWriter, r *http.Request) {
	fmt.Println(time.Now().Local().String() + "------------------------ respHandler ---------------------------------------")
	fmt.Println("--------------------- respHandler Request Headers-----------------------")
	for name, value := range r.Header {
		fmt.Printf("%v: %v\n", name, value)
	}
	fmt.Println("------------------------------------------------------------------------")
	reqBody, err := io.ReadAll(r.Body)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Printf("reqBody: %s\n", reqBody)
	params, _ := url.ParseQuery(string(reqBody))
	agentUrl := params.Get("agenturl") //URL.Query().Get("agenturl")
	question := params.Get("question") //URL.Query().Get("question")
	dispjson := params.Get("dispjson") //URL.Query().Get("dispjson")
	agentResp := ""
	sendJson = ""
	recvJson = ""
	fmt.Println("---------------------------------------------")
	fmt.Println("agentUrl = " + agentUrl)
	fmt.Println("dispjson = " + dispjson)
	fmt.Println("---------------------------------------------")
	if agentUrl != "" {
		agentResp = getAgentResp(agentUrl, question)
	}
	content := "<head>"
	content += "<title>OVON Agent Browser</title>"
	content += "<style type=\"text/css\">"
	content += "  span#art{"
	content += "      vertical-align:middle;"
	content += "      line-height: 60px;"
	content += "      font-size: 30px;"
	content += "      font-weight: bold;"
	content += "      font-family: Ariel,sans-serif,monospace;"
	content += "      color: red;"
	content += "      padding-left: 30px;"
	content += "  }"
	content += "  div#intro {"
	content += "      width:60%;"
	content += "      margin-left:20px;"
	content += "      padding:10px;"
	content += "      font-family: Ariel,sans-serif,monospace;"
	content += "  }"
	content += "  form#reqform {"
	content += "      width:100%;"
	content += "      margin-left:30px;"
	content += "      margin-top:10px;"
	content += "      margin-bottom:10px;"
	content += "  }"
	content += "  div.json {"
	content += "      width:75%;"
	content += "      background-color: #faeecd;"
	content += "      margin-left:20px;"
	content += "      margin-top:10px;"
	content += "      margin-bottom:10px;"
	content += "      padding:10px;"
	content += "  }"
	content += "  div#agentresp {"
	content += "      width:75%;"
	content += "      margin-left:20px;"
	content += "      padding:10px;"
	content += "      font-family: Ariel,sans-serif,monospace;"
	content += "      border-style:solid;"
	content += "      border-width:1px;"
	content += "  }"
	content += "  div#sendjson {"
	content += "  }"
	content += "  div#recvjson {"
	content += "  }"
	content += "</style>"
	content += "</head>"
	content += "<body>"
	content += "<span id='art'>OVON Agent Browser</span>"
	content += "<div id = 'intro'>"
	content += "Enter the URL of an OVON-message compliant agent, "
	content += "then enter the message/question that you would like "
	content += "to send to the agent.<br> The response from the agent will be shown "
	content += "below.<br> Tick the 'Show JSON' box to display the "
	content += "JSON messages sent to, and received from the agent. "
	content += "</div>"
	content += "<form id=\"reqform\" action=\"/getresponse\" method=\"post\" enctype=\"application/x-www-form-urlencoded\" "
	content += " <label for=\"agenturl\">Agent URL:</label><br>"
	content += "  <input type=\"text\" id=\"agenturl\" name=\"agenturl\" value=\""
	content += agentUrl
	content += "\"  size=\"50\"><br>"
	content += "  <label for=\"question\">Enter your question:</label><br>"
	content += "<textarea id=\"question\" name=\"question\" rows=\"4\" cols=\"80\">"
	content += question
	content += "</textarea><br><br>"
	content += "<input type=\"checkbox\" id=\"dispjson\" name=\"dispjson\" value=\"yes\">"
	content += "<label for=\"dispjson\"> Show JSON</label><br><br>"
	content += "  <input type=\"submit\" value=\"Submit your question to the Agent\">"
	content += "</form> "
	content += "<div id='agentresp'>"
	content += agentResp
	content += "</div>"
	if strings.Contains(dispjson, "yes") {
		content += "<div div id='sendjson' class='json'>"
		content += "<u>JSON sent to agent</u><br>"
		content += sendJson
		content += "</div>"
		content += "<div id-'recvjson' class='json'>"
		content += "<u>JSON received from agent</u><br>"
		content += recvJson
		content += "</div>"
	}
	content += "</body>"
	//w.Header().Add("Content-Type", "text/plain")
	fmt.Fprint(w, content)
}

func getAgentResp(agenturl string, question string) string {
	retval := ""
	now := time.Now().Local().String()

	var newtoken Token
	newtoken.Value = question

	var utterevent Event
	utterevent.EventType = "utterance"
	utterevent.Parameters.DialogEvent.SpeakerID = "textBrowser"
	utterevent.Parameters.DialogEvent.Span.StartTime = now
	utterevent.Parameters.DialogEvent.Features.Text.MimeType = "text/plain"
	utterevent.Parameters.DialogEvent.Features.Text.Tokens = append(utterevent.Parameters.DialogEvent.Features.Text.Tokens, newtoken)

	var omess ovonMess
	omess.Ovon.Sender.From = "https://www.someserver.com/getresponse"
	omess.Ovon.ResponseCode = 200
	omess.Ovon.Conversation.ID = "OvonDemo137"
	omess.Ovon.Events = append(omess.Ovon.Events, utterevent)

	jsonBytes, _ := json.Marshal(omess)
	fmt.Println("getAgentResp: " + string(jsonBytes))

	sendJson = string(jsonBytes)

	url := agenturl
	contentType := "application/json"

	client := &http.Client{}
	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonBytes))
	if err != nil {
		fmt.Println(err)
	}
	req.Header.Add("Content-Type", contentType)
	//req.Header.Add("Access-Control-Allow-Origin:", "*")        //use only in response

	resp, err := client.Do(req) //// send the http request
	if err != nil {
		fmt.Println(err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Println(err)
	}

	fmt.Println("\n\n message back: " + string(body))

	test := string(body)
	if strings.Contains(test, "Error") {
		return test
	} else {
		recvJson = string(body)
		var respMess ovonMess
		json.Unmarshal(body, &respMess)
		//retval = respMess.Ovon.Events[0].Parameters.DialogEvent.Features.Text.Tokens[0].Value
		var eventSlice = respMess.Ovon.Events
		numevents := len(eventSlice)
		fmt.Printf("getAgentResp: numevents = %d\n", numevents)
		for i := 0; i < numevents; i++ {
			if eventSlice[i].EventType == "invite" {
				//doInviteResponse(w, conversationId)
				break
			} else if eventSlice[i].EventType == "utterance" {
				tokenslice := eventSlice[i].Parameters.DialogEvent.Features.Text.Tokens
				numtokens := len(tokenslice)
				fmt.Printf("event[%d] has %d tokens \n", i, numtokens)
				if numtokens > 0 {
					retval = tokenslice[0].Value
				}
				break
			}
		}
	}
	return retval

}

func ovonHandler(w http.ResponseWriter, r *http.Request) {
	fmt.Println(time.Now().Local().String() + "------------------------ ovonHandler ---------------------------------------")
	bodyBytes, _ := io.ReadAll(r.Body)
	var method = r.Method
	var origin = ""
	origin = r.Header.Get("Origin")
	var reqMethod = ""
	reqMethod = r.Header.Get("Access-Control-Request-Method")
	fmt.Printf("%v: %v\n", "Method", method)
	fmt.Println("--------------------- ovonHandler Request Headers-----------------------")
	for name, value := range r.Header {
		fmt.Printf("%v: %v\n", name, value)
	}
	fmt.Println("---------------------------------------------------------      ")

	if method == "OPTIONS" && origin != "" && reqMethod != "" { //It's a PREFLIGHT REQUEST
		w.WriteHeader(204)
		w.Header().Add("Access-Control-Allow-Method", r.Header.Get("Access-Control-Request-Method"))
		w.Header().Add("Access-Control-Allow-Headers", r.Header.Get("Access-Control-Request-Headers"))
		fmt.Fprint(w, "preflight") /// only visible if response code is 200
		fmt.Printf("%v\n", "Request is a PREFLIGHT")
		fmt.Println("--------------------- ovonHandler Response Headers-----------------------")
		for name, value := range w.Header() {
			fmt.Printf("%v: %v\n", name, value)
		}
		fmt.Println("-------------------------------------------------------------------------")
	} else { // It's a DATA REQUEST
		bodyString := string(bodyBytes)
		fmt.Printf("\nbodystring: %v\n", bodyString)
		var mess string
		// Convert response body to Todo struct
		var inmess ovonMess
		json.Unmarshal(bodyBytes, &inmess)
		fmt.Printf("\ninmess\n%+v\n", inmess)
		var conversationId = inmess.Ovon.Conversation.ID
		var eventSlice = inmess.Ovon.Events
		numevents := len(eventSlice)
		fmt.Printf("numevents = %d\n", numevents)
		for i := 0; i < numevents; i++ {
			if eventSlice[i].EventType == "invite" {
				doInviteResponse(w, conversationId)
				break
			} else if eventSlice[i].EventType == "utterance" {
				tokenslice := eventSlice[i].Parameters.DialogEvent.Features.Text.Tokens
				numtokens := len(tokenslice)
				fmt.Printf("event[%d] has %d tokens \n", i, numtokens)
				if numtokens > 0 {
					mess = tokenslice[0].Value
				}
				doResponse(w, mess, conversationId)
				break
			}
		}
	}
}

func doInviteResponse(w http.ResponseWriter, conversationId string) {
	now := time.Now().Local().String()

	var intoken Token
	intoken.Value = "Ready"

	var utterevent Event
	utterevent.EventType = "utterance"
	utterevent.Parameters.DialogEvent.SpeakerID = "basic-agent"
	utterevent.Parameters.DialogEvent.Span.StartTime = now
	utterevent.Parameters.DialogEvent.Features.Text.MimeType = "text/plain"
	utterevent.Parameters.DialogEvent.Features.Text.Tokens = append(utterevent.Parameters.DialogEvent.Features.Text.Tokens, intoken)

	var omess ovonMess
	omess.Ovon.Sender.From = "https://www.someserver.com/ovontest"
	omess.Ovon.ResponseCode = 200
	omess.Ovon.Conversation.ID = conversationId
	omess.Ovon.Events = append(omess.Ovon.Events, utterevent)

	fmt.Printf("\n%+v\n", omess)
	outBytes, _ := json.Marshal(omess)
	w.Header().Add("Access-Control-Allow-Origin", "*") /// needed by CORS Request
	fmt.Printf("\n%+v\n", string(outBytes))
	fmt.Fprint(w, string(outBytes))

}

func doResponse(w http.ResponseWriter, mess string, conversationId string) {
	now := time.Now().Local().String()

	var intoken Token
	intoken.Value = getAgentResponse(mess) /////////  call another agent or API

	var utterevent Event
	utterevent.EventType = "utterance"
	utterevent.Parameters.DialogEvent.SpeakerID = "basic-agent"
	utterevent.Parameters.DialogEvent.Span.StartTime = now
	utterevent.Parameters.DialogEvent.Features.Text.MimeType = "text/plain"
	utterevent.Parameters.DialogEvent.Features.Text.Tokens = append(utterevent.Parameters.DialogEvent.Features.Text.Tokens, intoken)

	var omess ovonMess
	omess.Ovon.Sender.From = "https://www.someserver.com/ovontest"

	omess.Ovon.ResponseCode = 200
	omess.Ovon.Conversation.ID = conversationId
	omess.Ovon.Events = append(omess.Ovon.Events, utterevent)

	fmt.Printf("\n%+v\n", omess)
	outBytes, _ := json.Marshal(omess)
	w.Header().Add("Access-Control-Allow-Origin", "*") /// needed by CORS Request
	fmt.Println("--------------------- ovonHandler Response Headers-----------------------")
	for name, value := range w.Header() {
		fmt.Printf("%v: %v\n", name, value)
	}
	fmt.Println("-------------------------------------------------------------------------")
	fmt.Printf("\n%+v\n", string(outBytes))
	fmt.Fprint(w, string(outBytes))
}

func getAgentResponse(mess string) string {
	retval := "You said - " + mess
	return retval
}

func main() {
	http.HandleFunc("/ovontest", ovonHandler)
	http.HandleFunc("/getresponse", respHandler)
	http.HandleFunc("/", handler)
	log.Fatal(http.ListenAndServe(":8082", nil))
}
