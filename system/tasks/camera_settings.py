"""
Tasks for automatically switching camera exposure and gain, e.g. between day and
night settings.

Edit DAY_SETTINGS and NIGHT_SETTINGS below to set the desired values for each
preset.

To run a preset automatically at a given hour, open the web UI, click the Tasks
menu, choose camera_settings.day_settings (or night_settings) -> Schedule, pick
the "timeofday" schedule type, set the time, and enable repeats to run it every
day.

Applying a preset restarts the video system (same as changing the video settings
in the UI). If a recording is in progress, it is stopped first and started again
with the same selected sources once the camera is back up, continuing in a new
video file.
"""
import time

import video_system
from rl_logging import get_main_logger

log = get_main_logger()

# The image source id from config/video_config.json
SRC_ID = "top"

DAY_SETTINGS = {
    "exposure": 25000,
    "gain": 2,
}

NIGHT_SETTINGS = {
    "exposure": 35000,
    "gain": 14,
}


def day_settings():
    _apply_settings(DAY_SETTINGS, "day")


def night_settings():
    _apply_settings(NIGHT_SETTINGS, "night")


def _apply_settings(settings, name):
    config = video_system.video_config
    src_config = config.get("image_sources", {}).get(SRC_ID)
    if src_config is None:
        log.error(
            f"camera_settings: image source '{SRC_ID}' was not found in the video config."
        )
        return

    if all(src_config.get(k) == v for k, v in settings.items()):
        log.info(
            f"camera_settings: '{name}' settings ({settings}) are already applied. Doing nothing."
        )
        return

    was_recording = video_system._rec_state.get("is_recording", False)
    selected_sources = list(video_system._rec_state.get("selected_sources", []))

    if was_recording:
        log.info("camera_settings: stopping the current recording before applying settings.")
        video_system.stop_record()
        # stop_record finishes asynchronously (uses timers).
        time.sleep(2)

    src_config.update(settings)
    log.info(f"camera_settings: applying '{name}' settings to '{SRC_ID}': {settings}")
    video_system.update_video_config(config)

    if was_recording:
        # Restarting the video system clears the recording state, so restore it.
        video_system.set_selected_sources(selected_sources)
        # Give the camera process time to initialize before recording again.
        time.sleep(8)
        log.info("camera_settings: resuming recording.")
        video_system.start_record()
