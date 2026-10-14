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


class MagnetoreceptionExperimentV2(exp.Experiment):
    """
    Delayed-reward magnetoreception choice experiment driven by bbox location.

    Choice paradigm: the animal uses the magnetic field to choose B1 vs B2.
    Forward is correct at B1 (right); reverse is correct at B2 (left).

    Cycle (repeats while the experiment runs):
    - Point A: all doors closed, magnets on in this trial's shuffled direction.
      After a_back_doors_delay_seconds, both back doors open.
    - Point B1/B2: magnets off and both back doors close.
      Correct: after correct_reward_delay_seconds, magnets on in the same
      direction and the chosen feeder dispenses; after
      correct_post_reward_seconds, magnets off and that side's front door opens.
      Incorrect: no food; after incorrect_exit_delay_seconds, that side's front
      door opens. Magnets stay off.
    - Point C (same box as magnetoreception_exp point D): close the front door
      of the chosen side and return to A.
      If A is confirmed before C, the chosen front door still closes.

    The next trial at A waits until magnet_off_to_on_min_seconds have passed
    since the magnets last turned off.

    Zone params use normalized coordinates in [0, 1]:
    - Circle: location [cx, cy] and radius (fraction of min(image width, height))
    - Rectangle: location [x1, y1, x2, y2] (centroid must be inside the box)

    Starting or stopping the experiment does not move doors or magnets.
    Stopping and restarting resumes the same phase and trial within a session.
    Manual "Reset Baseline" and "Restart Cycle" are still available.
    Reset Baseline closes every door and turns the magnets off.

    Each session runs a fixed block of total_trials (default 60): half forward and
    half reverse in a shuffled order. The block ends after the last full A->B->C
    cycle. feeder_stop_total_limit logs a warning and blocks further dispenses on
    that side but does not stop the block.

    random_seed: optional int; if omitted, seeded from session data_dir for
    reproducible shuffled schedules within a session.

    success_count counts rewards that were actually dispensed. The choice itself
    is logged on magnetoreception/point_b when the animal reaches B, before the
    reward delay. A->B time runs from magnetoreception/back_doors_open to that
    choice, so it excludes the closed-door wait at A and the reward delay.
    """

    default_params = {
        "bbox_obs_id": "1",
        "image_source_id": "top",
        "point_a": {"location": [0.42, 0.2, 0.59, 0.72]},
        "point_b1": {"location": [0.74, 0.05, 0.92, 0.42]},
        "point_b2": {"location": [0.07, 0.05, 0.24, 0.42]},
        "point_c": {"location": [0.44, 0.75, 0.57, 1]},
        "zone_confirm_frames": 15,
        "zone_confirm_seconds": 0.5,
        "centroid_smoothing_alpha": 0.3,
        "feeder_dispense_limit": 15,
        "feeder_stop_total_limit": 30,
        "a_back_doors_delay_seconds": 5,
        "correct_reward_delay_seconds": 5,
        "correct_post_reward_seconds": 15,
        "incorrect_exit_delay_seconds": 5,
        "magnet_off_to_on_min_seconds": 5,
        "total_trials": 60,
        "random_seed": None,
    }

    _SESSION_FIELDS = (
        ("phase", "a"),
        ("magnet_direction", None),
        ("trial_num", 0),
        ("cycle_side", None),
        ("choice_side", None),
        ("choice_correct", None),
        ("b_stage", None),
        ("reward_dispensed", False),
        ("c_entry_handled", False),
        ("magnets_off_time", None),
        ("a_delay_end_time", None),
        ("b_stage_end_time", None),
        ("magnet_gap_end_time", None),
        ("right_feeder_1_dispense_count", 0),
        ("left_feeder_1_dispense_count", 0),
        ("right_feeder_2_dispense_count", 0),
        ("left_feeder_2_dispense_count", 0),
        ("b_trials_count", 0),
        ("success_count", 0),
        ("success_right_count", 0),
        ("success_left_count", 0),
        ("trial_schedule", None),
        ("schedule_seed", None),
    )

    def _state_key(self, name):
        return f"magnetoreception_v2_{name}"

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

    def _total_trials(self):
        return int(exp.get_params().get("total_trials", 60))

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
        if self.phase in ("a_delay", "b"):
            self._magnets_on_trial_direction()
        elif self.phase == "b_wait" and self.b_stage == "post_reward":
            self._magnets_on_trial_direction()
        elif self.phase == "b_wait" and self.b_stage in ("pre_reward", "incorrect"):
            self.magnets_stop()
        elif self.phase == "c":
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

        if self.phase == "a_delay":
            self._rearm_deadline(
                self.a_delay_end_time,
                self._finish_a_delay,
                "A back-door delay",
            )

        if self.phase == "b_wait":
            callback = {
                "pre_reward": self._deliver_reward,
                "post_reward": self._finish_correct_hold,
                "incorrect": self._open_exit_after_incorrect,
            }.get(self.b_stage)
            if callback is None:
                self.log.warning(
                    f"Trial {self.trial_num}: phase b_wait has no stage "
                    f"({self.b_stage!r}); not rearming"
                )
            else:
                self._rearm_deadline(
                    self.b_stage_end_time,
                    callback,
                    f"B stage {self.b_stage}",
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
            "Starting magnetoreception experiment v2 (automatic A -> B -> C loop)"
        )
        self._init_trial_schedule()
        self._log_event("magnetoreception/experiment_start", {})

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
                    "b_stage": self.b_stage,
                    "choice_side": self.choice_side,
                    "choice_correct": self.choice_correct,
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
                "Configure point_a/b1/b2/c with normalized zones."
            )
        except ValueError as e:
            self.log.warning(f"BBox listener not started ({e}). Arena actions still available.")

    def on_video_restart(self):
        self.log.warning(
            "Video restarted while magnetoreception_exp_v2 is running; "
            "re-attaching bbox zone listener."
        )
        self._start_bbox_listener()

    def end(self):
        self.log.info("Ending magnetoreception experiment v2")
        self._log_event(
            "magnetoreception/experiment_end",
            {"trial": self.trial_num, "phase": self.phase},
        )
        self._cancel_phase_schedule()
        self._cleanup_bbox()
        self._sync_session_state()

    def release(self):
        self._cleanup_bbox()

    def restart_cycle(self):
        self._cancel_phase_schedule()
        self.phase = "a"
        self.magnet_direction = None
        self.cycle_side = None
        self.choice_side = None
        self.choice_correct = None
        self.b_stage = None
        self.reward_dispensed = False
        self.c_entry_handled = False
        self.magnets_off_time = None
        self.a_delay_end_time = None
        self.b_stage_end_time = None
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

    def _log_phase(self, phase):
        self._log_event(
            "magnetoreception/phase_change",
            {"trial": self.trial_num, "phase": phase, "b_stage": self.b_stage},
        )

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
            "a_delay": {"A"},
            "b": {"B1", "B2"},
            "b_wait": {"B1", "B2"},
            "c": {"C"},
        }

        wrong_zones = entered - expected_zones.get(self.phase, set())
        if self.phase == "c":
            wrong_zones -= {"A", "C"}

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
            if "C" in entered:
                if self._finish_loop() and "A" in confirmed_zones:
                    self._try_start_trial_at_a()
            elif "A" in confirmed_zones:
                if self._finish_loop(via_a_before_c=True):
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
        self.a_delay_end_time = None
        self.b_stage_end_time = None
        self.b_stage = None
        self.choice_side = None
        self.choice_correct = None
        self.reward_dispensed = False
        self.c_entry_handled = False
        self.trial_num += 1
        self.magnet_direction = self._magnet_direction_for_trial(self.trial_num)
        if self.magnet_direction == "forward":
            self.cycle_side = "right"
        else:
            self.cycle_side = "left"

        self._close_all_doors()
        self._magnets_on_trial_direction()

        delay = self._seconds("a_back_doors_delay_seconds", 5)
        self.phase = "a_delay"
        self.a_delay_end_time = time.time() + delay
        self._sync_session_state()

        self.log.info(
            f"Trial {self.trial_num}: at point A, all doors closed, "
            f"magnets {self.magnet_direction} "
            f"(correct choice -> {'B1' if self.cycle_side == 'right' else 'B2'}); "
            f"back doors open in {delay:.1f}s"
        )
        self._log_event(
            "magnetoreception/trial_start",
            {
                "trial": self.trial_num,
                "zone": "A",
                "magnet_direction": self.magnet_direction,
                "cycle_side": self.cycle_side,
                "phase": self.phase,
                "doors": "all_closed",
                "back_doors_delay_seconds": delay,
            },
        )
        self._log_phase(self.phase)
        self._schedule_phase(self._finish_a_delay, delay)

    def _finish_a_delay(self):
        if self.phase != "a_delay":
            return
        self.a_delay_end_time = None
        self.open_back_doors()
        self.phase = "b"
        # A choice seen while the back doors were still closed must count once they open.
        self.in_zones -= {"B1", "B2"}
        self._sync_session_state()
        self.log.info(
            f"Trial {self.trial_num}: back doors open, waiting for B1/B2"
        )
        self._log_event(
            "magnetoreception/back_doors_open",
            {
                "trial": self.trial_num,
                "magnet_direction": self.magnet_direction,
                "back_doors": "both_open",
            },
        )
        self._log_phase(self.phase)

    def _on_point_b(self, side):
        if self.phase != "b":
            return

        expected = "B1" if self.magnet_direction == "forward" else "B2"
        self.choice_side = side
        self.choice_correct = side == expected
        self.magnets_stop()
        self.magnets_off_time = time.time()
        self.close_back_doors()
        self.b_trials_count += 1

        self.log.info(
            f"Trial {self.trial_num}: at {side}, magnets off, back doors closed "
            f"({'correct' if self.choice_correct else 'incorrect'}, expected {expected})"
        )
        self._log_event(
            "magnetoreception/point_b",
            {
                "trial": self.trial_num,
                "zone": side,
                "magnet_direction": self.magnet_direction,
                "dispensed": False,
                "feeder": None,
                "reason": "correct_choice" if self.choice_correct else "incorrect_side",
                "expected_zone": expected,
                "choice_correct": self.choice_correct,
            },
        )

        self.phase = "b_wait"
        if self.choice_correct:
            delay = self._seconds("correct_reward_delay_seconds", 5)
            self.b_stage = "pre_reward"
            self._log_phase(self.phase)
            self.b_stage_end_time = time.time() + delay
            self._sync_session_state()
            self._schedule_phase(self._deliver_reward, delay)
        else:
            delay = self._seconds("incorrect_exit_delay_seconds", 5)
            self.b_stage = "incorrect"
            self._log_phase(self.phase)
            self.b_stage_end_time = time.time() + delay
            self._sync_session_state()
            self.log.info(
                f"Trial {self.trial_num}: incorrect choice, no reward; "
                f"front door opens in {delay:.1f}s"
            )
            self._schedule_phase(self._open_exit_after_incorrect, delay)

    def _deliver_reward(self):
        if self.phase != "b_wait" or self.b_stage != "pre_reward":
            return

        self._magnets_on_trial_direction()
        feeder_num = None
        feeder_side = None
        if not self.reward_dispensed:
            self.reward_dispensed = True
            self._sync_session_state()
            feeder_num, feeder_side = self._dispense_choice_reward()
            reward_event = {
                "trial": self.trial_num,
                "zone": self.choice_side,
                "magnet_direction": self.magnet_direction,
                "dispensed": feeder_num is not None,
                "feeder": feeder_side if feeder_num is not None else None,
                "reason": "correct_choice" if feeder_num is not None else "feeder_limit",
            }
            if feeder_num is not None:
                reward_event[f"{feeder_side}_feeder"] = feeder_num
                self.success_count += 1
                if feeder_side == "right":
                    self.success_right_count += 1
                elif feeder_side == "left":
                    self.success_left_count += 1
                self.log.info(
                    f"Trial {self.trial_num}: reward at {self.choice_side} -> "
                    f"{feeder_side} feeder {feeder_num}, magnets {self.magnet_direction}"
                )
            else:
                self.log.info(
                    f"Trial {self.trial_num}: correct choice at {self.choice_side} "
                    "but feeder limit reached, no dispense"
                )
            self._log_event("magnetoreception/reward", reward_event)

        hold = self._seconds("correct_post_reward_seconds", 15)
        self.b_stage = "post_reward"
        self.b_stage_end_time = time.time() + hold
        self._sync_session_state()
        self._log_phase(self.phase)
        self.log.info(
            f"Trial {self.trial_num}: magnets on after reward; "
            f"front door opens in {hold:.1f}s"
        )
        self._schedule_phase(self._finish_correct_hold, hold)

    def _finish_correct_hold(self):
        if self.phase != "b_wait" or self.b_stage != "post_reward":
            return
        self.magnets_stop()
        self.magnets_off_time = time.time()
        self._sync_session_state()
        self._open_exit_door()

    def _open_exit_after_incorrect(self):
        if self.phase != "b_wait" or self.b_stage != "incorrect":
            return
        self._open_exit_door()

    def _open_exit_door(self):
        door = self._open_chosen_front_door()
        self.b_stage = None
        self.b_stage_end_time = None
        self.c_entry_handled = False
        self.phase = "c"
        self._sync_session_state()
        self.log.info(
            f"Trial {self.trial_num}: opening {door} front door at {self.choice_side}, "
            "magnets off, waiting for point C"
        )
        self._log_event(
            "magnetoreception/exit_door",
            {
                "trial": self.trial_num,
                "zone": self.choice_side,
                "choice_correct": self.choice_correct,
                "door_opened": door,
                "magnets": "off",
            },
        )
        self._log_phase(self.phase)

    def _finish_loop(self, via_a_before_c=False):
        """Close the chosen front door and return to waiting for A.

        Returns False when this was the last trial and the block has stopped.
        """
        self.c_entry_handled = True
        door = self._close_chosen_front_door()
        if via_a_before_c:
            self.log.info(
                f"Trial {self.trial_num}: at A before C detected -> "
                f"close {door} front door"
            )
        else:
            self.log.info(
                f"Trial {self.trial_num}: at C -> close {door} front door"
            )

        self.phase = "a"
        self.b_stage = None
        self.b_stage_end_time = None
        self.in_zones = set()
        self._sync_session_state()
        self._log_event(
            "magnetoreception/point_c",
            {
                "trial": self.trial_num,
                "zone": "C",
                "choice_side": self.choice_side,
                "cycle_side": self.cycle_side,
                "door_closed": door,
                "via_a_before_c": via_a_before_c,
            },
        )
        self._log_phase(self.phase)
        if via_a_before_c:
            self._log_event(
                "magnetoreception/point_c_via_a",
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
            "C": params["point_c"],
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

    def _close_all_doors(self):
        self.close_left_door()
        self.close_right_door()
        self.close_back_doors()

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

    def _dispense_choice_reward(self):
        if self.choice_side == "B1":
            return self.dispense_right_feeder(), "right"
        if self.choice_side == "B2":
            return self.dispense_left_feeder(), "left"
        self.log.warning(
            f"Trial {self.trial_num}: cannot dispense, choice side unknown"
        )
        return None, None

    def set_baseline(self):
        """All doors closed, magnets off."""
        self.log.info("Setting baseline arena state")
        self.magnets_stop()
        self._close_all_doors()

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
            "magnetoreception/feeder_limit_warning",
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
