"""Write the experiment heartbeat file consumed by the health monitor."""

import json
import time
from pathlib import Path

DEFAULT_HEALTH_DIR = Path("/data/reptilearn/health")
HEARTBEAT_NAME = "experiment_heartbeat.json"


def heartbeat_path(health_dir=None) -> Path:
    return Path(health_dir or DEFAULT_HEALTH_DIR) / HEARTBEAT_NAME


def write_experiment_heartbeat(session_state, health_dir=None) -> Path:
    """Atomically write the current session heartbeat.

    session_state: a mapping or managed_state.Cursor with session fields.
    """
    dest_dir = Path(health_dir or DEFAULT_HEALTH_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / HEARTBEAT_NAME

    def _get(key, default=None):
        try:
            if hasattr(session_state, "get"):
                value = session_state.get(key, default)
            else:
                value = session_state[key]
        except Exception:
            return default
        return default if value is None else value

    payload = {
        "ts": time.time(),
        "session_id": _get("id"),
        "experiment": _get("experiment"),
        "is_running": bool(_get("is_running", False)),
        "data_dir": str(_get("data_dir", "") or ""),
        "cur_block": _get("cur_block"),
        "cur_trial": _get("cur_trial"),
        "phase": _get("magnetoreception_phase") or _get("onboarding_phase"),
        "last_bbox_ts": _get("last_bbox_ts"),
        "last_zone_event_ts": _get("last_zone_event_ts"),
        "bbox_listener_generation": _get("bbox_listener_generation"),
        "bbox_listener_obs_id": _get("bbox_listener_obs_id"),
    }

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, default=str) + "\n")
    tmp.replace(path)
    return path


_ZONE_EVENT_MARKERS = (
    "/wrong_zone",
    "/point_",
    "/phase_change",
    "/waiting_at_a",
)


def note_bbox_listener_attached(session_state, obs_id) -> None:
    """Record that the experiment attached a bbox listener to the current observers."""
    try:
        import video_system as vs

        generation = vs.observers_generation()
    except Exception:
        generation = None
    session_state["bbox_listener_obs_id"] = obs_id
    session_state["bbox_listener_generation"] = generation
    session_state["bbox_listener_attached_ts"] = time.time()
    session_state["last_bbox_ts"] = time.time()


def note_bbox_frame(session_state, min_interval_sec=5.0) -> None:
    """Throttle-update last_bbox_ts. Call from on_bbox_detection (including empty dets)."""
    now = time.time()
    try:
        last = session_state.get("last_bbox_ts")
        if last is not None and (now - float(last)) < min_interval_sec:
            return
    except Exception:
        pass
    session_state["last_bbox_ts"] = now


def note_zone_event(session_state, event=None) -> None:
    if event is not None and not any(m in str(event) for m in _ZONE_EVENT_MARKERS):
        return
    session_state["last_zone_event_ts"] = time.time()
