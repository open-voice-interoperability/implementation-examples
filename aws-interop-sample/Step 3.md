# Step 3: Create a Web UI for the Appointment Bot
In order to work with the Lex Bot, it needs a client. The easiest way to spin up a client is to use the Sample Amazon Lex Web Interface from GitHub. To create this, follow these steps:
 1. In a new tab, navigate to https://github.com/aws-samples/aws-lex-web-ui.
 2. Scroll down to the getting started section and click the Launch Stack button for the region you want the Web UI to be hosted in.
 3. In the Quick create stack screen, enter a Stack name, such as MyAppointmentBotWebUIStack.
 4. Change the CodeBuildName to something unique to the region, such as MyAppointmentBotWebUI.
 5. Scroll down to the Lex V2 Bot section. Flip back to the Bot tab and copy the Bot ID and paste it into the LexV2BotId parameter in the CloudFormation - Stack tab.  
 ![Copy the Bot ID](./images/image-7.png)  
 6. Click on the View aliases button back in the Bot tab. Click the Create alias button. Enter PROD as the name. Choose Version 1 as the version. Click Create.
 7. Select the PROD Alias. Copy the Alias ID into the LexV2BotAliasId parameter in the CloudFormation - Stack tab.
 8. Scroll down to Web Application Parameters. Enter the web address of the S3 bucket for the ToDo WebApp in the WebAppPath. To get this value, you will need to open a new tab to the AWS Console and search for the CloudFront service. Now, select the distribution for the ToDo WebApp. Then select the Origins tab. Select Origin1. Click Edit. Copy the URL shown in the Origin domain field. Paste this URL into the WebAppParentOrigin parameter.
 9. Enter **/index.html** in the WebAppPath parameter.
 10. Enter **You can ask me to make an appointment. Just type "Make an appointment" or click on the mic and say it.** in the WebAppConfBotInitialText parameter.
 11. Enter **Say 'Make an Appointment' to get started.** in the WebAppConfInitialSpeech parameter.
 12. Enter **Make an Appointment** in the WebAppConfToolbarTitle parameter.
 13. Set the ShouldLoadIframeMinimized parameter to true.
 14. Scroll to the bottom, check the warnings and click Create stack.
 15. Wait for CloudFormation to finish the deployment. Then click on the parent stack, such as MyAppointmentBotWebUIStack. Click the Outputs tab. Click the WebAppDomainName link (a CloudFront domain). NOTE: Despite all the settings, the page title will be Order Flowers Bot. 

 

TODO:
- Get the chatbot icon to show on the ToDo WebApp page
- Fix the Page title.
- Add a favicon to the app.

In CodeCatalyst, clone the repo to your local machine.
Then, navigate to the frontend folder and open a command window.
Then:
```bash
# install npm package from github repo
npm install --save awslabs/aws-lex-web-ui
# you may need to install co-dependencies:
npm install --save vue vuex vuetify material-design-icons roboto-fontface
```
 In frontend/src/App.tsx:
 ```javascript
  // dependencies
  import Vue from 'vue';
  import Vuex from 'vuex';
  import Vuetify from 'vuetify';

  // import the component constructor
  import { Loader as LexWebUi } from 'aws-lex-web-ui';

  Vue.use(Vuetify);
  Vue.use(Vuex);

  // plugin creates the LexWebUi component
  const lexWebUi = new LexWebUi({
    // pass your own configuration
    cognito: {
      poolId: 'us-east-1:momrules-fade-babe-cafe-0123456789ab',
    },
    lex: {
      initialText: 'How can I help you?',
      botName: 'helpBot',
      botAlias: '$LATEST',
    },
    ui: {
      toolbarTitle: 'Help Bot',
      toolbarLogo: '',
    },
  });
 ```

Replace the cognito poolId (get from CloudFormation Stack) and the botName (get from Lex).

