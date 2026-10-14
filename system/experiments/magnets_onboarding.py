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


class MagnetsOnboarding(exp.Experiment):
    """
    Magnet onboarding loop. The field is on and there is no reward, so a
    session can measure side preference with the cue.

    Cycle:
    - Point A: front doors closed, both back doors open, magnets on in this
      trial's shuffled direction. Forward points toward B1 (right). Reverse
      points toward B2 (left).
    - Point B1/B2: both back doors close. The field stays on for
      b_hold_seconds (default 15). The side the animal entered chooses the
      exit door, not the magnet direction.
    - After the hold: magnets off, and the front door of that side opens
      (right at B1, left at B2).
    - Point D: that front door closes, then the experiment waits at A.
      If A is confirmed before D, the open front door still closes.

    The next trial at A waits until magnet_off_to_on_min_seconds have passed
    since the magnets last turned off.

    Zone params use normalized coordinates in [0, 1]:
    - Circle: location [cx, cy] and radius (fraction of min(image width, height))
    - Rectangle: location [x1, y1, x2, y2] (centroid must be inside the box)

    Starting or stopping does not move the doors. Stopping turns the magnets
    off. Stopping and restarting resumes the same phase and trial within a
    session. Manual "Reset Baseline" and "Restart Cycle" are still available.
    Reset Baseline opens both back doors, closes both front doors, and turns
    the magnets off.

    Each session runs a fixed block of total_trials (default 50): half forward
    and half reverse in a shuffled order. The block ends after the last full
    A->B->D cycle. There is no feeder.

    random_seed: optional int; if omitted, seeded from session data_dir for
    reproducible shuffled schedules within a session.

    magnetoreception/point_b is logged with the zone and magnet direction and
    without a choice reason, so day-summary scoring skips these trials the
    same way it skips onboarding.
    """

    default_params = {
        "bbox_obs_id": "1",
        "image_source_id": "top",
        "point_a": {"location": [0.42, 0.45, 0.59, 0.72]},
        "point_b1": {"location": [0.74, 0.05, 0.92, 0.42]},
        "point_b2": {"location": [0.07, 0.05, 0.24, 0.42]},
        "point_d": {"location": [0.44, 0.75, 0.57, 1]},
        "zone_confirm_frames": 15,
        "zone_confirm_seconds": 0.5,
        "centroid_smoothing_alpha": 0.3,
        "b_hold_seconds": 15,
        "magnet_off_to_on_min_seconds": 5,
        "total_trials": 50,
        "random_seed": None,
    }

    _SESSION_FIELDS = (
        ("phase", "a"),
        ("magnet_direction", None),
        ("trial_num", 0),
        ("choice_side", None),
        ("d_entry_handled", False),
        ("magnets_off_time", None),
        ("b_hold_end_time", None),
        ("magnet_gap_end_time", None),
        ("trial_schedule", None),
        ("schedule_seed", None),
    )

    def _state_key(self, name):
        return f"magnets_onboarding_{name}"

    def _restore_from_session(self, key, default):
        if key not in session_state:
            return default
        value = session_state[key]
        return default if value is None else value

    def _restore_state(self):
        for name, default in self._SESSION_FIELDS:
            setattr(
                self,
                name,
                self._restore_from_session(self._state_key(name), default),
            )

    def setup(self):
        self.bbox_collector = None
        self.in_zones = set()
        self.zone_counts = {}
        self.zone_first_seen = {}
        self.smoothed_centroid = None
        self._a_start_scheduled = False

        self._restore_state()

        self.actions["Reset Baseline"] = {"run": self.set_baseline}
        self.actions["Magnets Forward"] = {"run": self.magnets_forward}
        self.actions["Magnets Reverse"] = {"run": self.magnets_reverse}
        self.actions["Magnets Stop"] = {"run": self.magnets_stop}
        self.actions["Open Left Door"] = {"run": self.open_left_door}
        self.actions["Close Left Door"] = {"run": self.close_left_door}
        self.actions["Open Right Door"] = {"run": self.open_right_door}
        self.actions["Close Right Door"] = {"run": self.close_right_door}
        self.actions["Open Back Doors"] = {"run": self.open_back_doors}
        self.actions["Close Back Doors"] = {"run": self.close_back_doors}
        self.actions["Restart Cycle"] = {"run": self.restart_cycle}

        self._sync_session_state()

    def _total_trials(self):
        return int(exp.get_params().get("total_trials", 50))

    def _seconds(self, name, default):
        return float(exp.get_params().get(name, default))

    def _trials_per_direction(self):
        total = self._total_trials()
        if total % 2 != 0:
            raise ValueError(f"total_trials must be even, got {total}")
        return total // 2

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
        per_dir = self._trials_per_direction()
        existing = self.trial_schedule

        if existing is not None and len(existing) == total:
            self.log.info(
                f"Using existing trial schedule ({total} trials, seed={self.schedule_seed})"
            )
            return

        seed = self._get_schedule_seed()
        random.seed(seed)
        schedule_list = ["forward"] * per_dir + ["reverse"] * per_dir
        random.shuffle(schedule_list)
        self.trial_schedule = schedule_list
        self.schedule_seed = seed
        self._sync_session_state()
        self.log.info(
            f"Generated shuffled trial schedule: {total} trials "
            f"({per_dir} forward, {per_dir} reverse), seed={seed}"
        )
        self._log_event("magnetoreception/random_seed", {"seed": seed})
        self._log_event(
            "magnetoreception/trial_schedule",
            {
                "seed": seed,
                "total_trials": total,
                "forward_count": per_dir,
                "reverse_count": per_dir,
                "schedule": schedule_list,
            },
        )

    def _magnet_direction_for_trial(self, trial_num):
        return self.trial_schedule[trial_num - 1]

    def _complete_block(self):
        total = self._total_trials()
        self.log.info(f"Block complete: {total} trials finished")
        self._log_event(
            "magnetoreception/block_complete",
            {"trial": self.trial_num, "total_trials": total},
        )
        exp.stop_experiment()

    def _prepare_experiment_resume(self):
        self.in_zones = set()
        self.smoothed_centroid = None
        self.zone_counts = {}
        self.zone_first_seen = {}
        self._cancel_phase_schedule()
        self._a_start_scheduled = False
        self._reconcile_magnets()
        self._rearm_pending_schedules()
        self._sync_session_state()

    def _reconcile_magnets(self):
        """Re-command magnets for an in-progress stage. Waiting at A is left alone."""
        if self.phase in ("b", "b_hold"):
            self._magnets_on_trial_direction()
        elif self.phase == "d":
            self.magnets_stop()

    def _rearm_pending_schedules(self):
        if self.trial_num >= self._total_trials() and self.phase == "a":
            return

        if self.phase == "a" and self.magnet_gap_end_time is not None:
            self._rearm_deadline(
                self.magnet_gap_end_time,
                self._start_trial_after_magnet_gap,
                "magnet gap",
                arm_a_start=True,
            )

        if self.phase == "b_hold":
            self._rearm_deadline(
                self.b_hold_end_time,
                self._finish_b_hold,
                "B hold",
            )

    def _rearm_deadline(self, end_time, callback, label, arm_a_start=False):
        if end_time is None:
            self.log.info(f"Resuming {label}: deadline missing, running now")
            callback()
            return

        remaining = float(end_time) - time.time()
        if remaining > 0:
            self.log.info(f"Resuming {label}: {remaining:.1f}s remaining")
            if arm_a_start:
                self._a_start_scheduled = True
            self._schedule_phase(callback, remaining)
            return

        self.log.info(f"Resuming {label}: deadline passed, running now")
        callback()

    def run(self):
        self.log.info(
            "Starting magnets onboarding (automatic A -> B -> D loop, no reward)"
        )
        self._init_trial_schedule()
        self._log_event("magnetoreception/onboarding_start", {})

        if self.trial_num >= self._total_trials() and self.phase == "a":
            self._complete_block()
            return

        if self.trial_num > 0 or self.phase != "a":
            self.log.info(
                f"Resuming experiment at phase '{self.phase}', trial {self.trial_num}"
            )
            self._log_event(
                "magnetoreception/experiment_resume",
                {
                    "phase": self.phase,
                    "trial": self.trial_num,
                    "magnet_direction": self.magnet_direction,
                    "choice_side": self.choice_side,
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

    def run_trial(self):
        """Re-arm waits after the framework cancels experiment_phases schedules."""
        self._cancel_phase_schedule()
        self._a_start_scheduled = False
        self._rearm_pending_schedules()

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
                "Configure point_a/b1/b2/d with normalized zones."
            )
        except ValueError as e:
            self.log.warning(f"BBox listener not started ({e}). Arena actions still available.")

    def on_video_restart(self):
        self.log.warning(
            "Video restarted while magnets_onboarding is running; "
            "re-attaching bbox zone listener."
        )
        self._start_bbox_listener()

    def end(self):
        self.log.info("Ending magnets onboarding")
        self._log_event(
            "magnetoreception/onboarding_end",
            {"trial": self.trial_num, "phase": self.phase},
        )
        self._cancel_phase_schedule()
        self._cleanup_bbox()
        self.magnets_stop()
        self._sync_session_state()

    def release(self):
        self._cleanup_bbox()

    def restart_cycle(self):
        self._cancel_phase_schedule()
        self.phase = "a"
        self.magnet_direction = None
        self.choice_side = None
        self.d_entry_handled = False
        self.magnets_off_time = None
        self.b_hold_end_time = None
        self.magnet_gap_end_time = None
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
        for name, _default in self._SESSION_FIELDS:
            session_state[self._state_key(name)] = getattr(self, name)

    def _cancel_phase_schedule(self):
        try:
            schedule.cancel_all(pool="experiment_phases")
        except ValueError:
            pass

    def _schedule_phase(self, callback, delay_seconds):
        schedule.once(callback, max(0.0, float(delay_seconds)), pool="experiment_phases")

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
            "b_hold": {"B1", "B2"},
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
        elif self.phase == "d" and not self.d_entry_handled:
            if "D" in entered:
                if self._on_point_d() and "A" in confirmed_zones:
                    self._try_start_trial_at_a()
            elif "A" in confirmed_zones:
                if self._on_point_d(via_a_before_d=True):
                    self._try_start_trial_at_a()

    def _try_start_trial_at_a(self):
        if self.phase != "a" or self._a_start_scheduled:
            return

        if self.trial_num >= self._total_trials():
            self._complete_block()
            return

        min_gap = self._seconds("magnet_off_to_on_min_seconds", 5)

        if self.magnets_off_time is None:
            self._on_point_a()
            return

        elapsed = time.time() - float(self.magnets_off_time)
        if elapsed >= min_gap:
            self._on_point_a()
            return

        remaining = min_gap - elapsed
        self._a_start_scheduled = True
        self.magnet_gap_end_time = time.time() + remaining
        self._sync_session_state()
        self.log.info(
            f"Trial {self.trial_num}: only {elapsed:.1f}s since magnets off "
            f"(min {min_gap}s); waiting {remaining:.1f}s before starting at A"
        )
        self._log_event(
            "magnetoreception/magnet_gap_wait",
            {
                "trial": self.trial_num,
                "elapsed_seconds": round(elapsed, 2),
                "wait_seconds": round(remaining, 2),
                "min_gap_seconds": min_gap,
            },
        )
        self._schedule_phase(self._start_trial_after_magnet_gap, remaining)

    def _start_trial_after_magnet_gap(self):
        self._a_start_scheduled = False
        self.magnet_gap_end_time = None
        if self.phase != "a":
            return
        if self.trial_num >= self._total_trials():
            self._complete_block()
            return
        self._on_point_a()

    def _on_point_a(self):
        self._a_start_scheduled = False
        self.magnet_gap_end_time = None
        self.magnets_off_time = None
        self.b_hold_end_time = None
        self.choice_side = None
        self.d_entry_handled = False
        self.trial_num += 1
        self.magnet_direction = self._magnet_direction_for_trial(self.trial_num)

        self.close_left_door()
        self.close_right_door()
        self.open_back_doors()
        self._magnets_on_trial_direction()

        self.phase = "b"
        self._sync_session_state()

        toward = "B1" if self.magnet_direction == "forward" else "B2"
        self.log.info(
            f"Trial {self.trial_num}: at point A, front doors closed, "
            f"both back doors open, magnets {self.magnet_direction} (toward {toward})"
        )
        self._log_event(
            "magnetoreception/trial_start",
            {
                "trial": self.trial_num,
                "zone": "A",
                "magnet_direction": self.magnet_direction,
                "phase": self.phase,
                "back_doors": "both_open",
                "front_doors": "closed",
            },
        )

    def _on_point_b(self, side):
        if self.phase != "b":
            return

        self.choice_side = side
        self.close_back_doors()
        hold = self._seconds("b_hold_seconds", 15)
        self.phase = "b_hold"
        self.b_hold_end_time = time.time() + hold
        self._sync_session_state()

        self.log.info(
            f"Trial {self.trial_num}: at {side}, back doors closed, "
            f"magnets stay {self.magnet_direction} for {hold:.1f}s"
        )
        self._log_event(
            "magnetoreception/point_b",
            {
                "trial": self.trial_num,
                "zone": side,
                "magnet_direction": self.magnet_direction,
            },
        )
        self._schedule_phase(self._finish_b_hold, hold)

    def _finish_b_hold(self):
        if self.phase != "b_hold":
            return

        self.b_hold_end_time = None
        self.magnets_stop()
        self.magnets_off_time = time.time()
        door = self._open_chosen_front_door()
        self.d_entry_handled = False
        self.phase = "d"
        self._sync_session_state()

        self.log.info(
            f"Trial {self.trial_num}: B hold complete at {self.choice_side} -> "
            f"magnets off, {door} front door open, waiting for point D"
        )
        self._log_event(
            "magnetoreception/b_hold_complete",
            {
                "trial": self.trial_num,
                "zone": self.choice_side,
                "magnet_direction": self.magnet_direction,
                "door_opened": door,
                "magnets": "off",
            },
        )

    def _on_point_d(self, via_a_before_d=False):
        """Close the chosen front door and return to waiting for A.

        Returns False when this was the last trial and the block has stopped.
        """
        self.d_entry_handled = True
        door = self._close_chosen_front_door()
        if via_a_before_d:
            self.log.info(
                f"Trial {self.trial_num}: at A before D detected -> "
                f"close {door} front door"
            )
        else:
            self.log.info(
                f"Trial {self.trial_num}: at D -> close {door} front door"
            )

        self.phase = "a"
        self.in_zones = set()
        self._sync_session_state()
        self._log_event(
            "magnetoreception/point_d",
            {
                "trial": self.trial_num,
                "zone": "D",
                "choice_side": self.choice_side,
                "magnet_direction": self.magnet_direction,
                "door_closed": door,
                "via_a_before_d": via_a_before_d,
            },
        )
        if via_a_before_d:
            self._log_event(
                "magnetoreception/point_d_via_a",
                {"trial": self.trial_num},
            )
        else:
            self.log.info(
                f"Trial {self.trial_num}: waiting for point A to start next trial"
            )
            self._log_event(
                "magnetoreception/waiting_at_a",
                {"trial": self.trial_num},
            )

        if self.trial_num >= self._total_trials():
            self._complete_block()
            return False
        return True

    def _zones_at(self, centroid, w, h, min_dim):
        params = exp.get_params()
        zone_defs = {
            "A": params["point_a"],
            "B1": params["point_b1"],
            "B2": params["point_b2"],
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

    def _magnets_on_trial_direction(self):
        if self.magnet_direction == "forward":
            self.magnets_forward()
        elif self.magnet_direction == "reverse":
            self.magnets_reverse()
        else:
            self.log.warning(
                f"Trial {self.trial_num}: no magnet direction to apply"
            )

    def _choice_door_side(self):
        if self.choice_side == "B1":
            return "right"
        if self.choice_side == "B2":
            return "left"
        return None

    def _open_chosen_front_door(self):
        side = self._choice_door_side()
        if side == "right":
            self.open_right_door()
        elif side == "left":
            self.open_left_door()
        else:
            self.log.warning(
                f"Trial {self.trial_num}: choice side unknown, opening both front doors"
            )
            self.open_left_door()
            self.open_right_door()
            return "both"
        return side

    def _close_chosen_front_door(self):
        side = self._choice_door_side()
        if side == "right":
            self.close_right_door()
        elif side == "left":
            self.close_left_door()
        else:
            self.log.warning(
                f"Trial {self.trial_num}: choice side unknown, closing both front doors"
            )
            self.close_left_door()
            self.close_right_door()
            return "both"
        return side

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
