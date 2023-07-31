# Step 7: Modify the Airline System Bot to Expose the OVON Interface

The Airline System is deployed to AWS as a Serverless Application. These are found in the AWS Lambda console, under the Applications tab, instead of the Functions tab. The Airline System is deployed as a Serverless Application because it is composed of multiple Lambda functions, and the Serverless Application construct allows you to deploy multiple Lambda functions as a single unit. The functions themselves are listed in the Resources panel, of the Serverless Application named **airlines-stack**, under the Logical ID named LambdaBusinessLogic. This is where we will need to build the OVON interface for the Airlines bot.

First, in Visual Studio Code, you're going to want to use the AWS Explorer to connect to your IAM account. This is done by clicking on the AWS Explorer icon in the left-hand menu, and then right-clicking on the Connection to select Add New Connection. You will need to provide the Access Key ID and Secret Access Key for your IAM account. Once you have done this, you should be able to see your AWS account in the AWS Explorer, and you should be able to expand the Lambda node to see the airlines-stack Lambda functions. You can then right click on the **AirlinesBusinessLogic** function and choose Download. You will find the files from the Lambda function in the [AirlinesBusinessLogic](./source/python/airlineBot/AirlinesBusinessLogic/) folder in the source folder.

Next, we need to create an OVON folder and add the OVON [dialogevent.py](https://github.com/open-voice-network/lib-interop/blob/main/python/lib/dialog_event.py) file from the OVON Github Repo names lib-interop.


