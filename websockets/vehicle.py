from simplejsondb import Database

# If database named 'vehicle' doesn't exist yet, creates a new empty dict database
vehicle = Database('vehicle.json', default=dict())


# Now, we can treat the database instance as a dictionary!

vehicle.data['oil change'] = 'yes, your 2018 Outback is due for an oil change'
vehicle.data['tire rotation'] = 'yes, your Subaru Outback is due for a tire rotation'
vehicle.data['state inspection'] = 'no, your 2018 Subaru Outback does not need a state inspection. you will need a state inspection in three months'
print(vehicle.data.values())
