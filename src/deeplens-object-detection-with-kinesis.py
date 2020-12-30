#*****************************************************
#                                                    *
# Copyright 2018 Amazon.com, Inc. or its affiliates. *
# All Rights Reserved.                               *
#                                                    *
#*****************************************************
""" A sample lambda for object detection"""
from threading import Thread, Event
import os
import time
import datetime
import json
import numpy as np
import awscam
import cv2
import greengrasssdk
import DeepLens_Kinesis_Video as dkv
from botocore.session import Session

class LocalDisplay(Thread):
    """ Class for facilitating the local display of inference results
        (as images). The class is designed to run on its own thread. In
        particular the class dumps the inference results into a FIFO
        located in the tmp directory (which lambda has access to). The
        results can be rendered using mplayer by typing:
        mplayer -demuxer lavf -lavfdopts format=mjpeg:probesize=32 /tmp/results.mjpeg
    """
    def __init__(self, resolution):
        """ resolution - Desired resolution of the project stream """
        # Initialize the base class, so that the object can run on its own
        # thread.
        super(LocalDisplay, self).__init__()
        # List of valid resolutions
        RESOLUTION = {'1080p' : (1920, 1080), '720p' : (1280, 720), '480p' : (858, 480)}
        if resolution not in RESOLUTION:
            raise Exception("Invalid resolution")
        self.resolution = RESOLUTION[resolution]
        # Initialize the default image to be a white canvas. Clients
        # will update the image when ready.
        self.frame = cv2.imencode('.jpg', 255*np.ones([640, 480, 3]))[1]
        self.stop_request = Event()

    def run(self):
        """ Overridden method that continually dumps images to the desired
            FIFO file.
        """
        # Path to the FIFO file. The lambda only has permissions to the tmp
        # directory. Pointing to a FIFO file in another directory
        # will cause the lambda to crash.
        result_path = '/tmp/results.mjpeg'
        # Create the FIFO file if it doesn't exist.
        if not os.path.exists(result_path):
            os.mkfifo(result_path)
        # This call will block until a consumer is available
        with open(result_path, 'w') as fifo_file:
            while not self.stop_request.isSet():
                try:
                    # Write the data to the FIFO file. This call will block
                    # meaning the code will come to a halt here until a consumer
                    # is available.
                    fifo_file.write(self.frame.tobytes())
                except IOError:
                    continue

    def set_frame_data(self, frame):
        """ Method updates the image data. This currently encodes the
            numpy array to jpg but can be modified to support other encodings.
            frame - Numpy array containing the image data of the next frame
                    in the project stream.
        """
        ret, jpeg = cv2.imencode('.jpg', cv2.resize(frame, self.resolution))
        if not ret:
            raise Exception('Failed to set frame data')
        self.frame = jpeg

    def join(self):
        self.stop_request.set()

class KinesisStreamer(object):

    """
    States:

        - NOT_STREAMING
        - STREAMING

    State variables:

        - STREAMING_STARTED_AT

    Logic:

        - See process_recognition_event() comments

    """

    def __init__(self, client, iot_topic, target_string_label, target_confidence):
        
        self.streaming_state = 'NOT_STREAMING'
        self.streaming_started_at = time.time()

        self.target_string_label = target_string_label
        self.target_confidence = target_confidence

        self.stop_streaming_timeout_secs = 60 * 2

        self.client = client 
        self.iot_topic = iot_topic

        # Stream configuration, name and retention
        # Note that the name will appear as deeplens-myStream
        stream_name = 'DeepLensPersonDetector'
        retention = 48 #hours

        # Use the boto session API to grab credentials
        session = Session()
        creds = session.get_credentials()

        # Create producer and stream.
        self.producer = dkv.createProducer(creds.access_key, creds.secret_key, creds.token, "us-east-1")
        self.client.publish(topic=self.iot_topic, payload="DKV Producer created.")
        self.kvs_stream = self.producer.createStream(stream_name, retention)
        self.client.publish(topic=self.iot_topic, payload="DKV Stream {} created".format(stream_name))

    def process_recognition_event(self, string_label, confidence):
        """
        string_label - eg, "person"
        confidence - a float between 0 and 1

        - If we're not_streaming
            - If we see a person with > 72% confidence, then start streaming and record STREAMING_STARTED_AT
            - Else, do nothing
        - If we're streaming
            - If we see a person with > 72% confidence, then keep streaming and reset STREAMING_STARTED_AT to now
            - Else, if no person recognized:
                - If STREAMING_STARTED_AT older than 30 mins, stop streaming and reset STREAMING_STARTED_AT
                - Else, keep streaming
        """
        try:
            if self.streaming_state == 'NOT_STREAMING':
                if string_label == self.target_string_label and confidence >= self.target_confidence:
                    self.transition_to_start_streaming()
            elif self.streaming_state == 'STREAMING':
                if string_label == self.target_string_label and confidence >= self.target_confidence:
                    self.streaming_started_at = time.time()
                else:
                    seconds_since_epoch = time.time()
                    if seconds_since_epoch - self.streaming_started_at > self.stop_streaming_timeout_secs:
                        self.transition_to_stop_streaming()
            else:
                raise Exception("Unexpected state: {}".format(self.streaming_state))
        except Exception as ex:
            self.client.publish(topic=self.iot_topic, payload='Error in process_recognition_event: {}'.format(ex))

    def transition_to_start_streaming(self):
        self.client.publish(topic=self.iot_topic, payload="Starting DKV Stream")
        self.streaming_state = 'STREAMING'
        self.streaming_started_at = time.time()
        # Start putting data into the KVS stream
        self.kvs_stream.start()
        self.client.publish(topic=self.iot_topic, payload="DKV Stream started")

    def transition_to_stop_streaming(self):
        self.client.publish(topic=self.iot_topic, payload="Stopping DKV Stream")
        self.streaming_state = 'NOT_STREAMING'
        self.streaming_started_at = time.time()
        # Stop putting data into the KVS stream
        self.kvs_stream.stop()
        self.client.publish(topic=self.iot_topic, payload="DKV Stream stopped")

