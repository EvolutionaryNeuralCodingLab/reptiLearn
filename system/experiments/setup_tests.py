import experiment as exp
from experiment import session_state
import arena
import video_system as vid
import schedule
import time

from image_observers.yolo_bbox_detector import BBoxDataCollector


class SetupTestsExperiment(exp.Experiment):
    """
    Experiment for testing and controlling arena components:
    - Magnets (forward, reverse, stop)
    - Feeders (left and right)
    - Doors (left, right, back doors)
    - Camera and video recording
    - Optional bbox CSV from a configured image observer (see default_params)
    """

    default_params = {
        "test_duration_sec": 25,  # Duration for timed tests
        "bbox_obs_id": "1",  # ImageObserver id for BBoxDataCollector CSV
        "log_bbox_csv": True,
    }

    def setup(self):
        """Initialize the experiment and register actions"""
        self.log.info("Setting up arena and video control experiment")

        # Register magnet control actions
        self.actions["Magnets Forward"] = {"run": self.magnets_forward}
        self.actions["Magnets Reverse"] = {"run": self.magnets_reverse}
        self.actions["Magnets Stop"] = {"run": self.magnets_stop}

        # Timed magnet blocks (forward / reverse with automatic doors & feeders)
        self.actions["Start Forward Block"] = {"run": self.start_forward_block}
        self.actions["Start Reverse Block"] = {"run": self.start_reverse_block}

        # Register feeder control actions
        self.actions["Dispense Left Feeder"] = {"run": self.dispense_left_feeder}
        self.actions["Dispense Right Feeder"] = {"run": self.dispense_right_feeder}

        # Register door control actions
        self.actions["Open Left Door"] = {"run": self.open_left_door}
        self.actions["Close Left Door"] = {"run": self.close_left_door}
        self.actions["Open Right Door"] = {"run": self.open_right_door}
        self.actions["Close Right Door"] = {"run": self.close_right_door}
        # Individual back doors
        self.actions["Open Back Door Right"] = {"run": self.open_back_door_right}
        self.actions["Close Back Door Right"] = {"run": self.close_back_door_right}
        self.actions["Open Back Door Left"] = {"run": self.open_back_door_left}
        self.actions["Close Back Door Left"] = {"run": self.close_back_door_left}
        # Convenience actions to open/close both back doors together
        self.actions["Open Back Doors"] = {"run": self.open_back_doors}
        self.actions["Close Back Doors"] = {"run": self.close_back_doors}

        # Register video/camera control actions
        self.actions["Start Recording"] = {"run": self.start_recording}
        self.actions["Stop Recording"] = {"run": self.stop_recording}
        self.actions["Toggle Recording"] = {"run": self.toggle_recording}

        # Register test sequences
        self.actions["Test All Doors"] = {"run": self.test_all_doors}
        self.actions["Test All Feeders"] = {"run": self.test_all_feeders}
        self.actions["Test Magnets Sequence"] = {"run": self.test_magnets_sequence}

        self.bbox_collector = None

        self.log.info("Setup complete. All actions registered.")

    # ========== Magnet Control Methods ==========

    def magnets_forward(self):
        """Activate magnets in forward direction"""
        self.log.info("Activating magnets forward")
        arena.run_command("forward", "Magnets Forward", None, False)

    def magnets_reverse(self):
        """Activate magnets in reverse direction"""
        self.log.info("Activating magnets reverse")
        arena.run_command("reverse", "Magnets Reverse", None, False)

    def magnets_stop(self):
        """Stop magnets"""
        self.log.info("Stopping magnets")
        arena.run_command("stop", "Magnets Stop", None, False)

    # ----- Timed magnet blocks -----

    def start_forward_block(self):
        """
        Start a 25s block with forward magnets:
        - t=0s: magnets forward
        - t=5s: open both back doors
        - t=10s: close both back doors
        - t=15s: right feeder dispense
        - t=20s: stop magnets, open left door
        """
        self._start_magnet_block(direction="forward")

    def start_reverse_block(self):
        """
        Start a 25s block with reverse magnets:
        - t=0s: magnets reverse
        - t=5s: open both back doors
        - t=10s: close both back doors
        - t=15s: left feeder dispense
        - t=20s: stop magnets, open right door
        """
        self._start_magnet_block(direction="reverse")

    def _start_magnet_block(self, direction: str):
        """
        Common logic for a timed magnet block.

        Magnets are on for 20s inside a 25s block window.
        Other components follow the timing spec relative to t=0.
        """
        # Cancel any previous scheduled steps for this experiment
        try:
            schedule.cancel_all(pool="experiment_phases")
        except ValueError:
            # No schedules yet for this pool
            pass

        self.log.info(f"Starting {direction} magnet block (25s total, 20s magnets on)")

        # t = 0s: activate magnets
        if direction == "forward":
            self.magnets_forward()
        else:
            self.magnets_reverse()

        # t = 5s: open back doors (right & left)
        schedule.once(self._open_back_doors_both, 5, pool="experiment_phases")

        # t = 10s: close back doors
        schedule.once(self._close_back_doors_both, 10, pool="experiment_phases")

        # t = 15s: feeders (right for forward, left for reverse)
        if direction == "forward":
            schedule.once(self.dispense_right_feeder, 15, pool="experiment_phases")
        else:
            schedule.once(self.dispense_left_feeder, 15, pool="experiment_phases")

        # t = 20s: stop magnets
        schedule.once(self.magnets_stop, 20, pool="experiment_phases")

        # t = 25s: just log block end
        schedule.once(self._log_block_end, 25, pool="experiment_phases")

    def _open_back_doors_both(self):
        """Helper: open both back doors together."""
        self.log.info("Opening back doors")
        self.open_back_doors()

    def _close_back_doors_both(self):
        """Helper: close both back doors together."""
        self.log.info("Closing back doors")
        self.close_back_doors()

    def _log_block_end(self):
        """Helper: log end of the 25s block window."""
        self.log.info("Magnet block window (25s) finished")

    # ========== Feeder Control Methods ==========

    def dispense_left_feeder(self):
        """Dispense food from left feeder"""
        self.log.info("Dispensing from left feeder")
        arena.run_command("dispense", "Left Feeder", None, False)

    def dispense_right_feeder(self):
        """Dispense food from right feeder"""
        self.log.info("Dispensing from right feeder")
        arena.run_command("dispense", "Right Feeder", None, False)

    # ========== Door Control Methods ==========

    def open_left_door(self):
        """Open the left door"""
        self.log.info("Opening left door")
        arena.run_command("open", "Left Door", None, False)

    def close_left_door(self):
        """Close the left door"""
        self.log.info("Closing left door")
        arena.run_command("close", "Left Door", None, False)

    def open_right_door(self):
        """Open the right door"""
        self.log.info("Opening right door")
        arena.run_command("open", "Right Door", None, False)

    def close_right_door(self):
        """Close the right door"""
        self.log.info("Closing right door")
        arena.run_command("close", "Right Door", None, False)

    def open_back_door_right(self):
        """Open the back door right"""
        self.log.info("Opening Back Door Right")
        arena.run_command("open", "Back Door Right", None, False)

    def close_back_door_right(self):
        """Close the back door right"""
        self.log.info("Closing Back Door Right")
        arena.run_command("close", "Back Door Right", None, False)

    def open_back_door_left(self):
        """Open the back door left"""
        self.log.info("Opening Back Door Left")
        arena.run_command("open", "Back Door Left", None, False)

    def close_back_door_left(self):
        """Close the back door left"""
        self.log.info("Closing Back Door Left")
        arena.run_command("close", "Back Door Left", None, False)

    def open_back_doors(self):
        """Open both back doors together"""
        self.log.info("Opening both back doors")
        self.open_back_door_right()
        self.open_back_door_left()

    def close_back_doors(self):
        """Close both back doors together"""
        self.log.info("Closing both back doors")
        self.close_back_door_right()
        self.close_back_door_left()

    # ========== Video/Camera Control Methods ==========

    def start_recording(self):
        """Start video recording"""
        self.log.info("Starting video recording")
        session_state["video", "record", "is_recording"] = True
        # Trigger camera if available
        if arena.has_trigger():
            arena.start_trigger()

    def stop_recording(self):
        """Stop video recording"""
        self.log.info("Stopping video recording")
        session_state["video", "record", "is_recording"] = False
        # Stop camera trigger if available
        if arena.has_trigger():
            arena.stop_trigger()

    def toggle_recording(self):
        """Toggle video recording state"""
        current_state = session_state.get(("video", "record", "is_recording"), default=False)
        if current_state:
            self.stop_recording()
        else:
            self.start_recording()

    # ========== Test Sequence Methods ==========

    def test_all_doors(self):
        """Test sequence: open and close all doors"""
        self.log.info("Starting door test sequence")
        params = exp.get_params()
        duration = params.get("test_duration_sec", 5)

        # Open all doors
        self.log.info("Opening all doors...")
        self.open_left_door()
        time.sleep(0.5)
        self.open_right_door()
        time.sleep(0.5)
        self.open_back_doors()

        # Wait
        self.log.info(f"Waiting {duration} seconds...")
        time.sleep(duration)

        # Close all doors
        self.log.info("Closing all doors...")
        self.close_left_door()
        time.sleep(0.5)
        self.close_right_door()
        time.sleep(0.5)
        self.close_back_doors()

        self.log.info("Door test sequence complete")

    def test_all_feeders(self):
        """Test sequence: dispense from all feeders"""
        self.log.info("Starting feeder test sequence")
        
        # Dispense from left feeder
        self.log.info("Testing left feeder...")
        self.dispense_left_feeder()
        time.sleep(2)

        # Dispense from right feeder
        self.log.info("Testing right feeder...")
        self.dispense_right_feeder()
        time.sleep(2)

        self.log.info("Feeder test sequence complete")

    def test_magnets_sequence(self):
        """Test sequence: forward -> stop -> reverse -> stop"""
        self.log.info("Starting magnets test sequence")
        params = exp.get_params()
        duration = params.get("test_duration_sec", 5)

        # Forward
        self.log.info("Testing magnets forward...")
        self.magnets_forward()
        time.sleep(duration)

        # Stop
        self.log.info("Stopping magnets...")
        self.magnets_stop()
        time.sleep(5)

        # Reverse
        self.log.info("Testing magnets reverse...")
        self.magnets_reverse()
        time.sleep(duration)

        # Stop
        self.log.info("Stopping magnets...")
        self.magnets_stop()

        self.log.info("Magnets test sequence complete")

    def run(self):
        """Main experiment run method"""
        self.log.info("Setup Tests Experiment is running")
        self.log.info("Use the registered actions to control arena components and video")

        params = exp.get_params()
        if params.get("log_bbox_csv", True):
            self._start_bbox_csv()

    def _start_bbox_csv(self):
        self._cleanup_bbox_csv()
        params = exp.get_params()
        obs_id = params.get("bbox_obs_id", "1")
        try:
            self.bbox_collector = BBoxDataCollector(obs_id)
            self.bbox_collector.start()
            self.log.info(
                f"BBox/pose CSV logging active for observer '{obs_id}' in "
                f"{session_state['data_dir']} (split_csv: files named {obs_id}_*.csv). "
                "Live overlays keep running when the experiment stops; only this log stops."
            )
        except ValueError as e:
            self.log.warning(
                f"BBox CSV logging skipped ({e}). "
                "Set params bbox_obs_id or disable with log_bbox_csv: false."
            )

    def on_video_restart(self):
        if not exp.get_params().get("log_bbox_csv", True):
            return
        if self.bbox_collector is None:
            return
        self.log.warning(
            "Video restarted while setup_tests is running; re-attaching bbox CSV logger."
        )
        self._start_bbox_csv()

    def _cleanup_bbox_csv(self):
        """BBoxDataCollector is started in run(); close_session() calls release() not end()."""
        if self.bbox_collector is not None:
            try:
                self.bbox_collector.stop()
            finally:
                self.bbox_collector = None

    def end(self):
        """Cleanup when experiment ends"""
        self.log.info("Ending Setup Tests Experiment")

        self._cleanup_bbox_csv()

        # Stop magnets if running
        self.magnets_stop()
        
        # Stop recording if active
        if session_state.get(("video", "record", "is_recording"), default=False):
            self.stop_recording()

    def release(self):
        """Called when the session is closed; always stop bbox logging if it was started."""
        self._cleanup_bbox_csv()
