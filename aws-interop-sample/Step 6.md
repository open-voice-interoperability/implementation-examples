# Step 6: Create a Web UI for the Airline System Bot

Let's spin up a new client by using the Sample Amazon Lex Web Interface from GitHub. To create this, follow these steps:

1. In a new tab, navigate to [https://github.com/aws-samples/aws-lex-web-ui](https://github.com/aws-samples/aws-lex-web-ui).
2. Scroll down to the getting started section and click the Launch Stack button for the region you want the Web UI to be hosted in.
3. In the Quick create stack screen, enter a Stack name, such as MyAirlineBotWebUIStack.
4. Change the CodeBuildName to something unique to the region, such as MyAirlineBotWebUI.
5. Scroll down to the Lex V2 Bot section. Flip back to the Bot tab and copy the Bot ID and paste it into the LexV2BotId parameter in the CloudFormation - Stack tab.

    ![Copy the Bot ID](./images/image-7.png)

6. Click on the View aliases button back in the Bot tab.
7. Select the PROD Alias. Copy the Alias ID into the LexV2BotAliasId parameter in the CloudFormation - Stack tab.
8. Enter **You can ask me to book a flight. Just type "Book a Flight" or click on the mic and say it.** in the WebAppConfBotInitialText parameter.
9. Enter **Say 'Book a Flight' to get started.** in the WebAppConfInitialSpeech parameter.
10. Enter **Book a Flight** in the WebAppConfToolbarTitle parameter.
11. Set the ShouldLoadIframeMinimized parameter to true.
12. Scroll to the bottom, check the warnings and click Create stack.
13. Wait for CloudFormation to finish the deployment. Then click on the parent stack, such as MyAirlineBotWebUIStack. Click the Outputs tab. Click the WebAppDomainName link (a CloudFront domain). NOTE: Despite all the settings, the page title will be Order Flowers Bot.

    (The easiest(?) way to fix this, is to navigate to the S3 Bucket: myairlinebotwebuistack-codebuild-webappbucket-xxxxxxxx. Then, download the  lex-web-ui-min.js JavaScript file. Open it in a text editor and search for "Order Flowers Bot" and replace it with "Book a Flight Bot". Save the file and upload it back to the bucket. Then, to clear the CloudFront cache, flip over to CloudFront, open the distribution for the lex-web-ui, select the invalidations tab, select one of the invalidations, select Copy to New, then select Create Invalidation. Once the cache is cleared, the changes to the JavaScript will be apparent when you hard refresh the Lex UI in your browser.)

14. Done.

- [Back < Step 5: Create the Airline System Lex Bot](Step%205.md)
- [Next > Step 7: Modify the Airline System Bot to Expose the OVON Interface](Step%207.md)