def infinite_infer_run():
    """ Entry point of the lambda function"""
    try:
        # This object detection model is implemented as single shot detector (ssd), since
        # the number of labels is small we create a dictionary that will help us convert
        # the machine labels to human readable labels.
        model_type = 'ssd'
        output_map = {1: 'aeroplane', 2: 'bicycle', 3: 'bird', 4: 'boat', 5: 'bottle', 6: 'bus',
                      7 : 'car', 8 : 'cat', 9 : 'chair', 10 : 'cow', 11 : 'dinning table',
                      12 : 'dog', 13 : 'horse', 14 : 'motorbike', 15 : 'person',
                      16 : 'pottedplant', 17 : 'sheep', 18 : 'sofa', 19 : 'train',
                      20 : 'tvmonitor'}
        # Create an IoT client for sending to messages to the cloud.
        client = greengrasssdk.client('iot-data')
        iot_topic = '$aws/things/{}/infer'.format(os.environ['AWS_IOT_THING_NAME'])

        kinesis_streamer = KinesisStreamer(
            client, 
            iot_topic,
            'person',
            0.72,
        )

        # Create a local display instance that will dump the image bytes to a FIFO
        # file that the image can be rendered locally.
        local_display = LocalDisplay('480p')
        local_display.start()
        # The sample projects come with optimized artifacts, hence only the artifact
        # path is required.
        model_path = '/opt/awscam/artifacts/mxnet_deploy_ssd_resnet50_300_FP16_FUSED.xml'
        # Load the model onto the GPU.
        client.publish(topic=iot_topic, payload='Loading object detection model..')
        model = awscam.Model(model_path, {'GPU': 1})
        client.publish(topic=iot_topic, payload='Object detection model loaded.')
        # Set the threshold for detection
        detection_threshold = 0.25
        # The height and width of the training set images
        input_height = 300
        input_width = 300
        # Do inference until the lambda is killed.
        while True:
            # Get a frame from the video stream
            ret, frame = awscam.getLastFrame()
            if not ret:
                raise Exception('Failed to get frame from the stream')
            # Resize frame to the same size as the training set.
            frame_resize = cv2.resize(frame, (input_height, input_width))
            # Run the images through the inference engine and parse the results using
            # the parser API, note it is possible to get the output of doInference
            # and do the parsing manually, but since it is a ssd model,
            # a simple API is provided.
            parsed_inference_results = model.parseResult(model_type,
                                                         model.doInference(frame_resize))
            # Compute the scale in order to draw bounding boxes on the full resolution
            # image.
            yscale = float(frame.shape[0]) / float(input_height)
            xscale = float(frame.shape[1]) / float(input_width)
            # Dictionary to be filled with labels and probabilities for MQTT
            cloud_output = {}
            # Get the detected objects and probabilities
            for obj in parsed_inference_results[model_type]:
                
                if obj['prob'] > detection_threshold:

                    # Start or stop streaming to "capture" any video around recognition events
                    kinesis_streamer.process_recognition_event(
                        output_map[obj['label']], 
                        obj['prob']
                    )

                    # Add bounding boxes to full resolution frame
                    xmin = int(xscale * obj['xmin'])
                    ymin = int(yscale * obj['ymin'])
                    xmax = int(xscale * obj['xmax'])
                    ymax = int(yscale * obj['ymax'])
                    # See https://docs.opencv.org/3.4.1/d6/d6e/group__imgproc__draw.html
                    # for more information about the cv2.rectangle method.
                    # Method signature: image, point1, point2, color, and tickness.
                    cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (255, 165, 20), 10)
                    # Amount to offset the label/probability text above the bounding box.
                    text_offset = 15
                    # See https://docs.opencv.org/3.4.1/d6/d6e/group__imgproc__draw.html
                    # for more information about the cv2.putText method.
                    # Method signature: image, text, origin, font face, font scale, color,
                    # and tickness
                    cv2.putText(frame, "{}::: {:.2f}%".format(output_map[obj['label']],
                                                               obj['prob'] * 100),
                                (xmin, ymin-text_offset),
                                cv2.FONT_HERSHEY_SIMPLEX, 2.5, (255, 255, 0), 6)
                    # Store label and probability to send to cloud
                    cloud_output[output_map[obj['label']]] = obj['prob']
            # Set the next frame in the local display stream.
            local_display.set_frame_data(frame)
            # Send results to the cloud
            
            # this timestamp wasn't utc, but in local timezone, and without any timezone info
            # eg, "timestamp": "2020-12-30 00:41:41.052689"
            # cloud_output['timestamp'] = str(datetime.datetime.now())
            
            cloud_output['timestamp'] = datetime.datetime.utcnow().isoformat()
            client.publish(topic=iot_topic, payload=json.dumps(cloud_output))
            
    except Exception as ex:
        client.publish(topic=iot_topic, payload='Error in object detection lambda: {}'.format(ex))

infinite_infer_run()
