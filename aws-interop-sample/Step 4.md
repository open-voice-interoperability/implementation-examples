# Step 4: Wire up the Lex Bot to the ToDo WebApp

Now, we need to wire up the API call to put the appointment from the bot into the ToDo WebApp.

1. In the AWS Console, search and select Lex.
2. Select the MakeAppointment bot.
3. Drill down to the intents list. Select the MakeAppointment intent.
4. Scroll down to the fulfilment section. Set the Active toggle to on. Click on Save Intent.
5. Now switch to the CloudFront console.
6. Locate the CloudFront distribution you created for the ToDo WebApp.
7. Select the Origins tab.
8. Select origin2 for the API Gateway and click Edit.
9. Copy the Origin domain shown and save it for use in the next steps.
10. Now switch to the Lambda console.
11. Locate the Lambda function you created for the bot.
12. In the lambda_function.py module, scroll down to the bottom, then scroll up a little to above the line:

```python
    """ --- Intents --- """
```

13. Above that line, insert the following function to call the API to create a ToDo Item:

    ```python
    def send_booking_to_todo_app(appointment_type, date, appointment_time, duration):
        """
        Called to write the appointment as a todo card in the todo webapp
        """
        logger.debug('Trying to save to ToDo app.')

        title = f"{appointment_type} Appointment"
        description = f"{appointment_type} Appointment on {date} at {appointment_time} for {duration} minutes."

        data = {
            "title": title,
            "description": description
        }
        # Replace with your API Gateway URL
        gateway = "https://l2py6m5sqe.execute-api.us-east-1.amazonaws.com
        url = f"{gateway}/prod/api/todos"
        response = requests.post(url, json=data)

        if response.status_code != 201:
            logger.debug('Failed to save to ToDo app.')
            raise Exception(f"There was a problem saving the ToDo item.\nError code: {response.status_code}")
    ```

14. Scroll up to the make_appointment() function.
15. Near the end of that function is code that looks like this:

```python
    else:
        # This is not treated as an error as this code sample supports functionality either as fulfillment or dialog code hook.
        logger.debug('Availabilities for {} were null at fulfillment time.  '
                     'This should have been initialized if this function was configured as the dialog code hook'.format(date))
    intent['state'] = 'Fulfilled'
```

16. Comment out the entire else section.
17. Then, insert the following two lines before the intent['state'] = 'Fulfilled' line:

```python
    send_booking_to_todo_app(appointment_type, date, appointment_time, duration)
    logging.debug('Saved the booking to the ToDo app.')
```

18. The finished code will look like this:

```python
    # else:
    #     # This is not treated as an error as this code sample supports functionality either as fulfillment or dialog code hook.
    #     logger.debug('Availabilities for {} were null at fulfillment time.  '
    #                  'This should have been initialized if this function was configured as the dialog code hook'.format(date))

    send_booking_to_todo_app(appointment_type, date, appointment_time, duration)
    logging.debug('Saved the booking to the ToDo app.')

    intent['state'] = 'Fulfilled'
```

19. Then, change the return json to:

```python
    return {
        'sessionState': {
            'dialogAction': {
                'type': 'Close'
            },
            'intent': intent
        },
        'requestAttributes': {},
        'messages': [
            {
                'contentType': 'PlainText',
                'content': 'Okay, I have booked your appointment.  We will see you at {} on {}'.format(build_time_output_string(appointment_time), date)
            }
        ]
    }
```

20. Deploy the Lambda function.
21. Run the bot through the Web UI to ensure the ToDo item is created.
22. Done.
