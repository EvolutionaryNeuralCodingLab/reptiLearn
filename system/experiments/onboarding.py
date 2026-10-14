import arena
import bbox
import experiment as exp
import numpy as np
import video_system as vid
from experiment import session_state
from health.heartbeat import (
    note_bbox_frame,
    note_bbox_listener_attached,
    note_zone_event,
)
from image_observers.yolo_bbox_detector import BBoxDataCollector


class MagnetoreceptionOnboarding(exp.Experiment):
    """
    Automatic magnetoreception onboarding loop for a new animal.

    Cycle (repeats while the onboarding runs):
    - Point A: open both back doors
    - Point B1/B2: close both back doors
    - Point C1/C2: open front door on the C side that the animal entered, go to D
    - Point D: close front door, return to A

    Zone params use normalized coordinates in [0, 1]:
    - Circle: location [cx, cy] and radius (fraction of min(image width, height))
    - Rectangle: location [x1, y1, x2, y2] (centroid must be inside the box)

    Starting or stopping does not move the doors. Stopping and starting again
    resumes the same phase and trial. Manual "Restart Cycle" returns to
    waiting at A and does not reset the trial number.
    """

    default_params = {
        "bbox_obs_id": "1",
        "image_source_id": "top",
        "point_a": {"location": [0.42, 0.45, 0.59, 0.72]},
        "point_b1": {"location": [0.74, 0.05, 0.92, 0.42]},
        "point_b2": {"location": [0.07, 0.05, 0.24, 0.42]},
        "point_c1": {"location": [0.77, 0.42, 0.92, 0.76]},
        "point_c2": {"location": [0.07, 0.42, 0.24, 0.76]},
        "point_d": {"location": [0.44, 0.75, 0.57, 1]},
        "zone_confirm_frames": 15,
        "zone_confirm_seconds": 0.5,
        "centroid_smoothing_alpha": 0.3,
    }

    def _restore_from_session(self, key, default):
        if key not in session_state:
            return default
        value = session_state[key]
        return default if value is None else value

    def setup(self):
        self.bbox_collector = None
        self.in_zones = set()
        self.zone_counts = {}
        self.zone_first_seen = {}
        self.smoothed_centroid = None

        self.phase = self._restore_from_session("onboarding_phase", "a")
        self.trial_num = self._restore_from_session("onboarding_trial", 0)
        self.c_side = self._restore_from_session("onboarding_c_side", None)
        self.c_entry_handled = self._restore_from_session(
            "onboarding_c_entry_handled", False
        )
        self.d_entry_handled = self._restore_from_session(
            "onboarding_d_entry_handled", False
        )

        self.actions["Reset Baseline"] = {"run": self.set_baseline}
        self.actions["Open Left Door"] = {"run": self.open_left_door}
        self.actions["Close Left Door"] = {"run": self.close_left_door}
        self.actions["Open Right Door"] = {"run": self.open_right_door}
        self.actions["Close Right Door"] = {"run": self.close_right_door}
        self.actions["Open Back Doors"] = {"run": self.open_back_doors}
        self.actions["Close Back Doors"] = {"run": self.close_back_doors}
        self.actions["Restart Cycle"] = {"run": self.restart_cycle}

        self._sync_session_state()


    def run(self):
        self.log.info(
            "Starting onboarding cycle (automatic A -> B -> C -> D loop)"
        )
        self._log_event("magnetoreception/onboarding_start", {})

        if self.trial_num > 0 or self.phase != "a":
            self.log.info(
                f"Resuming experiment at phase '{self.phase}', trial {self.trial_num}"
            )
            self._log_event(
                "magnetoreception/experiment_resume",
                {
                    "phase": self.phase,
                    "trial": self.trial_num,
                    "c_side": self.c_side,
                },
            )
        else:
            self.log.info(
                "Waiting for animal at point A to start (arena unchanged)"
            )
            self._log_event(
                "magnetoreception/waiting_at_a",
                {"trial": self.trial_num},
            )

        self.in_zones = set()
        self.smoothed_centroid = None
        self.zone_counts = {}
        self.zone_first_seen = {}
        self._sync_session_state()
        self._start_bbox_listener()

    def _start_bbox_listener(self):
        """Attach (or re-attach) the bbox zone listener to the current observer."""
        self._cleanup_bbox()
        params = exp.get_params()
        obs_id = params.get("bbox_obs_id", "1")
        try:
            self.bbox_collector = BBoxDataCollector(obs_id)
            self.bbox_collector.start(self.on_bbox_detection)
            note_bbox_listener_attached(session_state, obs_id)
            self.log.info(
                f"BBox-driven state machine active on observer '{obs_id}'. "
                "Configure point_a/b1/b2/c1/c2/d with normalized zones."
            )
        except ValueError as e:
            self.log.warning(f"BBox listener not started ({e}). Arena actions still available.")

    def on_video_restart(self):
        self.log.warning(
            "Video restarted while onboarding is running; "
            "re-attaching bbox zone listener."
        )
        self._start_bbox_listener()

    def end(self):
        self.log.info("Ending onboarding cycle")
        self._log_event(
            "magnetoreception/onboarding_end",
            {"trial": self.trial_num, "phase": self.phase},
        )
        self._cleanup_bbox()
        self._sync_session_state()

    def release(self):
        self._cleanup_bbox()

    def restart_cycle(self):
        self.phase = "a"
        self.c_side = None
        self.c_entry_handled = False
        self.d_entry_handled = False
        self.in_zones = set()
        self._sync_session_state()
        self.log.info("Waiting for animal at point A to start next cycle")
        self._log_event(
            "magnetoreception/waiting_at_a",
            {"trial": self.trial_num},
        )

    def _cleanup_bbox(self):
        if self.bbox_collector is not None:
            try:
                self.bbox_collector.stop()
            finally:
                self.bbox_collector = None

    def _sync_session_state(self):
        session_state["onboarding_phase"] = self.phase
        session_state["onboarding_trial"] = self.trial_num
        session_state["onboarding_c_side"] = self.c_side
        session_state["onboarding_c_entry_handled"] = self.c_entry_handled
        session_state["onboarding_d_entry_handled"] = self.d_entry_handled

    def _log_event(self, event, value=None):
        if exp.event_logger is not None:
            exp.event_logger.log(event, value)
        note_zone_event(session_state, event)

    def on_bbox_detection(self, det, timestamp):
        note_bbox_frame(session_state)
        w, h, min_dim = self._image_geometry()
        raw_centroid = self._centroid_pixels(det, w, h)

        if raw_centroid is None:
            self.in_zones = set()
            self.smoothed_centroid = None
            self.zone_counts = {}
            self.zone_first_seen = {}
            return

        alpha = exp.get_params().get("centroid_smoothing_alpha", 0.3)

        if self.smoothed_centroid is None:
            self.smoothed_centroid = raw_centroid
        else:
            self.smoothed_centroid = (
                alpha * raw_centroid[0] + (1 - alpha) * self.smoothed_centroid[0],
                alpha * raw_centroid[1] + (1 - alpha) * self.smoothed_centroid[1],
            )

        centroid = self.smoothed_centroid

        raw_zones = self._zones_at(centroid, w, h, min_dim)
        params = exp.get_params()
        min_frames = params.get("zone_confirm_frames", 15)
        min_seconds = params.get("zone_confirm_seconds", 0.5)

        confirmed_zones = set()

        for zone in raw_zones:
            if zone not in self.zone_counts:
                self.zone_counts[zone] = 0
                self.zone_first_seen[zone] = timestamp

            self.zone_counts[zone] += 1

            dwell_time = timestamp - self.zone_first_seen[zone]

            if hasattr(dwell_time, "total_seconds"):
                dwell_time = dwell_time.total_seconds()

            if self.zone_counts[zone] >= min_frames and dwell_time >= min_seconds:
                confirmed_zones.add(zone)

        for zone in list(self.zone_counts.keys()):
            if zone not in raw_zones:
                self.zone_counts.pop(zone, None)
                self.zone_first_seen.pop(zone, None)

        entered = confirmed_zones - self.in_zones

        expected_zones = {
            "a": {"A"},
            "b": {"B1", "B2"},
            "c": {"C1", "C2"},
            "d": {"D"},
        }

        wrong_zones = entered - expected_zones.get(self.phase, set())
        if self.phase == "d":
            wrong_zones -= {"A", "D"}

        if wrong_zones:
            self.log.info(
                f"Animal detected at {wrong_zones}, but current phase is '{self.phase}' "
                f"and expected zones are {expected_zones.get(self.phase, set())}"
            )
            self._log_event(
                "magnetoreception/wrong_zone",
                {
                    "trial": self.trial_num,
                    "phase": self.phase,
                    "zones": sorted(wrong_zones),
                    "expected": sorted(expected_zones.get(self.phase, set())),
                },
            )

        self.in_zones = confirmed_zones

        if self.phase == "a" and "A" in entered:
            self._try_start_trial_at_a()
        elif self.phase == "b" and entered.intersection({"B1", "B2"}):
            side = "B1" if "B1" in entered else "B2"
            self._on_point_b(side)
        elif self.phase == "c" and not self.c_entry_handled:
            entered_c = entered.intersection({"C1", "C2"})
            if entered_c:
                side = "C1" if "C1" in entered_c else "C2"
                self._on_point_c(side)
        elif self.phase == "d" and not self.d_entry_handled:
            if "D" in entered:
                self._on_point_d()
                if "A" in confirmed_zones:
                    self._try_start_trial_at_a()
            elif "A" in confirmed_zones:
                self._on_point_d(via_a_before_d=True)
                self._try_start_trial_at_a()

    def _try_start_trial_at_a(self):
        self._on_point_a()

    def _on_point_a(self):
        self.d_entry_handled = False
        self.trial_num += 1
        self._sync_session_state()

        self.close_left_door()
        self.close_right_door()
        self.open_back_doors()

        self.log.info(f"Trial {self.trial_num}: at point A, both back doors open")

        self.phase = "b"
        self._sync_session_state()
        self._log_event(
            "magnetoreception/trial_start",
            {
                "trial": self.trial_num,
                "zone": "A",
                "phase": self.phase,
                "back_doors": "both_open",
            },
        )

    def _on_point_b(self, side):
        self.log.info(f"Trial {self.trial_num}: at {side}, closing both back doors")
        self.close_back_doors()

        self.phase = "c"
        self._sync_session_state()
        self._log_event(
            "magnetoreception/point_b",
            {"trial": self.trial_num, "zone": side},
        )
        self._log_event(
            "magnetoreception/phase_change",
            {"trial": self.trial_num, "phase": self.phase},
        )

    def _on_point_c(self, side):
        self.c_entry_handled = True
        self.c_side = side
        self.close_left_door()
        self.close_right_door()

        door = "right" if side == "C1" else "left"
        self.log.info(
            f"Trial {self.trial_num}: at {side} -> opening {door} front door"
        )
        if side == "C1":
            self.open_right_door()
        else:
            self.open_left_door()

        self.phase = "d"
        self._sync_session_state()
        self._log_event(
            "magnetoreception/point_c",
            {
                "trial": self.trial_num,
                "zone": side,
                "door_opened": door,
            },
        )


    def _on_point_d(self, via_a_before_d=False):
        if self.c_side == "C1":
            if via_a_before_d:
                self.log.info(
                    f"Trial {self.trial_num}: at A before D detected -> "
                    "close right front door"
                )
            else:
                self.log.info(
                    f"Trial {self.trial_num}: at D -> close right front door"
                )
            self.close_right_door()
        elif self.c_side == "C2":
            if via_a_before_d:
                self.log.info(
                    f"Trial {self.trial_num}: at A before D detected -> "
                    "close left front door"
                )
            else:
                self.log.info(
                    f"Trial {self.trial_num}: at D -> close left front door"
                )
            self.close_left_door()
        else:
            self.log.info(f"Trial {self.trial_num}: at D -> close front doors")
            self.close_left_door()
            self.close_right_door()

        self.d_entry_handled = True
        self.phase = "a"
        self.c_entry_handled = False
        self.c_side = None
        self.in_zones = set()
        self._sync_session_state()
        self._log_event(
            "magnetoreception/point_d",
            {
                "trial": self.trial_num,
                "c_side": self.c_side,
                "via_a_before_d": via_a_before_d,
            },
        )
        if via_a_before_d:
            self._log_event(
                "magnetoreception/point_d_via_a",
                {"trial": self.trial_num},
            )
        else:
            self.log.info(f"Trial {self.trial_num}: waiting for point A to start next trial")
            self._log_event(
                "magnetoreception/waiting_at_a",
                {"trial": self.trial_num},
            )

    def _zones_at(self, centroid, w, h, min_dim):
        params = exp.get_params()
        zone_defs = {
            "A": params["point_a"],
            "B1": params["point_b1"],
            "B2": params["point_b2"],
            "C1": params["point_c1"],
            "C2": params["point_c2"],
            "D": params["point_d"],
        }
        return {
            name
            for name, zone in zone_defs.items()
            if self._in_zone(centroid, zone, w, h, min_dim)
        }

    def _image_geometry(self):
        src_id = exp.get_params()["image_source_id"]
        img, _ = vid.image_sources[src_id].get_image()
        h, w = img.shape[:2]
        return w, h, min(w, h)

    def _in_zone(self, centroid, zone, w, h, min_dim):
        cx, cy = centroid
        loc = zone["location"]

        if len(loc) == 4:
            x1, y1, x2, y2 = loc
            x1, x2 = x1 * w, x2 * w
            y1, y2 = y1 * h, y2 * h
            xmin, xmax = min(x1, x2), max(x1, x2)
            ymin, ymax = min(y1, y2), max(y1, y2)
            return xmin <= cx <= xmax and ymin <= cy <= ymax

        lx, ly = loc[0] * w, loc[1] * h
        radius = zone["radius"] * min_dim
        return (cx - lx) ** 2 + (cy - ly) ** 2 <= radius ** 2

    def _centroid_pixels(self, det, w, h):
        if det is None or len(det) < 4 or np.any(np.isnan(det[:4])):
            return None

        x1, y1, x2, y2 = det[:4]
        x1, x2 = x1 * w, x2 * w
        y1, y2 = y1 * h, y2 * h

        return tuple(bbox.xyxy_to_centroid(np.array([x1, y1, x2, y2])))

    def set_baseline(self):
        """Back doors open, front doors closed."""
        self.log.info("Setting baseline arena state")
        self.close_left_door()
        self.close_right_door()
        self.open_back_doors()

    def open_left_door(self):
        arena.run_command("open", "Left Door", None, False)

    def close_left_door(self):
        arena.run_command("close", "Left Door", None, False)

    def open_right_door(self):
        arena.run_command("open", "Right Door", None, False)

    def close_right_door(self):
        arena.run_command("close", "Right Door", None, False)

    def open_right_back_door(self):
        arena.run_command("open", "Back Door Right", None, False)

    def close_right_back_door(self):
        arena.run_command("close", "Back Door Right", None, False)

    def open_left_back_door(self):
        arena.run_command("open", "Back Door Left", None, False)

    def close_left_back_door(self):
        arena.run_command("close", "Back Door Left", None, False)

    def open_back_doors(self):
        self.open_right_back_door()
        self.open_left_back_door()

    def close_back_doors(self):
        self.close_right_back_door()
        self.close_left_back_door()
