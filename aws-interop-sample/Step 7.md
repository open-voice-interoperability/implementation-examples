# Step 7: Modify the Airline System Bot to Expose the OVON Interface

The Airline System is deployed to AWS as a Serverless Application. These are found in the AWS Lambda console, under the Applications tab, instead of the Functions tab. The Airline System is deployed as a Serverless Application because it is composed of multiple Lambda functions, and the Serverless Application construct allows you to deploy multiple Lambda functions as a single unit. The functions themselves are listed in the Resources panel, of the Serverless Application named **airlines-stack**, under the Logical ID named LambdaBusinessLogic. This is where we will need to build the OVON interface for the Airlines bot.





