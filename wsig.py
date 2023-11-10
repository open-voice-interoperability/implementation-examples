# This file contains the WSGI configuration required to serve up your
# web application at http://secondAssistant.pythonanywhere.com/
# It works by setting the variable 'application' to a WSGI handler of some
# description.
#

# +++++++++++ GENERAL DEBUGGING TIPS +++++++++++
# getting imports and sys.path right can be fiddly!
# We've tried to collect some general tips here:
# https://help.pythonanywhere.com/pages/DebuggingImportError



# +++++++++++ FLASK +++++++++++
# Flask works like any other WSGI-compatible framework, we just need
# to import the application.  Often Flask apps are called "app" so we
# may need to rename it during the import:
#
#
import sys
#
## The "/home/secondAssistant" below specifies your home
## directory -- the rest should be the directory you uploaded your Flask
## code to underneath the home directory.  So if you just ran
## "git clone git@github.com/myusername/myproject.git"
## ...or uploaded files to the directory "myproject", then you should
## specify "/home/secondAssistant/myproject"
#path = '/home/secondAssistant/implementation-examples/websockets'
#if path not in sys.path:
#    sys.path.append(path)

#add your project directory to the sys.path
project_home = '/home/secondAssistant/implementation-examples/websockets'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path
#
#from flask_app import app as application  # noqa
from secondaryAssistantFlask import app as application
#
# NB -- many Flask guides suggest you use a file called run.py; that's
# not necessary on PythonAnywhere.  And you should make sure your code
# does *not* invoke the flask development server with app.run(), as it
# will prevent your wsgi file from working.