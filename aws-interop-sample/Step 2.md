# Step 2: Create the Lex Appointment Bot and Lambda Function

## Part 1 - Create the Lex Appointment Bot

Follow these steps to create an Amazon Lex Appointment Bot.

1. In the AWS Console, search for the Lex service.
2. Select the Amazon Lex tile.
3. In the Bots section, select the Create bot button.
4. Click on Start with an example.
5. Select the MakeAppointment Sample bot.
6. Enter the Bot Name, such as MyAppointmentBot.
7. In IAM permissions, Select to Create a role with basic Amazon Lex permissions.
8. In the Children's Privacy, select No.
9. Click the Next button.
10. In the Add a language screen, select a voice for your Voice interaction.
11. Click Done.
12. Shortly, you will be on the Intent: MakeAppointment screen. Click the Save intent button.
13. At the top, click the Build button.
14. Once built, click the Test button to try out your bot.

- Start with "I need to make an appointment."
- Then, "A dentist appointment."
- Then, "Tomorrow."
- Then, "Now."
- Then, "Yes."

   You should see the intent is fulfilled.

15. Done.

## Part 2 - Create the Lambda Function

Follow these steps to create an Amazon Lambda Function for the Appointment Bot backend.

1. In the AWS Console, search for the Lambda service.
2. Select the Lambda tile.
3. Select the Create function button.
4. Select to Use a blueprint.
5. Select the blueprint named Make an Appointment with Lex.
6. Give the function a name, such as MyLexAppointmentBotFunction.
7. Scroll down and select the Create function button.
8. With the function created, flip back to the Lex console.
9. Select the MakeAppointment bot you created in Part 1.
10. Select the Aliases tab under Deployment.
11. Select the TestBotAlias.
12. Select the English language link.
13. Change the Lambda function Source to the Lambda function you just created.
14. Save the change.
15. Now, we need to release the bot to Prod. Select the link to go back to the aliases list.
16. Select Bot Versions on the left.
17. Create a new version named Prod.
18. Done.

- [Back < Step 1: Create the ToDo WebApp as an Amazon CodeCatalyst Project](./Step%201.md)
- [Next > Step 3: Create a Web UI for the Appointment Bot](./Step%203.md)
