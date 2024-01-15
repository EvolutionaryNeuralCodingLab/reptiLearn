# Camera configuration

Camera image data is made available to ReptiLearn by ImageSource objects. Several classes of ImageSource are available after installing the software. Each camera you wish to use needs to be configured with one of these classes.

ReptiLearn currently supports the following camera GeniCam SDKs:
- [Teledyne FLIR Spinnaker SDK](https://www.flir.eu/products/spinnaker-sdk/)
- [Allied Vision Vimba SDK](https://www.alliedvision.com/en/products/vimba-sdk/) (experimental)

These SDKs support reliable image timestamps and allow to synchronize acquisition from multiple cameras. In addition, webcams and video files can also be used as sources using the OpenCV library (see below) but these sources do not provide accurate timing.

## Install camera SDK

Before setting up GeniCam cameras in ReptiLearn, you need to install the SDK you plan to use. Make sure to also install the __python bindings__ for your SDK (e.g. PySpin for Spinnaker) and that the bindings library is available when the reptilearn python environment is active.

## Configure ImageSources

To configure an ImageSource open the ReptiLearn web UI, open the Video menu, and click on "Video Settings...". A window should open with two tabs - Sources and Observers. Make sure you are in the Sources tab and click on the plus button to add a new ImageSource. 

In the dialog that opens choose the ImageSource class that you want to use. Select `video_source.VideoImageSource` to use the OpenCV library to stream from webcams or video files. Select `flir_cameras.FLIRImageSource` to use FLIR Spinnaker SDK, or `allied_vision_cameras.AlliedVisionImageSource` to use Allied Vision Vimba SDK. Next, enter an Id for the new ImageSource and click on the Add button.

A new ImageSource should be created and its id should appear on the dropdown list on the top right corner of the video settings window. Select the new source from the list, if it's not already selected, to view and edit its configuration parameters. 

Common ImageSource parameters:
- `class` (required): the Python ImageSource subclass used with this ImageSource. This is set when first adding the source and should not be changed manually.
- `image_shape` (required): An array of number of rows, columns and channels. This parameter sets the shape of the memory buffer used to store images acquired by this source. This value depends on the camera resolution and number of channels. For a grayscale camera with a resolution of A pixels high and B pixels wide use `[A, B]` (no. of rows, no. of columns). For a color RGB camera with the same dimensions use `[A, B, 3]` to account for red, green and blue channels. Default value is None.
- `encoding_config` (required): A string containing the name of an encoding configuration used to encode frames into video files. This should be one of the keys defined in the ReptiLearn config file under video_record encoding_configs. Default value is null.
- `disabled`: true or false. Whether the ImageSource should be loaded or not. Default value is false.
- `buf_dtype`: The buffer data type of each image pixel channel. Currently "uint8" or "uint16" are supported, for unsigned 8-bit integer or unsigned 16-bit integer respectively. This depends on the bit depth used by your camera. Default value is "uint8".
- `8bit_scaling`: Should be used in case buf_dtype is "uint16". Videos and images can currently only be encoded in 8 bits per pixel channel. This configures the way 16 bit pixel values are scaled to 8 bits. It can be either:
   - `"auto"` (string): Scale pixel intensities linearly so that the image minimum becomes 0 and the maximum becomes 255.
   - `"full_range"` (string): Linear scaling which maps 0 to 0 and 65535 to 255.
   - `[a, b]` (any two-element array): Linear scaling which maps a to 0 and b to 255.
- `video_frame_rate`: Integer. The number of frames per second. Used for setting the speed of recorded videos. When this is set to null the value of the `frame_rate` parameter will be used instead. If that parameter is not set as well the frame rate is set by the `video_frame_rate` value in the video_record variable of the main config file. Default value is null.

### Configuring FLIR cameras

The flir_cameras.FLIRImageSource class provides additional configuration parameters to configure the camera:
-  `serial_number` (required): The serial number of the camera you wish to use. This string is usually printed somewhere on the camera itself and used to identify a specific camera.
- `exposure`: Integer number. Acquisition exposure time in microseconds. Default value is 8000µs.
- `trigger`: true or false. Whether a trigger should be used to trigger frame acquisition. Default value is true.
- `trigger_source`: Determines the trigger source when using a trigger. See [here](http://softwareservices.flir.com/Spinnaker/latest/group___camera_defs__h.html#gae197f5f767ec00af9bb4149e96446fe8) for a list of possible values. For example, to use GPIO Line0 enter "Line0" (excluding the TriggerSource_ prefix). Default value is Line3.
- `frame_rate`: Integer number. The number of frames acquired per second when not using a trigger or null. When this parameter is not null any trigger parameters will be ignored. Default value is null.
- `pyspin`: Object. Key value pairs for setting any PySpin properties. For example to set the camera PixelFormat property to PixelFormat_BGR8 and the AdcBitDepth property to AdcBitDepth_Bit10 you can use: `{ "PixelFormat": "BGR8", "AdcBitDepth": "Bit10" }` (note that the PixelFormat_ and AdcBitDepth_ prefixes are removed). See the Spinnaker documentation for a full list of options.
- `stream_id`: Integer number. The index of the stream to acquire images from. This is useful for cameras that provide multiple image streams.
- `acquisition_timeout`: Integer number. The number of milliseconds to wait for an image to arrive before giving up. Default value is 5000 (5 seconds).
- `restart_on_timeout`: true or false. When set to true, the camera is reinitialized whenever an acquisition timeout is encountered. Default value is false.

### Configuring OpenCV VideoCapture

The video_source.VideoImageSource class can be used to acquire images from common webcams or stream from video files (useful for testing purposes) using OpenCV VideoCapture object. The `image_shape` parameter can be omitted in which case the shape is inferred from the VideoCapture object. This class provides the following additional configuration parameters:

- `video_path` (required): String or integer number. To stream from a video file enter the file path here. To stream from a camera enter a number id for the camera you want to use (starting from 0).
- `frame_rate`: Integer number. Acquisition rate in frames per second. Only used for camera streams. Default value is null. 
- `start_frame`: Integer number. Used with video file playback. The number of the first frame that will be played. Default value is 0.
- `end_frame`; Integer number. Used with video file playback. The number of the last frame that will be played. A value of null will cause the ImageSource to play until the end of the file. Default value is null
- `repeat`: true, false or integer number. Used for video file playback. When set to true or a number the ImageSource will restart playback when reaching the last frame. A number can be used to set the number of repeats. When set to false playback stop after the last frame.
- `is_color`: true or false. Whether the stream will contain color or grayscale images. Used to set the image shape of the source. Default value is false.

### Configuring Allied Vision cameras

Allied Vision Vimbda SDK is supported experimentally using the allied_vision_cameras.AlliedVisionImageSource class. Refer to the [source code](../system/image_sources/allied_vision_cameras.py) for more information about available configuration parameters.