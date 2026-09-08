import random
import time

import arena
import bbox
import experiment as exp
import numpy as np
import schedule
import video_system as vid
from experiment import session_state
from health.heartbeat import (
    note_bbox_frame,
    note_bbox_listener_attached,
    note_zone_event,
)
from image_observers.yolo_bbox_detector import BBoxDataCollector


class MagnetoreceptionTrainingExperiment(exp.Experiment):
    """
    Automatic training experiment for magnetic field orientation driven by bbox location.

    Right baseline state:
    - Right back door: open
    - Left back door: closed
    - Front doors: closed
    - Magnetic field: off

    Left baseline state:
    - Right back door: closed
    - Left back door: open
    - Front doors: closed
    - Magnetic field: off

    Cycle (repeats while the experiment runs):
    - Point A: shuffled trial type — forward, reverse, conflict_right, or conflict_left
    - If forward:
        - Point B1: close right back door; dispense right feeder.
        - Point C1: dwell at C with doors closed and magnets on.
        - After dwell: magnets off, open same-side front door, go to D.
        - Point D: close front door; return to A.
        - Point A: start new trial (magnets turn on only after a minimum off gap since C dwell).
        - If A is detected before D while en route from C, D door-close and A trial start
          are applied together (still respecting the magnet off-to-on gap).
    - If conflict_right / conflict_left (magnet opposes open door, no feeder):
        - Point A: one back door open (right or left) with magnets in the opposite direction.
        - Correct B side (door side): no feeder; C dwell with magnets on; then C/D as usual.
    - If reverse:
        - Point B2: close left back door; dispense left feeder.
        - Point C2: dwell at C with doors closed and magnets on.
        - After dwell: magnets off, open same-side front door, go to D.
        - Point D: close front door; return to A.
    
    Zone params use normalized coordinates in [0, 1]:
    - Circle: location [cx, cy] and radius (fraction of min(image width, height))
    - Rectangle: location [x1, y1, x2, y2] (centroid must be inside the box)

    Bbox detections are converted with the current frame size on each update.

    Starting or stopping the experiment does not reset the arena to baseline.
    Stopping and restarting the experiment resumes the same phase and trial within
    a session. Manual "Reset Baseline" and "Restart Cycle" are still available.

    Each session runs a fixed shuffled block: trials_per_direction forward,
    trials_per_direction reverse, and conflict_trials_per_side each of conflict_right
    and conflict_left (opposite magnet vs door, no feeder at B). Default block is
    20+20+10+10=60 trials. The block ends after the last full A->B->C->D cycle.

    random_seed: optional int; if omitted, seeded from session data_dir for
    reproducible shuffled schedules within a session.
    """

    default_params = {
        "bbox_obs_id": "1",
        "image_source_id": "top",
        "point_a": {"location": [0.42, 0.2, 0.59, 0.72]},
        "point_b1": {"location": [0.74, 0.05, 0.92, 0.42]},
        "point_b2": {"location": [0.07, 0.05, 0.24, 0.42]},
        "point_c1": {"location": [0.77, 0.42, 0.92, 0.76]},
        "point_c2": {"location": [0.07, 0.42, 0.24, 0.76]},
        "point_d": {"location": [0.44, 0.75, 0.57, 1]},
        "zone_confirm_frames": 15,
        "zone_confirm_seconds": 0.5,
        "centroid_smoothing_alpha": 0.3,
        "feeder_dispense_limit": 15,
        "feeder_stop_total_limit": 30,
        "point_c_dwell_seconds": 10,
        "magnet_off_to_on_min_seconds": 5,
        "trials_per_direction": 20,
        "conflict_trials_per_side": 10,
        "random_seed": None,
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
        self._a_start_scheduled = False
        self.trial_schedule = None
        self.schedule_seed = None

        self.phase = self._restore_from_session("magnetoreception_phase", "a")
        self.magnet_direction = self._restore_from_session(
            "magnetoreception_magnet_direction", None
        )
        self.trial_num = self._restore_from_session("magnetoreception_trial", 0)
        self.cycle_side = self._restore_from_session("cycle_side", None)
        self.c_dwell_complete = self._restore_from_session(
            "magnetoreception_c_dwell_complete", True
        )
        self.right_feeder_1_dispense_count = self._restore_from_session(
            "magnetoreception_right_feeder_1_dispense_count", 0
        )
        self.left_feeder_1_dispense_count = self._restore_from_session(
            "magnetoreception_left_feeder_1_dispense_count", 0
        )
        self.right_feeder_2_dispense_count = self._restore_from_session(
            "magnetoreception_right_feeder_2_dispense_count", 0
        )
        self.left_feeder_2_dispense_count = self._restore_from_session(
            "magnetoreception_left_feeder_2_dispense_count", 0
        )
        self.b_trials_count = self._restore_from_session(
            "magnetoreception_b_trials_count", 0
        )
        self.success_count = self._restore_from_session(
            "magnetoreception_success_count", 0
        )
        self.success_right_count = self._restore_from_session(
            "magnetoreception_success_right_count", 0
        )
        self.success_left_count = self._restore_from_session(
            "magnetoreception_success_left_count", 0
        )
        self.c_side = self._restore_from_session("magnetoreception_c_side", None)
        self.c_entry_handled = self._restore_from_session(
            "magnetoreception_c_entry_handled", False
        )
        self.d_entry_handled = self._restore_from_session(
            "magnetoreception_d_entry_handled", False
        )
        self.magnets_off_time = self._restore_from_session(
            "magnetoreception_magnets_off_time", None
        )
        self.c_dwell_end_time = self._restore_from_session(
            "magnetoreception_c_dwell_end_time", None
        )
        self.trial_schedule = self._restore_from_session(
            "magnetoreception_trial_schedule", None
        )
        self.schedule_seed = self._restore_from_session(
            "magnetoreception_schedule_seed", None
        )

        self.actions["Reset Baseline"] = {"run": self.set_baseline}
        self.actions["Magnets Forward"] = {"run": self.magnets_forward}
        self.actions["Magnets Reverse"] = {"run": self.magnets_reverse}
        self.actions["Magnets Stop"] = {"run": self.magnets_stop}
        self.actions["Dispense Left Feeder"] = {"run": self.dispense_left_feeder}
        self.actions["Dispense Right Feeder"] = {"run": self.dispense_right_feeder}
        self.actions["Open Left Door"] = {"run": self.open_left_door}
        self.actions["Close Left Door"] = {"run": self.close_left_door}
        self.actions["Open Right Door"] = {"run": self.open_right_door}
        self.actions["Close Right Door"] = {"run": self.close_right_door}
        self.actions["Open Back Doors"] = {"run": self.open_back_doors}
        self.actions["Close Back Doors"] = {"run": self.close_back_doors}
        self.actions["Restart Cycle"] = {"run": self.restart_cycle}

        self._sync_session_state()

    def _magnet_trials_per_direction(self):
        return int(exp.get_params().get("trials_per_direction", 20))

    def _conflict_trials_per_side(self):
        return int(exp.get_params().get("conflict_trials_per_side", 10))

    def _conflict_trials(self):
        return 2 * self._conflict_trials_per_side()

    def _magnets_on_for_direction(self, direction=None):
        direction = direction if direction is not None else self.magnet_direction
        return direction in ("forward", "reverse", "conflict_right", "conflict_left")

    def _total_trials(self):
        return 2 * self._magnet_trials_per_direction() + self._conflict_trials()

    def _get_schedule_seed(self):
        params = exp.get_params()
        seed = params.get("random_seed")
        if seed is None:
            seed = hash(str(session_state["data_dir"])) & 0xFFFFFFFF
        else:
            seed = int(seed)
        return int(seed)

    def _init_trial_schedule(self):
        total = self._total_trials()
        per_dir = self._magnet_trials_per_direction()
        conflict_per_side = self._conflict_trials_per_side()
        existing = self.trial_schedule

        if existing is not None and len(existing) == total:
            self.log.info(
                f"Using existing trial schedule ({total} trials, seed={self.schedule_seed})"
            )
            return

        seed = self._get_schedule_seed()
        random.seed(seed)
        schedule_list = (
            ["forward"] * per_dir
            + ["reverse"] * per_dir
            + ["conflict_right"] * conflict_per_side
            + ["conflict_left"] * conflict_per_side
        )
        random.shuffle(schedule_list)
        self.trial_schedule = schedule_list
        self.schedule_seed = seed
        self._sync_session_state()
        self.log.info(
            f"Generated shuffled trial schedule: {total} trials "
            f"({per_dir} forward, {per_dir} reverse, "
            f"{conflict_per_side} conflict_right, {conflict_per_side} conflict_left), "
            f"seed={seed}"
        )
        self._log_event("magnetoreception_training/random_seed", {"seed": seed})
        self._log_event(
            "magnetoreception_training/trial_schedule",
            {
                "seed": seed,
                "total_trials": total,
                "forward_count": per_dir,
                "reverse_count": per_dir,
                "conflict_right_count": conflict_per_side,
                "conflict_left_count": conflict_per_side,
                "schedule": schedule_list,
            },
        )

    def _next_trial_direction(self):
        return self._magnet_direction_for_trial(self.trial_num + 1)

    def _magnet_direction_for_trial(self, trial_num):
        return self.trial_schedule[trial_num - 1]

    def _complete_block(self):
        total = self._total_trials()
        self.log.info(f"Block complete: {total} trials finished")
        self._log_event(
            "magnetoreception_training/block_complete",
            {"trial": self.trial_num, "total_trials": total},
        )
        exp.stop_experiment()

    def _prepare_experiment_resume(self):
        self.in_zones = set()
        self.smoothed_centroid = None
        self.zone_counts = {}
        self.zone_first_seen = {}
        self._cancel_c_dwell_schedule()
        self._a_start_scheduled = False
        self._reconcile_arena_for_phase()
        self._rearm_pending_schedules()
        self._sync_session_state()

    def _reconcile_arena_for_phase(self):
        if self.phase == "b" and self.magnet_direction == "forward":
            self.magnets_forward()
            self.open_right_back_door()
        elif self.phase == "b" and self.magnet_direction == "reverse":
            self.magnets_reverse()
            self.open_left_back_door()
        elif self.phase == "b" and self.magnet_direction == "conflict_right":
            self.magnets_reverse()
            self.open_right_back_door()
        elif self.phase == "b" and self.magnet_direction == "conflict_left":
            self.magnets_forward()
            self.open_left_back_door()
        elif (
            self.phase == "c"
            and self.c_entry_handled
            and not self.c_dwell_complete
            and self.magnet_direction == "conflict_right"
        ):
            self.magnets_reverse()
        elif (
            self.phase == "c"
            and self.c_entry_handled
            and not self.c_dwell_complete
            and self.magnet_direction == "conflict_left"
        ):
            self.magnets_forward()
        elif (
            self.phase == "c"
            and self.c_entry_handled
            and not self.c_dwell_complete
            and self.magnet_direction == "forward"
        ):
            self.magnets_forward()
        elif (
            self.phase == "c"
            and self.c_entry_handled
            and not self.c_dwell_complete
            and self.magnet_direction == "reverse"
        ):
            self.magnets_reverse()

    def _rearm_pending_schedules(self):
        if self.trial_num >= self._total_trials():
            return

        if self.phase == "a" and self.magnets_off_time is not None:
            min_gap = exp.get_params().get("magnet_off_to_on_min_seconds", 5)
            elapsed = time.time() - self.magnets_off_time
            if elapsed < min_gap:
                remaining = min_gap - elapsed
                self._a_start_scheduled = True
                self.log.info(
                    f"Resuming magnet gap wait: {remaining:.1f}s before next trial at A"
                )
                schedule.once(
                    self._start_trial_after_magnet_gap,
                    remaining,
                    pool="experiment_phases",
                )

        if (
            self.phase == "c"
            and self.c_entry_handled
            and not self.c_dwell_complete
            and self.c_dwell_end_time is not None
        ):
            remaining = self.c_dwell_end_time - time.time()
            if remaining > 0:
                self.log.info(f"Resuming C dwell: {remaining:.1f}s remaining")
                schedule.once(
                    self._finish_c_dwell, remaining, pool="experiment_phases"
                )
            else:
                self._finish_c_dwell()

    def run(self):
        self.log.info(
            "Starting magnetoreception training (automatic A -> B -> C -> D loop)"
        )
        self._init_trial_schedule()
        self._log_event("magnetoreception_training/experiment_start", {})

        if self.trial_num >= self._total_trials():
            self._complete_block()
            return

        if self.trial_num > 0 or self.phase != "a":
            self.log.info(
                f"Resuming experiment at phase '{self.phase}', trial {self.trial_num}"
            )
            self._log_event(
                "magnetoreception_training/experiment_resume",
                {
                    "phase": self.phase,
                    "trial": self.trial_num,
                    "magnet_direction": self.magnet_direction,
                    "c_side": self.c_side,
                },
            )
        else:
            self.log.info("Waiting for animal at point A to start block (arena unchanged)")
            self._log_event(
                "magnetoreception/waiting_at_a",
                {"trial": self.trial_num},
            )

        self._prepare_experiment_resume()
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
                "Configure point_a/b1/b2/c1/c2 with normalized location [0-1] and radius."
            )
        except ValueError as e:
            self.log.warning(f"BBox listener not started ({e}). Arena actions still available.")

    def on_video_restart(self):
        self.log.warning(
            "Video restarted while magnetoreception_train is running; "
            "re-attaching bbox zone listener."
        )
        self._start_bbox_listener()

    def end(self):
        self.log.info("Ending magnetoreception training")
        self._log_event(
            "magnetoreception_training/experiment_end",
            {"trial": self.trial_num, "phase": self.phase},
        )
        self._cancel_c_dwell_schedule()
        self._cleanup_bbox()
        self.magnets_stop()
        self._sync_session_state()

    def release(self):
        self._cleanup_bbox()

    def restart_cycle(self):
        self._cancel_c_dwell_schedule()
        self.phase = "a"
        self.magnet_direction = None
        self.c_side = None
        self.c_entry_handled = False
        self.d_entry_handled = False
        self.c_dwell_complete = True
        self.magnets_off_time = None
        self.c_dwell_end_time = None
        self._a_start_scheduled = False
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
        session_state["magnetoreception_phase"] = self.phase
        session_state["magnetoreception_trial"] = self.trial_num
        session_state["cycle_side"] = self.cycle_side
        session_state["magnetoreception_magnet_direction"] = self.magnet_direction
        session_state["magnetoreception_right_feeder_1_dispense_count"] = (
            self.right_feeder_1_dispense_count
        )
        session_state["magnetoreception_left_feeder_1_dispense_count"] = (
            self.left_feeder_1_dispense_count
        )
        session_state["magnetoreception_right_feeder_2_dispense_count"] = (
            self.right_feeder_2_dispense_count
        )
        session_state["magnetoreception_left_feeder_2_dispense_count"] = (
            self.left_feeder_2_dispense_count
        )
        session_state["magnetoreception_b_trials_count"] = self.b_trials_count
        session_state["magnetoreception_success_count"] = self.success_count
        session_state["magnetoreception_success_right_count"] = self.success_right_count
        session_state["magnetoreception_success_left_count"] = self.success_left_count
        session_state["magnetoreception_c_dwell_complete"] = self.c_dwell_complete
        session_state["magnetoreception_c_side"] = self.c_side
        session_state["magnetoreception_c_entry_handled"] = self.c_entry_handled
        session_state["magnetoreception_d_entry_handled"] = self.d_entry_handled
        session_state["magnetoreception_magnets_off_time"] = self.magnets_off_time
        session_state["magnetoreception_c_dwell_end_time"] = self.c_dwell_end_time
        session_state["magnetoreception_trial_schedule"] = self.trial_schedule
        session_state["magnetoreception_schedule_seed"] = self.schedule_seed

    def _cancel_c_dwell_schedule(self):
        try:
            schedule.cancel_all(pool="experiment_phases")
        except ValueError:
            pass

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

        # smoothed centroid calculation
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

        # reset zones that are no longer currently detected
        for zone in list(self.zone_counts.keys()):
            if zone not in raw_zones:
                self.zone_counts.pop(zone, None)
                self.zone_first_seen.pop(zone, None)
        
        entered = confirmed_zones - self.in_zones

        # Debug log: animal is in a confirmed zone, but not the zone expected for this phase
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

        if self.phase == "a" and "A" in entered and self.c_dwell_complete:
            self._try_start_trial_at_a()
        elif self.phase == "b" and entered.intersection({"B1", "B2"}):
            side = "B1" if "B1" in entered else "B2"
            self._on_point_b(side)
        elif self.phase == "c" and not self.c_entry_handled:
            expected_c = "C1" if self.cycle_side == "right" else "C2"
            if expected_c in entered:
                self._on_point_c(expected_c)
        elif self.phase == "d" and not self.d_entry_handled:
            if "D" in entered:
                self._on_point_d()
                if "A" in confirmed_zones:
                    self._try_start_trial_at_a()
            elif "A" in confirmed_zones:
                self._on_point_d(via_a_before_d=True)
                self._try_start_trial_at_a()

    def _try_start_trial_at_a(self):
        if self._a_start_scheduled:
            return

        if self.trial_num >= self._total_trials():
            self._complete_block()
            return

        min_gap = exp.get_params().get("magnet_off_to_on_min_seconds", 5)

        if self.magnets_off_time is None:
            self._on_point_a()
            return

        elapsed = time.time() - self.magnets_off_time
        if elapsed >= min_gap:
            self._on_point_a()
            return

        remaining = min_gap - elapsed
        self._a_start_scheduled = True
        self.log.info(
            f"Trial {self.trial_num}: only {elapsed:.1f}s since magnets off at C "
            f"(min {min_gap}s); waiting {remaining:.1f}s before starting at A"
        )
        self._log_event(
            "magnetoreception_training/magnet_gap_wait",
            {
                "trial": self.trial_num,
                "elapsed_seconds": round(elapsed, 2),
                "wait_seconds": round(remaining, 2),
                "min_gap_seconds": min_gap,
            },
        )
        schedule.once(
            self._start_trial_after_magnet_gap, remaining, pool="experiment_phases"
        )

    def _start_trial_after_magnet_gap(self):
        self._a_start_scheduled = False
        if self.phase != "a" or not self.c_dwell_complete:
            return
        if self.trial_num >= self._total_trials():
            self._complete_block()
            return
        self._on_point_a()

    def _on_point_a(self):
        self._a_start_scheduled = False
        self.magnets_off_time = None
        self.c_dwell_end_time = None
        self.d_entry_handled = False
        self.trial_num += 1
        self.magnet_direction = self._magnet_direction_for_trial(self.trial_num)
        self._sync_session_state()

        self.close_back_doors()
        self.close_left_door()
        self.close_right_door()

        if self.magnet_direction == "forward":
            self.log.info(f"Trial {self.trial_num}: at point A, starting magnets forward (north -> B1)")
            self.magnets_forward()
            self.open_right_back_door()
            self.cycle_side = "right"
        elif self.magnet_direction == "reverse":
            self.log.info(f"Trial {self.trial_num}: at point A, starting magnets reverse (north -> B2)")
            self.magnets_reverse()
            self.open_left_back_door()
            self.cycle_side = "left"
        elif self.magnet_direction == "conflict_right":
            self.log.info(
                f"Trial {self.trial_num}: at point A, conflict right trial "
                "(right back door, magnets reverse, no feeder at B1)"
            )
            self.magnets_reverse()
            self.open_right_back_door()
            self.cycle_side = "right"
        elif self.magnet_direction == "conflict_left":
            self.log.info(
                f"Trial {self.trial_num}: at point A, conflict left trial "
                "(left back door, magnets forward, no feeder at B2)"
            )
            self.magnets_forward()
            self.open_left_back_door()
            self.cycle_side = "left"

        self.phase = "b"
        self._sync_session_state()
        self._log_event(
            "magnetoreception/trial_start",
            {
                "trial": self.trial_num,
                "zone": "A",
                "magnet_direction": self.magnet_direction,
                "cycle_side": self.cycle_side,
                "phase": self.phase,
            },
        )

    def _on_point_b(self, side):
        self.log.info(f"Trial {self.trial_num}: at {side}, closing back doors")
        self.close_back_doors()

        feeder_event = {
            "trial": self.trial_num,
            "zone": side,
            "magnet_direction": self.magnet_direction,
            "dispensed": False,
            "feeder": None,
            "reason": None,
        }

        if self.magnet_direction == "conflict_right" and side == "B1":
            self.log.info(
                f"Trial {self.trial_num}: conflict right trial at B1 -> no feeder "
                "(door/magnet mismatch)"
            )
            feeder_event.update({"reason": "magnet_conflict", "expected_zone": "B2"})
        elif self.magnet_direction == "conflict_right" and side == "B2":
            self.log.info(
                f"Trial {self.trial_num}: conflict right trial at B2 -> no feeder, wrong side"
            )
            feeder_event.update(
                {"reason": "incorrect_side", "expected_zone": "B1"}
            )
        elif self.magnet_direction == "conflict_left" and side == "B2":
            self.log.info(
                f"Trial {self.trial_num}: conflict left trial at B2 -> no feeder "
                "(door/magnet mismatch)"
            )
            feeder_event.update({"reason": "magnet_conflict", "expected_zone": "B1"})
        elif self.magnet_direction == "conflict_left" and side == "B1":
            self.log.info(
                f"Trial {self.trial_num}: conflict left trial at B1 -> no feeder, wrong side"
            )
            feeder_event.update(
                {"reason": "incorrect_side", "expected_zone": "B2"}
            )
        elif self.magnet_direction == "forward" and side == "B1":
            right_feeder = self.dispense_right_feeder()
            if right_feeder is not None:
                self.log.info(
                    f"Magnet north toward B1 and animal at B1 -> right feeder {right_feeder}"
                )
                feeder_event.update(
                    {
                        "dispensed": True,
                        "feeder": "right",
                        "right_feeder": right_feeder,
                        "reason": "correct_choice",
                    }
                )
            else:
                self.log.info(
                    "Magnet north toward B1 and animal at B1 -> feeder limit, no dispense"
                )
                feeder_event.update(
                    {
                        "reason": "feeder_limit",
                        "expected_zone": "B1",
                    }
                )
        elif self.magnet_direction == "forward" and side == "B2":
            self.log.info("Magnet north toward B1 and animal at B2 -> no feeder")
            feeder_event.update(
                {
                    "reason": "incorrect_side",
                    "expected_zone": "B1",
                }
            )
        elif self.magnet_direction == "reverse" and side == "B1":
            self.log.info("Magnet north toward B2 and animal at B1 -> no feeder")
            feeder_event.update(
                {
                    "reason": "incorrect_side",
                    "expected_zone": "B2",
                }
            )
        elif self.magnet_direction == "reverse" and side == "B2":
            self.log.info("Magnet north toward B2 and animal at B2 -> left feeder")
            left_feeder = self.dispense_left_feeder()
            if left_feeder is not None:
                feeder_event.update(
                    {
                        "dispensed": True,
                        "feeder": "left",
                        "left_feeder": left_feeder,
                        "reason": "correct_choice",
                    }
                )
            else:
                self.log.info(
                    "Magnet north toward B2 and animal at B2 -> feeder limit, no dispense"
                )
                feeder_event.update(
                    {
                        "reason": "feeder_limit",
                        "expected_zone": "B2",
                    }
                )

        self.b_trials_count += 1
        if feeder_event.get("reason") == "correct_choice":
            self.success_count += 1
            if feeder_event.get("feeder") == "right":
                self.success_right_count += 1
            elif feeder_event.get("feeder") == "left":
                self.success_left_count += 1
        self._sync_session_state()
        
        self._log_event("magnetoreception/point_b", feeder_event)

        self.phase = "c"
        self._sync_session_state()
        self._log_event(
            "magnetoreception/phase_change",
            {"trial": self.trial_num, "phase": self.phase},
        )

    def _on_point_c(self, side):
        expected_c = "C1" if self.cycle_side == "right" else "C2"
        if side != expected_c:
            self.log.info(
                f"Trial {self.trial_num}: at {side}, expected {expected_c} "
                f"for cycle_side={self.cycle_side}; ignoring"
            )
            self._log_event(
                "magnetoreception/wrong_zone",
                {
                    "trial": self.trial_num,
                    "phase": self.phase,
                    "zones": [side],
                    "expected": [expected_c],
                },
            )
            return

        self.c_entry_handled = True
        self.c_side = side
        self.c_dwell_complete = False
        self._sync_session_state()

        self.close_left_door()
        self.close_right_door()

        dwell_seconds = exp.get_params().get("point_c_dwell_seconds", 10)
        magnets_on = self._magnets_on_for_direction()
        self.log.info(
            f"Trial {self.trial_num}: at {side} -> dwell {dwell_seconds}s "
            f"with doors closed, magnets {'on' if magnets_on else 'off'}"
        )
        self._log_event(
            "magnetoreception/point_c",
            {
                "trial": self.trial_num,
                "zone": side,
                "magnet_direction": self.magnet_direction,
                "dwell_seconds": dwell_seconds,
                "doors": "closed",
                "magnets": "on" if magnets_on else "off",
            },
        )
        self.c_dwell_end_time = time.time() + dwell_seconds
        self._sync_session_state()
        schedule.once(self._finish_c_dwell, dwell_seconds, pool="experiment_phases")

    def _finish_c_dwell(self):
        self.c_dwell_end_time = None
        self.magnets_stop()
        self.magnets_off_time = time.time()

        door = "right" if self.c_side == "C1" else "left"
        if self.c_side == "C1":
            self.log.info(
                f"Trial {self.trial_num}: C dwell complete at C1 -> "
                "magnets off, opening right front door"
            )
            self.open_right_door()
        else:
            self.log.info(
                f"Trial {self.trial_num}: C dwell complete at C2 -> "
                "magnets off, opening left front door"
            )
            self.open_left_door()

        self.d_entry_handled = False
        self._sync_session_state()
        self.log.info(
            f"Trial {self.trial_num}: C dwell complete at {self.c_side} -> "
            f"magnets off, {door} front door open, waiting for point D"
        )
        self._log_event(
            "magnetoreception_training/c_dwell_complete",
            {
                "trial": self.trial_num,
                "zone": self.c_side,
                "cycle_side": self.cycle_side,
                "door_opened": door,
                "magnets": "off",
            },
        )
        self.phase = "d"
        self._sync_session_state()

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
        self.c_dwell_complete = True
        self.c_entry_handled = False
        self.in_zones = set()
        self._sync_session_state()
        self._log_event(
            "magnetoreception_training/point_d",
            {
                "trial": self.trial_num,
                "cycle_side": self.cycle_side,
                "c_side": self.c_side,
                "via_a_before_d": via_a_before_d,
            },
        )
        if via_a_before_d:
            self._log_event(
                "magnetoreception_training/point_d_via_a",
                {"trial": self.trial_num},
            )
        else:
            self.log.info(f"Trial {self.trial_num}: waiting for point A to start next trial")
            self._log_event(
                "magnetoreception/waiting_at_a",
                {"trial": self.trial_num},
            )

        if self.trial_num >= self._total_trials():
            self._complete_block()

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
        """Back doors open, front doors closed, magnets off."""
        self.log.info("Setting baseline arena state")
        self.magnets_stop()
        self.close_left_door()
        self.close_right_door()
        self.open_back_doors()

    def magnets_forward(self):
        arena.run_command("forward", "Magnets Forward", None, False)

    def magnets_reverse(self):
        arena.run_command("reverse", "Magnets Reverse", None, False)

    def magnets_stop(self):
        arena.run_command("stop", "Magnets Stop", None, False)

    def _side_feeder_total(self, side):
        if side == "right":
            return self.right_feeder_1_dispense_count + self.right_feeder_2_dispense_count
        return self.left_feeder_1_dispense_count + self.left_feeder_2_dispense_count

    def _check_feeder_stop_limit(self):
        limit = exp.get_params().get("feeder_stop_total_limit", 30)
        right_total = self._side_feeder_total("right")
        left_total = self._side_feeder_total("left")
        if right_total < limit and left_total < limit:
            return

        self.log.warning(
            f"Feeder limit reached (limit={limit}): "
            f"right={right_total}, left={left_total}; "
            "blocking further dispenses on limited side(s)"
        )
        self._log_event(
            "magnetoreception_training/feeder_limit_warning",
            {
                "trial": self.trial_num,
                "feeder_stop_total_limit": limit,
                "right_total": right_total,
                "left_total": left_total,
                "right_feeder_1": self.right_feeder_1_dispense_count,
                "right_feeder_2": self.right_feeder_2_dispense_count,
                "left_feeder_1": self.left_feeder_1_dispense_count,
                "left_feeder_2": self.left_feeder_2_dispense_count,
            },
        )

    def dispense_left_feeder(self):
        limit = exp.get_params().get("feeder_stop_total_limit", 30)
        if self._side_feeder_total("left") >= limit:
            self._check_feeder_stop_limit()
            return None
        per_feeder_limit = exp.get_params().get("feeder_dispense_limit", 16)
        if self.left_feeder_1_dispense_count < per_feeder_limit:
            self.left_feeder_1_dispense_count += 1
            self._sync_session_state()
            self.dispense_left_feeder_1()
            self._check_feeder_stop_limit()
            return 1
        if self._side_feeder_total("left") >= limit:
            self._check_feeder_stop_limit()
            return None
        self.left_feeder_2_dispense_count += 1
        self._sync_session_state()
        self.dispense_left_feeder_2()
        self._check_feeder_stop_limit()
        return 2

    def dispense_left_feeder_1(self):
        arena.run_command("dispense", "Left Feeder 1", None, False)

    def dispense_left_feeder_2(self):
        arena.run_command("dispense", "Left Feeder 2", None, False)

    def dispense_right_feeder(self):
        limit = exp.get_params().get("feeder_stop_total_limit", 30)
        if self._side_feeder_total("right") >= limit:
            self._check_feeder_stop_limit()
            return None
        per_feeder_limit = exp.get_params().get("feeder_dispense_limit", 16)
        if self.right_feeder_1_dispense_count < per_feeder_limit:
            self.right_feeder_1_dispense_count += 1
            self._sync_session_state()
            self.dispense_right_feeder_1()
            self._check_feeder_stop_limit()
            return 1
        if self._side_feeder_total("right") >= limit:
            self._check_feeder_stop_limit()
            return None
        self.right_feeder_2_dispense_count += 1
        self._sync_session_state()
        self.dispense_right_feeder_2()
        self._check_feeder_stop_limit()
        return 2

    def dispense_right_feeder_1(self):
        arena.run_command("dispense", "Right Feeder 1", None, False)

    def dispense_right_feeder_2(self):
        arena.run_command("dispense", "Right Feeder 2", None, False)

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
