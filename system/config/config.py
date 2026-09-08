from pathlib import Path

# Method for starting up child processes. Valid values are "spawn" and "fork".
# See https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
process_start_method = "spawn"

# Logging level of process and main loggers.
log_level = "DEBUG"

# Max number of recent log lines that will be stored in the log buffer. The log buffer contents
# are sent to the web UI whenever a connection is established.
log_buffer_size = 1000

# A tuple (host, port) of the shared state store server
state_store_address = ("127.0.0.1", 50000)

# Authkey of the shared state store
state_store_authkey = "reptilearn"

# Host and port number for the UI, REST and websocket server.
web_ui = {
    "host": "0.0.0.0",
    "port": 3500,
}


# Where experiment python modules can be found.
experiment_modules_dir: Path = Path("./experiments/")

# Where python modules containing tasks can be found.
tasks_modules_dir: Path = Path("./tasks/")

# Session data (videos, images, csv files, etc.) will be stored here.
session_data_root: Path = Path("/data/reptilearn/sessions/")

# Videos and images that were collected without an open session are stored here.
media_dir: Path = Path("/data/reptilearn/media/")

# Path to the video configuration file
video_config_path: Path = Path("./config/video_config.json")

# Path to the arena hardware controller configuration file
arena_config_path: Path = Path("./config/arena_config.json")

# Path to the arena hardware controller directory
arena_controller_path: Path = Path("../arena/")

# Path to a folder containing the bundled UI website
ui_build_path: Path = Path("../ui/build")

# Path to a folder containing static web assets. The url to access these assets will be: http://<api host>:<api port>/<static folder name>/<filename> (e.g. http://localhost:5000/stimuli/x.mp4)
static_web_path: Path = Path("../stimuli")

# Available archive directories
archive_dirs = {
    # Examples:
    #
    # "Archive1": Path("/path/to/archive/dir"),
    # "Archive2": Path("/path/to/another/archive/dir"),
}

# Image source streaming over HTTP settings
http_streaming = {
    "frame_rate": 15,  # http streaming frame rate
    # See https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.save
    # and https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
    "encoding": "JPEG",
    "encode_params": {"quality": 85},
}


video_record = {
    "video_frame_rate": 60,  # the default frame rate for recorded videos
    "file_ext": "mp4",
    "start_trigger_on_startup": False,
    "max_write_queue_size": 0,  # 0 means infinite queue.
    "encoding_configs": {
        # Video encoding parameters:
        # These parameters are passed to imageio.get_writer function
        # See available options here: https://imageio.readthedocs.io/en/stable/format_ffmpeg.html
        "cpu": {
            "codec": "libx264",
            "quality": 5,
            "macro_block_size": 8,  # to work with 1440x1080 image size
            "ffmpeg_log_level": "warning",
        },
        "gpu": {
            "codec": "libx264",
            "macro_block_size": 2,
            "pixelformat": "nv12",
            "ffmpeg_log_level": "warning",
            "output_params": [
                # "-init_hw_device", "cuda=nv:0",  # Initialize CUDA devic
                # "-filter_hw_device", "nv",  # Set hardware device for filters
                # "-hwaccel", "cuda",  # Enable CUDA hardware acceleration
                # "-hwaccel_device", "0",  # Use first GPU
                "-preset", "slow",
                "-vf", "format=nv12",  # Upload to GPU memory

            ]
        },
        "color": {
            "codec": "h264_nvenc",
            "quality": None,
            "macro_block_size": 1,
            "ffmpeg_log_level": "warning",
            "output_params": ["-preset", "slow", "-qp", "30"], # -rc constqp removed, but you can control the rate using the -qp (constant quantization parameter) or -b:v options
        },
    },
}

# MQTT broker server address
mqtt = {
    "host": "localhost",
    "port": 1883,
}


# Arena hardware controller
arena = {
    "poll_interval": 60,
    "displays": {"touchscreen": ":0"},

    # Set this to False if you don't want to run the arena controller together with the system
    "run_controller": True,

    # Uncomment the following lines to log values from the specified arena interfaces to a database table.
    # "data_log": {  # requires a database connection
    #     "table_name": "arena",
    #     "columns": [
    #         ("Magnetic Sensor_0", "double precision"),
    #         ("Magnetic Sensor_1", "double precision"),
    #         ("Magnetic Sensor_2", "double precision"),
    #         ("Magnetic Sensor_3", "double precision"),
    #     ],
    # },

    # Burn magnetometer readings into the live HTTP video stream (above the timestamp).
    "magnetic_sensor_overlay": {
        "enabled": True,
        "interface": "Magnetic Sensor",
        "image_sources": ["top"],
        "position": "top",
        # Grayscale stream: 0–255 scalar, or BGR [B,G,R] (auto-converted to brightness).
        # [0, 255, 255] ≈ bright yellow; [0, 0, 255] ≈ bright red; 255 = white.
        "color": [0, 255, 0],
        "font_scale": 2,
    },  # set enabled: False if no magnetometer is configured

    "command_topic": "arena_command",  # Arena commands will be published to this MQTT topic
    "receive_topic": "arena",  # Incoming arena messages will arrive on this MQTT topic
}


