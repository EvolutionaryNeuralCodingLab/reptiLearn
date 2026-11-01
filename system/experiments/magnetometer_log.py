"""Append magnetometer samples to the session directory while a trial is in progress."""

import csv
import threading
import time
from pathlib import Path

import experiment as exp
import schedule

INTERFACE = "Magnetic Sensor"
INTERVAL_SEC = 5.0
POOL = "magnetometer_log"
COLUMNS = (
    "time",
    "trial",
    "phase",
    "magnet_direction",
    "b_stage",
    "x_uT",
    "y_uT",
    "z_uT",
    "b_uT",
)


class MagnetometerCsvLog:
    """
    Write one CSV row every 5 seconds while `owner.phase` is in `active_phases`.

    The file is `<session data_dir>/magnetometer.csv`. Sampling starts on the
    transition into an active phase (and immediately on resume) and stops when
    the phase leaves that set or the experiment ends.
    """

    def __init__(self, owner, active_phases):
        self.owner = owner
        self.active_phases = frozenset(active_phases)
        self._scheduled = False
        self._lock = threading.Lock()

    def sync(self):
        if not self._experiment_running():
            return
        if getattr(self.owner, "phase", None) in self.active_phases:
            self.start()
        else:
            self.stop()

    def start(self):
        with self._lock:
            if self._scheduled:
                return
            self._scheduled = True
        self._write_row()
        schedule.repeat(self._tick, INTERVAL_SEC, pool=POOL)
        path = self._csv_path()
        self.owner.log.info(
            "Logging magnetometer every "
            f"{INTERVAL_SEC:.0f}s during phases {sorted(self.active_phases)}"
            + (f" -> {path}" if path is not None else "")
        )

    def stop(self):
        with self._lock:
            was_scheduled = self._scheduled
            self._scheduled = False
        if not was_scheduled:
            return
        try:
            # wait=False: this may run on the scheduler thread itself.
            schedule.cancel_all(pool=POOL, wait=False)
        except ValueError:
            pass

    def _tick(self):
        try:
            if (
                not self._experiment_running()
                or getattr(self.owner, "phase", None) not in self.active_phases
            ):
                self.stop()
                return
            self._write_row()
        except Exception:
            self.owner.log.exception("Failed to log magnetometer sample")

    def _experiment_running(self):
        try:
            return bool(exp.session_state["is_running"])
        except Exception:
            return False

    def _csv_path(self):
        try:
            data_dir = exp.session_state["data_dir"]
        except Exception:
            return None
        if not data_dir:
            return None
        return Path(data_dir) / "magnetometer.csv"

    def _reading(self):
        try:
            if not exp.state.exists(("arena", "values", INTERFACE)):
                return None
            reading = exp.state["arena", "values", INTERFACE]
        except Exception:
            return None
        if not isinstance(reading, (list, tuple)) or len(reading) < 4:
            return None
        return [float(reading[0]), float(reading[1]), float(reading[2]), float(reading[3])]

    def _write_row(self):
        path = self._csv_path()
        if path is None:
            return
        reading = self._reading()
        if reading is None:
            values = ["", "", "", ""]
        else:
            values = [f"{v:.3f}" for v in reading]
        direction = getattr(self.owner, "magnet_direction", None)
        stage = getattr(self.owner, "b_stage", None)
        row = [
            f"{time.time():.3f}",
            getattr(self.owner, "trial_num", ""),
            getattr(self.owner, "phase", ""),
            "" if direction is None else direction,
            "" if stage is None else stage,
            *values,
        ]
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            new_file = not path.exists()
            with path.open("a", newline="") as handle:
                writer = csv.writer(handle)
            if new_file:
                writer.writerow(COLUMNS)
            writer.writerow(row)
        self._notify_owner()

    def _notify_owner(self):
        hook = getattr(self.owner, "on_magnetometer_sample", None)
        if hook is None:
            return
        try:
            hook()
        except Exception:
            self.owner.log.exception("Failed to update trial status")
