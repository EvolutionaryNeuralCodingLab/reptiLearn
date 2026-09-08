import arena
import data_log
import experiment as exp
from experiment import session_state
import video_system as vid
import numpy as np
import csv
import time
from pathlib import Path
from image_observers.yolo_bbox_detector import BBoxDataCollector
import torch


class YOLOTestExperiment(exp.Experiment):
    """
    Simple experiment to test YOLOv7 detections.
    Just logs detection information for verification.
    """

    default_params = {
        "obs_id": "1",  # Default observer ID
        "detection_threshold": 0.1,  # Confidence threshold
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
        self.actions["Open LEFT END DOOR"] = {"run": self.open_door_le}
        self.actions["Close LEFT END DOOR"] = {"run": self.close_door_le}
        self.actions["Open RIGHT END DOOR"] = {"run": self.open_door_re}
        self.actions["Close RIGHT END DOOR"] = {"run": self.close_door_re}

        # self.actions["Toggle LED 1"] = {"run": self.toggle_led1}
        # self.actions["Toggle LED 2"] = {"run": self.toggle_led2}

        self.actions["Switch SSR 1"] = {"run": self.switch_ssr1}
        self.actions["Switch SSR 2"] = {"run": self.switch_ssr2}
        self.actions["Switch SSR 3"] = {"run": self.switch_ssr3}
        self.actions["Switch SSR 4"] = {"run": self.switch_ssr4}

        self.actions["Feeder 1"] = {"run": self.feeder1}

        session_state["pin"] = True
        session_state["feeder_count"] = 15


    def trial(self):
        decision_area = self.decision_area["decision_area"]
        if self.location in decision_area:
            self.start_trial()
            self.close_reset_door()
            self.decision_doors("open")
            self.check_location()
        elif not self.location in decision_area:
            self.decision_doors("close")
            self.check_correct_choice()
            self.open_reset_door()
            self.end_trial()
            self.check_location()

    def start_trial(self):
        self.activate_magnetic_field()
        self.log.info(f"Starting trial {self.trial_id}, time {time.time}, success rate {self.success_rate}, food available {self.food_available}")
        
    def decision_doors(self, action):
        if action == "open":
            self.log.info("Opening decision doors")
            arena.run_command("open", "decision_door_1", None, False)
            arena.run_command("open", "decision_door_2", None, False)
        elif action == "close":
            self.log.info("Closing decision doors")
            arena.run_command("close", "decision_door_1", None, False)
            arena.run_command("close", "decision_door_2", None, False)

    def check_location(self):
        # update session state on chosen side (L / R)
        pass

    def reset_door(self):
        pass

    def check_correct_choice(self):
        if session_state.current_choice == session_state.magnetic_field_direction:
            if session_state.current_choice == "LEFT":
                arena.run_command("dispense", "left_feeder", None, False)
                session_state.left_feeder = session_state.left_feeder - 1
            else:
                arena.run_command("dispense", "right_feeder", None, False)
                session_state.right_feeder = session_state.right_feeder - 1
            if session_state.right_feeder == 0 or session_state.left_feeder == 0:
                self.notify_no_food()


    def feeder1(self):
        pass

    def toggle_led1(self):
        arena.run_command("toggle", "ssr1", None, False)
        arena.run_command("toggle", "ssr2", None, False)
        session_state["arena", "values", "ssr1"] = 1 - session_state["arena", "values", "ssr1"]
        session_state["arena", "values", "ssr2"] = 1 - session_state["arena", "values", "ssr2"]

    def toggle_led2(self):
        arena.run_command("toggle", "ssr3", None, False)
        arena.run_command("toggle", "ssr4", None, False)
        session_state["ssr3"] = 1 - session_state["ssr3"]
        session_state["ssr4"] = 1 - session_state["ssr4"]


    def switch_ssr1(self):
        arena.run_command("toggle", "ssr1", None, False)
    def switch_ssr2(self):
        arena.run_command("toggle", "ssr2", None, False)
    def switch_ssr3(self):
        arena.run_command("toggle", "ssr3", None, False)
    def switch_ssr4(self):
        arena.run_command("toggle", "ssr4", None, False)

    def open_door_le(self):
        self.log.info("Opening le door")
        arena.run_command("open", "left_end_door", None, False)

    def close_door_le(self):
        self.log.info("Closing le door")
        arena.run_command("close", "left_end_door", None, False)

    def open_door_re(self):
        self.log.info("Opening re door")
        arena.run_command("open", "right_end_door", None, False)

    def close_door_re(self):
        self.log.info("Closing re door")
        arena.run_command("close", "right_end_door", None, False)

    def respond(self):
        arena.run_command("toggle", "SSR")
        self.log.info("Testing Response")
        session_state["pin"] = [True if not session_state["pin"] else False][0]

    def feed(self):
        if not session_state["feeder_count"] == 0:
            arena.run_command("dispense", "left_feeder", None, False)
            self.log.info("fed")
            session_state["feeder_count"] = session_state["feeder_count"] - 1
        else:
            self.log.info("No more food")
    
    def on_detection(self, det):
        # det structure depends on your collector; start by printing it:
        if self.print_all:
            self.log.info(f"YOLO detection: {det}")

        # Below assumes det is a dict with keys; adjust once you see the print.
        # Example for a dict like:
        #   {"label": "person", "score": 0.87, "bbox": [x1, y1, x2, y2]}
        label = det.get("label")
        score = float(det.get("score", 0.0))
        x1, y1, x2, y2 = det.get("bbox", [None, None, None, None])

        ts = time.time()

        if hasattr(self, "_csv_writer"):
            self._csv_writer.writerow(
                [ts, self.obs_id, label, score, x1, y1, x2, y2]
            )
            self._csv_file.flush()

    def run(self):
        self.log.info("### ENTERED run() of yolo_detector_exp ###")
        """Start the detection test"""
        params = exp.get_params()
        self.obs_id = params['obs_id']
        self.obs = vid.image_observers[self.obs_id]
        self.detection_threshold = params.get("detection_threshold", 0.5)
        self.print_all = params.get("print_all", False)

        data_dir = exp.session_state["data_dir"]   # this is the session folder
        self.detections_path = data_dir / "yolo_detections.csv"
        self._csv_file = open(self.detections_path, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)

        self._csv_writer.writerow(
            ["timestamp", "obs_id", "label", "score", "x1", "y1", "x2", "y2"]
        )
        self._csv_file.flush()

        # Start the observer

        self.bbox_collector.start(self.on_detection)
        # arena.run_command("set_value", "ssr1", [1])
        # session_state["pin"] = True
        self.log.info(f"Starting YOLO test with confidence threshold {params['detection_threshold']}")

    def end(self):
        """Clean up"""
        if hasattr(self, "obslog"):
            self.obslog.stop()

        if hasattr(self, "bbox_collector") and self.bbox_collector is not None:
            self.bbox_collector.stop()

        params = exp.get_params()
        if hasattr(self, "_csv_file") and not self._csv_file.closed:
            self._csv_file.close()

        if hasattr(self, 'remove_listener'):
            self.remove_listener()

    # def on_detection(self, data, timestamp):
    #     """Handle each detection"""
    #     self.detection_count += 1
    #
    #     # Calculate time since last detection
    #     if self.last_timestamp is not None:
    #         time_delta = timestamp - self.last_timestamp
    #     else:
    #         time_delta = None
    #     self.last_timestamp = timestamp
    #
    #     # Only log if we have a valid detection
    #     if not np.any(np.isnan(data)):
    #         bbox_coords = data[:4]  # First 4 values are bbox coordinates
    #         confidence = data[4]  # Last value is confidence
    #
    #         # Log every detection if print_all is True
    #         if exp.get_params()["print_all"]:
    #             self.log.info(
    #                 f"Detection #{self.detection_count}\n"
    #                 f"Location: {bbox_coords}\n"
    #                 f"Confidence: {confidence:.3f}\n"
    #                 f"Timestamp: {timestamp}\n"
    #                 f"Time since last: {time_delta}"
    #             )
    #         # Otherwise just periodic summary
    #         elif self.detection_count % 100 == 0:
    #             self.log.info(
    #                 f"Processed {self.detection_count} frames\n"
    #                 f"Latest detection - Confidence: {confidence:.3f}, Location: {bbox_coords}"
    #             )
    #         self.respond()
    #         self.log.info("responding on detection")


    def run_trial(self):
        """Start a new trial"""
        self.log.info("Starting new detection trial")
        self.detection_count = 0
        self.last_timestamp = None

    def end_trial(self):
        """End the trial"""
        self.log.info(f"Trial ended. Processed {self.detection_count} total frames")