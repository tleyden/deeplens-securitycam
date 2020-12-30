
## Overview

Allows your AWS DeepLens to function like a home security camera.  When a person is detected, it will start recording a video stream and generate an email an alert that contains the video clip that starts at the time of detection. 

The functionality is split between the device and the cloud: the device generates raw IOT topic events and starts and stops the stream, the cloud reacts to those events, generates an HLS streaming session URL, and sends out an alert.

## Architecture

![Architecture](https://user-images.githubusercontent.com/296876/103382614-861be880-4aa4-11eb-8390-237d0ca8d9d7.png) 

## Getting it running

### Define GreenGrass lambda function to run on DeepLens device

1. Create a sample project for deeplens-object-detection

1. Download the zip file for that project locally since it has the greengrass SDK

1. Create another lambda function, call it deeplens-object-detection-with-kinesis

1. Upload the zip file downloaded in the previous step

1. Paste the code from this repo in src/deeplens-object-detection-with-kinesis.py into the greengrassHelloworld.py via the AWS Console UI

1. Use these settings: **Runtime**: Python 2.7 **Handler** greengrassHelloWorld.function_handler

1. Hit the Deploy button

1. Hit the actions / publish new version button

## Create DeepLens project and associate with lambda function

Create a DeepLens project, let's assume it's called `Object-detection-with-kinesis`.

**Model**: deeplens-object-detection  (same as sample project deeplens-object-detection)

**Function**: deeplens-object-detection-with-kinesis/versions/1  (you will need to increment the version whenever you change the lambda function)

Now deploy the project to your DeepLens, overwriting the existing project.  On the DeepLens device page click the lambda logs link under Device Details, and make sure there aren't any major errors.  You can also check the AWS IoT console and you should see detection messages like `{"person": 0.344323}` if you stand in front of the camera.

### Define SNS topic 

Define a new SNS topic called `AwsDeepLensSNS` and subscribe your email address to it. 

### Define cloud lambda function to receive IoT events

1. Create a new lambda function called AWSDeeplensSNSDeduped

1. Paste the code from src/AWSDeeplensSNSDeduped.py in this repo into `lambda_function.py`

1. Change **Runtime** to Python 3.7 and **Handler** to lambda_function.send_to_sns

1. Set an environment variable `SNS_TOPIC_ARN` the ARN of the SNS topic created in previous step

1. Under Permissions, open the generated role (eg, AWSDeeplensSNSDeduped-role-es8t9bve) and add the following policies: **AmazonKinesisVideoStreamsFullAccess** and **AmazonSNSFullAccess** (there's probably a more secure way, please file an issue if you have ideas)

1. Under Basic Settings, set the timeout to 1 min 0 sec

1. Hit the Deploy button 

### Define IoT core rule to forward to lambda function

```
SELECT * FROM '$aws/things/deeplens_xxxxx/infer' WHERE person > 0.72
```

And create a new action that invokes the cloud lambda function defined above.

## Testing it out

### Stand in front of the camera

Wave your hands ..

### Wait for an email notification

If it all works, you should get an email alert:

```
Person detected, check em out at: https://b-0433bf65.kinesisvideo.us-east-1.amazonaws.com/hls/.........~ orig msg: {'car': 0.298095703125, 'timestamp': '2020-12-30T18:26:36.384497', 'person': 0.62451171875}
```

If you open the link in Safari on OSX or iOS, it should play the video stream starting from the time of detection.

### Debug if you don't get it

The best places to look are:

* The lambda logs link under Device Details for the DeepLens device
* In the deeplens-object-detection-with-kinesis lambda function, hit the **Monitoring** section and click **View Logs In CloudWatch**  

## Using a custom model

TODO

## Known issues

1. After a while the emails no longer contain the Kinesis streaming URL link.  Redeploying a new version of the DeepLens project seems to fix it for a while.  Restarting the DeepLens might also fix it.

## References

* [Amazon Kinesis Video Streams Adds Support For HLS Output Streams](https://aws.amazon.com/blogs/aws/amazon-kinesis-video-streams-adds-support-for-hls-output-streams/)

* [DeepLens_Kinesis_Video Module for Amazon Kinesis Video Streams Integration](https://docs.aws.amazon.com/deeplens/latest/dg/deeplens-kinesis-video-streams-api.html)

* [Extend AWS DeepLens to Send SMS Notifications with AWS Lambda](https://aws.amazon.com/blogs/machine-learning/extend-aws-deeplens-to-send-sms-notifications-with-aws-lambda/)

* [AWS api docs for get_hls_streaming_session_url](https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/API_reader_GetHLSStreamingSessionURL.html)

* [Boto API docs for get_hls_streaming_session_url](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/kinesis-video-archived-media.html#KinesisVideoArchivedMedia.Client.get_hls_streaming_session_url)

* [DeepLens sample projects](https://docs.aws.amazon.com/deeplens/latest/dg/deeplens-templated-projects-overview.html)

