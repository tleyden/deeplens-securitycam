from __future__ import print_function

import json
import urllib
import boto3
import os
import time
import sys
import datetime
from botocore.config import Config

playback_mode = "LIVE_REPLAY"  # or "LIVE_REPLAY"
STREAM_NAME = "DeepLensPersonDetector"
FRAGMENT_SELECTOR_TYPE='SERVER_TIMESTAMP' # or PRODUCER_TIMESTAMP
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']

def get_recent_fragment_timestamp(kvam):

    # Get a list of recent fragments 
    fragments = kvam.list_fragments(
        StreamName=STREAM_NAME,
        MaxResults=1000,
        FragmentSelector={
            'FragmentSelectorType': FRAGMENT_SELECTOR_TYPE,
            'TimestampRange': {
                'StartTimestamp': datetime.datetime.now() - datetime.timedelta(minutes=2),
                'EndTimestamp': datetime.datetime.now()
            }
        }
    )['Fragments']

    # If no fragments found, throw an exception
    if len(fragments) == 0:
        raise Exception("No recent fragments found")
    print("Found {} recent fragments".format(len(fragments)))

    # Find fragment with lowest fragment number (earliest)
    # Not exactly efficient, but hopefully there is a better way and this can get thrown away.
    lowest_fragment_number = int(fragments[0]['FragmentNumber'])
    least_recent_fragment = None
    for fragment in fragments:
        if int(fragment['FragmentNumber']) <= lowest_fragment_number:
            least_recent_fragment = fragment
            lowest_fragment_number = int(fragment['FragmentNumber'])

    # Return the timestamp of fragment with highest fragment number
    if FRAGMENT_SELECTOR_TYPE == 'PRODUCER_TIMESTAMP':
        return least_recent_fragment['ProducerTimestamp']
    else:
        return least_recent_fragment['ServerTimestamp']

def get_timestamp_from_message(message):
    # Overall approach not working!!  
    # It seems to always return Exception getting kinesis_url: An error occurred (ResourceNotFoundException) when calling the GetHLSStreamingSessionURL operation: No fragments found in the stream for the streaming request. stream_starttime: 2020-12-30 05:47:48.973288
    fmt = '%Y-%m-%dT%H:%M:%S.%f'
    message_timestamp = message['timestamp']
    print("message_timestamp: {}".format(str(message_timestamp)))
    stream_starttime = datetime.datetime.strptime(message_timestamp, fmt)
    print("stream_starttime: {}".format(str(stream_starttime)))
    return stream_starttime

def get_kinesis_url(message):

    """
    The kinesis hls streaming session url is the most important part of the email notification,
    since clicking it will show a video stream starting at the point of detection, which will 
    hopefully include the detected person.

    This part is not working reliably yet (see known issues in README).
    """
    
    kinesis_url = ""
    
    # Not sure if the region config is needed
    my_config = Config(
        region_name = 'us-east-1',
    )
    
    # The reason this loops is to try to "wait" until fragments are available on the stream.
    # It will sleep 1s in between each loop iteration.
    for i in range(20):
    
        try:
            # Get a kinesis video endpoint
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

                # stream_starttime = get_timestamp_from_message(message)
                stream_starttime = get_recent_fragment_timestamp(kvam)
                print("get_recent_fragment_timestamp returned: {}".format(stream_starttime))
                
                kinesis_url = kvam.get_hls_streaming_session_url(
                    StreamName=STREAM_NAME,
                    Expires=43200, # 12 hours
                    PlaybackMode="LIVE_REPLAY",
                    HLSFragmentSelector={
                        'FragmentSelectorType': FRAGMENT_SELECTOR_TYPE,
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

    """
    Send to SNS with de-duping to avoid firing off too many duplicate notifications.
    It de-dupes by writing to a temp file, and future (hotstart) lambda invocations 
    check the temp file to see how long ago the last notification was sent.
    """

    sent_x_seconds_ago = last_message_sent_x_seconds_ago()
    if sent_x_seconds_ago < 30:
        return ('sent_x_seconds_ago: {} is too recent.  not sending SNS'.format(sent_x_seconds_ago))
    
    # Get the kinesis HLS streaming url to include in the message
    kinesis_url = get_kinesis_url(message)
    
    # Send SNS
    sns = boto3.client('sns')
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject='DeepLens Lambda notification',
        Message='Person detected, check em out at: ' + str(kinesis_url) + ' orig msg: ' + str(message)
    )

    result = ('sent_x_seconds_ago: {} within range.  sending SNS'.format(sent_x_seconds_ago))
    print(result)
    return result

def last_message_sent_x_seconds_ago():

    """
    The /tmp file approach is a dirty hack and isn't very reliable.  A database or a lambda
    step function state machine would be a better approach.
    """
    
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
    
