from __future__ import print_function

import json
import urllib
import boto3
import os
import time
import datetime
from botocore.config import Config

playback_mode = "LIVE"  # or "LIVE_REPLAY"

print('Loading message function...')

def get_kinesis_url(message):
    
    kinesis_url = ""
    
    # Not sure if the region config is needed
    my_config = Config(
        region_name = 'us-east-1',
    )
    
    # Do a loop to try to workaround the error 
    # Exception getting kinesis_url: An error occurred (ResourceNotFoundException) when calling the GetHLSStreamingSessionURL operation: No fragments found in the stream for the streaming request. stream_starttime: 2020-12-30 05:47:48.973288
    # Which might be a race condition
    for i in range(15):
    
        try:
            # Get a kinesis video endpoint
            STREAM_NAME = "DeepLensPersonDetector"
            kvs = boto3.client("kinesisvideo", config=my_config)
            # Grab the endpoint from GetDataEndpoint
            endpoint = kvs.get_data_endpoint(
                APIName="GET_HLS_STREAMING_SESSION_URL",
                StreamName=STREAM_NAME
            )['DataEndpoint']
            
            # Get a kinesis hls streaming session url that can be opened directly on ios safari
            kvam = boto3.client("kinesis-video-archived-media", endpoint_url=endpoint, config=my_config)
            
            if playback_mode == "LIVE":
                
                kinesis_url = kvam.get_hls_streaming_session_url(
                    StreamName=STREAM_NAME,
                    PlaybackMode="LIVE"
                )['HLSStreamingSessionURL']
                
            else:
                
                # not working!!  I don't know why, maybe there is increased delay before this is available.
                
                fmt = '%Y-%m-%dT%H:%M:%S.%f'
                message_timestamp = message['timestamp']
                print("message_timestamp: {}".format(str(message_timestamp)))
                stream_starttime = datetime.datetime.strptime(message_timestamp, fmt)
                print("stream_starttime: {}".format(str(stream_starttime)))
                
                kinesis_url = kvam.get_hls_streaming_session_url(
                    StreamName=STREAM_NAME,
                    PlaybackMode="LIVE_REPLAY",
                    HLSFragmentSelector={
                        'FragmentSelectorType': 'PRODUCER_TIMESTAMP',
                        'TimestampRange': {
                            'StartTimestamp': stream_starttime
                        }
                    }
                )['HLSStreamingSessionURL']
            
            print("kinesis_url: {}".format(str(kinesis_url)))
            return kinesis_url
            
        except Exception as ex:
            print("Exception getting kinesis_url: {}.  Sleeping and retrying {}th time".format(ex, i))
            
            # Sleep before trying again
            time.sleep(1)
    
    # Give up 
    return ""
        

def send_to_sns(message, context):

    sent_x_seconds_ago = last_message_sent_x_seconds_ago()
    if sent_x_seconds_ago < 30:
        return ('sent_x_seconds_ago: {} is too recent.  not sending SNS'.format(sent_x_seconds_ago))
    
    kinesis_url = get_kinesis_url(message)
    
    sns = boto3.client('sns')
    sns.publish(
        TopicArn='arn:aws:sns:us-east-1:193822812427:AwsDeepLensSNS',
        Subject='DeepLens Lambda notification',
        Message='Person detected, check em out at: ' + str(kinesis_url) + ' orig msg: ' + str(message)
    )

    return ('sent_x_seconds_ago: {} within range.  sending SNS'.format(sent_x_seconds_ago))

def last_message_sent_x_seconds_ago():
    
    last_sent_filename = "/tmp/last_sent_file"
    
    # by default, if we don't see the file, assume the last message was 
    # sent a long time ago to bust the de-dupe mechanism
    sent_x_seconds_ago = 10000000 
    
    if os.path.exists(last_sent_filename):
        # otherwise, read the value from the last_sent_file()
        with open(last_sent_filename, 'r') as f:
            prev_seconds_since_epoch = float(f.readline())
            seconds_since_epoch = datetime.datetime.now().timestamp()
            sent_x_seconds_ago = int(seconds_since_epoch - prev_seconds_since_epoch)
    
    # update last_sent_file with current time
    with open(last_sent_filename, 'w') as f:
        seconds_since_epoch = datetime.datetime.now().timestamp()
        f.write(str(seconds_since_epoch)) 
            
    return sent_x_seconds_ago
    
