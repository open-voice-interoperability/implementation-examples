# AWS Bot-to-bot interoperability end-to-end Sample
This sample builds a website and two bots in the Amazon AWS. The site is a simple To Do List app. The first Bot is for booking appointments and knows about the website's RESTful API so it can add the appointment as a To Do Item in the List. This Bot does not know how to book flight as a type of appointment. The second Bot knows a lot about Airline services, including Booking a Flight. 

Using the Open Voice Network's Interoperability Specification, when a user asks the first bot to book a flight, rather than failing, it hands off the task to the second bot. The second bot books the flight, returning the booking information to the first bot so that it can create an appointment for the flight itinerary and create the related To Do Item.

The main purpose of this sample is to showcase the interoperability between the two bots. The website and each bot's web UIs are there to provide visibility into this otherwise backend process. By following the step-by-step instructions, you will be able to recreate the related AWS objects and see this sample working in your own AWS environment. 

NOTE: It is possible that the AWS components used in this sample will change over time, but the principles showcased should hold true. Please let us know if there are any difficulties or problems executing the scripts and instructions.

## What we will be Creating
Using this sample, you will deploy myriad AWS objects that set up:
 1. An Amazon CodeCatalyst Project that builds:
- A single-page ToDo App Website hosted in S3 and CloudFront.
- A RESTful API backend using:
  - An AWS API Gateway to provide the REST interface
  - An Amazon DynamoDB for item persistence
  - A set of AWS Lambda functions that provide the glue between the two
 3. An Amazon Lex Bot that can be used to create appointments (that will be shown in the ToDo App as ToDo Items).
 4. A second Amazon Lex Bot that can be used to Book A Flight.
 5. A Lambda function that implements the Open Voice Network's Bot Interoperability Standard to provide an interface between the Appointment Bot and the Book a Flight Bot so that the former can use the latter to create a Flight Appointment, which will appear as a ToDo Item in the website.

## Sample Project and CloudFormation Templates
Some of this sample is provided by creating a new Amazon CodeCatalyst Project. 

Some of this sample is created by running CloudFormation Templates that will deploy the objects needed to implement the solution.

The final part of this sample shows how to implement bot-to-bot communication using the Open Voice Network's Bot Interoperability Standard and Python code.

## Step-by-Step Instructions for the AWS Components

- [Step 1: Create the ToDo WebApp as an Amazon CodeCatalyst Project](./Step%201.md)
- [Step 2: Create the Lex Appointment Bot](./Step%202.md)
- [Step 3: Create a Web UI for the Lex Bot](./Step%203.md)
- [Step 4: Wire up the Lex Bot to the ToDo WebApp](./Step%204.md)