# Voice activation pipeline:
# openWakeWord -> Silero VAD -> faster-whisper -> allow-listed action router.
# Audio is streamed from the browser microphone over Socket.IO (16 kHz mono Int16 PCM).
voice = {
    "enabled": True,
    "wake": {
        # Name of a pretrained openWakeWord model ("hey_jarvis", "alexa", "hey_mycroft", ...)
        # or a path to a custom .onnx model file.
        "model": "hey_jarvis",
        # Wake score threshold (0-1). Higher means fewer false activations.
        "threshold": 0.5,
    },
    "vad": {
        # Silero VAD speech probability threshold (0-1).
        "threshold": 0.5,
        # Seconds of trailing silence that end an utterance.
        "silence_duration": 0.8,
        # Seconds to wait for speech to start after wake/trigger before giving up.
        "speech_timeout": 5.0,
        # Hard limit on utterance length in seconds.
        "max_utterance_duration": 10.0,
        # Seconds of audio kept from before speech onset.
        "pre_roll": 0.5,
    },
    "stt": {
        # Any faster-whisper model name or a path to a CTranslate2 model directory.
        "model": "large-v3-turbo",
        # "auto" uses CUDA when available, otherwise CPU.
        "device": "auto",
        # "default" resolves to float16 on GPU / int8 on CPU.
        "compute_type": "default",
        "language": "en",
    },
    "router": {
        # Minimum fuzzy-match ratio (0-1) between the transcript and an allowed phrase.
        "match_threshold": 0.75,
        # Allow-list mapping spoken phrases to experiment action labels. Only actions
        # listed here AND registered by the currently loaded experiment can be triggered.
        "allowed_actions": {
            "reset baseline": "Reset Baseline",
            "magnets forward": "Magnets Forward",
            "magnets reverse": "Magnets Reverse",
            "magnets stop": "Magnets Stop",
            "stop magnets": "Magnets Stop",
            "dispense left feeder": "Dispense Left Feeder",
            "feed left": "Dispense Left Feeder",
            "dispense right feeder": "Dispense Right Feeder",
            "feed right": "Dispense Right Feeder",
            "open left door": "Open Left Door",
            "close left door": "Close Left Door",
            "open right door": "Open Right Door",
            "close right door": "Close Right Door",
            "open back doors": "Open Back Doors",
            "close back doors": "Close Back Doors",
            "restart cycle": "Restart Cycle",
        },
        # Allow-list mapping spoken phrases to analysis panels. On a match the
        # backend broadcasts a "voice_analysis" Socket.IO event and the web UI
        # runs the analysis and shows the figure popup.
        # Panels: success, learning_curve, feeder, a_to_b, all.
        # Scopes: current, all_train, all_exp.
        "allowed_analysis": {
            "show success rate": {"panel": "success", "scope": "current"},
            "success rate": {"panel": "success", "scope": "current"},
            "show learning curve": {"panel": "learning_curve", "scope": "all_train"},
            "learning curve": {"panel": "learning_curve", "scope": "all_train"},
            "show feeder split": {"panel": "feeder", "scope": "current"},
            "right left split": {"panel": "feeder", "scope": "current"},
            "show travel time": {"panel": "a_to_b", "scope": "current"},
            "a to b travel time": {"panel": "a_to_b", "scope": "current"},
            "show all figures": {"panel": "all", "scope": "current"},
            "run all panels": {"panel": "all", "scope": "current"},
            "run analysis": {"panel": "all", "scope": "current"},
        },
    },
}

# Database connection
database = {
    "user": "tal",
    "host": "127.0.0.1",
    "port": 5432,
    "db": "reptilearn_test",
}

# Event data logger
event_log = {
    # This is a list of default events that will be logged. Additional events
    # can be defined in custom experiment modules. Either MQTT or state update
    # events can be used. See event_log.py for more information.
    "default_events": [
        ("mqtt", "arena_command"),
        ("state", ("session", "cur_block")),
        ("state", ("session", "cur_trial")),
        ("state", ("video", "record", "is_recording")),
    ],
    # Whether to log events to the database.
    "log_to_db": False,
    # Whether to log events to csv files.
    "log_to_csv": True,
    # The database table where events will be stored.
    "table_name": "events",
}


# Lens correction values for various camera and lens combinations. Each dict value
# should have "mtx" and "dist" keys.
undistort = {
    "my_camera": {
        "mtx": [
            [914.289260410433, 0.0, 738.2530922192],
            [0.0, 916.7566060572917, 545.55232072031],
            [0.0, 0.0, 1.0],
        ],
        "dist": [
            -0.003198193435908103, 0.025725188502646434, -0.0006498045722770118, 0.00019654022324491473, -0.026594087462206286
        ],
    }
}