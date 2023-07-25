/*****************************************
* this is a simple webserver that will respond to a /ovontest request
* and respond with the Ovon json message that had been received
* setting id, start-time, and message
******************************************/


const http = require('http');

http.createServer((request, response) => {
  const { headers, method, url } = request;
  request.on('error', (err) => {
    console.error(err);
    response.statusCode = 400;
    response.end();
  });
  response.on('error', (err) => {
    console.error(err);
  });
  console.log(request.url+" method = "+request.method);
  if (request.method === 'POST' && request.url === '/ovontest') {
    let body = "";
    request.on('data', (chunk) => {
    //    console.log(chunk.toString());
        body += chunk.toString();
    }).on('end', () => {
        console.log ("At END: " + body);
//    })
    console.log("Scope check - body length = "+body.length)
    var json = JSON.parse(body);
    var now = new Date();
    json.id = "openAI-get-response";
    json["speaker-id"] = "AIBot";
    json['span']['start-time'] = now.getFullYear()+"- "+now.getMonth()+"-"+now.getDate();
    json['features']['bot-request']['tokens'][0].value = "This is the OVON bot. Sorry I can't help you right now. Please try again later."
    //
    var mess = JSON.stringify(json)  
    console.log (new Date()+"  Returning: " + mess);
    response.statusCode = 200;
    response.setHeader('Content-Type', 'application/json');
    // Note: the 2 lines above could be replaced with this next one:
    // response.writeHead(200, {'Content-Type': 'application/json'})

    const responseBody = { headers, method, url, mess };

    response.write(JSON.stringify(responseBody));
    response.end();
    //response.writeHead(200, {'Content-Type': 'application/json'});
    //response.end();
  })

  } else {
    response.statusCode = 404;
    response.end();
  }
}
).listen(8082);

