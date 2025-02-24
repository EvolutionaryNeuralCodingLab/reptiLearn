import arena

import experiment as exp
from experiment import session_state
import video_system as vid
import numpy as np

from image_observers.yolo_bbox_detector import BBoxDataCollector
import torch


class YOLOTestExperiment(exp.Experiment):
    """
    Simple experiment to test YOLOv7 detections.
    Just logs detection information for verification.
    """

    default_params = {
        "obs_id": "1",  # Default observer ID
        "detection_threshold": 0.5,  # Confidence threshold
        "print_all": True,  # Whether to print every detection or just summary
    }

    def setup(self):
        """Initialize the experiment"""
        self.log.info("Setting up detection experiment")
        # Validate observer exists
        params = exp.get_params()
        self.log.info(f"params: {params}")

        self.bbox_collector = BBoxDataCollector("1")
        self.print_next_detection = False

        # Initialize detection counter
        self.detection_count = 0
        self.last_timestamp = None

        self.actions["Test Response"] = {"run": self.respond}
        self.actions["FEED"] = {"run": self.feed}
        session_state["feeder_count"] = 15

    def respond(self):
        arena.run_command("toggle", "SSR")
        self.log.info("Testing Response")
        session_state["pin"] = [True if not session_state["pin"] else False][0]

    def feed(self):
        if not session_state["feeder_count"] == 0:
            arena.run_command("dispense", "Feeder", None, False)
            self.log.info("fed")
            session_state["feeder_count"] = session_state["feeder_count"] - 1
        else:
            self.log.info("No more food")

    def run(self):
        """Start the detection test"""
        params = exp.get_params()

        # Start the observer
        self.bbox_collector.start(self.on_detection)
        # arena.run_command("set_value", "ssr1", [1])
        # session_state["pin"] = True
        self.log.info(f"Starting YOLO test with confidence threshold {params['detection_threshold']}")

    def end(self):
        """Clean up"""
        if hasattr(self, 'remove_listener'):
            self.remove_listener()

        params = exp.get_params()
        if params["obs_id"] in vid.image_observers:
            vid.image_observers[params["obs_id"]].stop_observing()

    def on_detection(self, data, timestamp):
        """Handle each detection"""
        self.detection_count += 1

        # Calculate time since last detection
        if self.last_timestamp is not None:
            time_delta = timestamp - self.last_timestamp
        else:
            time_delta = None
        self.last_timestamp = timestamp

        # Only log if we have a valid detection
        if not np.any(np.isnan(data)):
            bbox_coords = data[:4]  # First 4 values are bbox coordinates
            confidence = data[4]  # Last value is confidence

            # Log every detection if print_all is True
            if exp.get_params()["print_all"]:
                self.log.info(
                    f"Detection #{self.detection_count}\n"
                    f"Location: {bbox_coords}\n"
                    f"Confidence: {confidence:.3f}\n"
                    f"Timestamp: {timestamp}\n"
                    f"Time since last: {time_delta}"
                )
            # Otherwise just periodic summary
            elif self.detection_count % 100 == 0:
                self.log.info(
                    f"Processed {self.detection_count} frames\n"
                    f"Latest detection - Confidence: {confidence:.3f}, Location: {bbox_coords}"
                )
            self.respond()
            self.log.info("responding on detection")


    def run_trial(self):
        """Start a new trial"""
        self.log.info("Starting new detection trial")
        self.detection_count = 0
        self.last_timestamp = None

    def end_trial(self):
        """End the trial"""
        self.log.info(f"Trial ended. Processed {self.detection_count} total frames")