const http = require('http');

var avonMess = {
    "id": "123",
    "speaker-id": "me",
    "span": {
    "start-time": "2022-12-20 15:59:01.246500+00:00",
    "end-offset": "PT3.1045"
    },
    "features": {
        "bot-request": {
            "mime-type": "text/plain",
            "encoding": "UTF-8",
            "tokens": [
                {"value": "this is a question"}
                ]
        }
    }
}


let data = JSON.stringify(avonMess); 
       
//send a POST request to localhost:8082 containing the Ovon json message

let req = http.request({
  hostname: 'localhost',                                
  port: '8082',
  path: '/ovontest',
  method: 'POST',
  headers: {
    'Content-Length': data.length,
    'Content-type': 'application/json'
  }
}, (resp) => {
  let data = '';
  resp.on('data', (chunk) => { data += chunk; });
  resp.on('end', () => {console.log(new Date()+"   "+data);})                        // display the response received back from the web server
  resp.on('error', ()=> {console.log("error caught")}); });

//console.count(data);
//req.write(data);
req.end(data);

