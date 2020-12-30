
## Overview

Allows your AWS DeepLens to function like a home security camera.  When a person is detected, it will start recording a video stream and generate an email an alert that contains the video clip that starts at the time of detection. 

The functionality is split between the device and the cloud: the device generates raw IOT topic events and starts and stops the stream, the cloud reacts to those events, generates an HLS streaming session URL, and sends out an alert.

## Architecture

![Architecture](https://user-images.githubusercontent.com/296876/103382614-861be880-4aa4-11eb-8390-237d0ca8d9d7.png) 

## Getting it running

## Using a custom model

## Known issues

## References