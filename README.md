# implementation-examples
repository for examples of implementations of OVON interoperability specifications

## Site Contents
AWS Bot-to-bot interoperability end-to-end Sample

### AWS Bot-to-bot interoperability end-to-end Sample
This sample builds a website and two bots in the Amazon AWS. The site is a simple To Do List app. The first Bot is for booking appointments and knows about the website's RESTful API so it can add the appointment as a To Do Item in the List. This Bot does not know how to book flight as a type of appointment. The second Bot knows a lot about Airline services, including Booking a Flight. 

Using the Open Voice Network's Interoperability Specification, when a user asks the first bot to book a flight, rather than failing, it hands off the task to the second bot. The second bot books the flight, returning the booking information to the first bot so that it can create an appointment for the flight itinerary and create the related To Do Item.

The main purpose of this sample is to showcase the interoperability between the two bots. The website and each bot's web UIs are there to provide visibility into this otherwise backend process. By following the step-by-step instructions, you will be able to recreate the related AWS objects and see this sample working in your own AWS environment. 

NOTE: It is possible that the AWS components used in this sample will change over time, but the principles showcased should hold true. Please let us know if there are any difficulties or problems executing the scripts and instructions.
