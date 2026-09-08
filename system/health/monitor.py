"""
Deterministic ReptiLearn health monitor.

Run from the system/ directory:

    python -m health.monitor

Exit codes: 0 healthy (warnings allowed), 1 unhealthy, 2 monitor error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HEALTH_DIR = Path(__file__).resolve().parent
SYSTEM_DIR = HEALTH_DIR.parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_ERROR = 2

ARDUINO_VID = 0x2341


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or (HEALTH_DIR / "config.json")
    with open(cfg_path, "r") as f:
        cfg = json.load(f)
    cfg["_config_path"] = str(cfg_path)
    return cfg


def health_dir(cfg: dict) -> Path:
    return Path(cfg.get("health_dir", "/data/reptilearn/health"))


def resolve_path(cfg: dict, key: str, default: str) -> Path:
    raw = (cfg.get("paths") or {}).get(key, default)
    path = Path(raw)
    if not path.is_absolute():
        path = SYSTEM_DIR / path
    return path


def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    tmp.replace(path)


def result(check_id: str, ok: bool, severity: str, summary: str, details=None) -> dict:
    return {
        "id": check_id,
        "ok": ok,
        "severity": severity,
        "summary": summary,
        "details": details or {},
    }


def skip(check_id: str, summary: str, details=None) -> dict:
    return result(check_id, True, "skip", summary, details)


def nested_get(data, *keys, default=None):
    cur = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def fetch_state(cfg: dict) -> tuple[dict | None, str | None]:
    web = cfg.get("web_ui") or {}
    host = web.get("host", "127.0.0.1")
    port = int(web.get("port", 3500))
    timeout = float(web.get("timeout_sec", 3))
    url = f"http://{host}:{port}/state"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def session_running(state: dict | None) -> bool:
    if not state:
        return False
    return bool(nested_get(state, "session", "is_running", default=False))


def session_data_dir(state: dict | None, heartbeat: dict | None) -> Path | None:
    raw = None
    if state:
        raw = nested_get(state, "session", "data_dir")
    if not raw and heartbeat:
        raw = heartbeat.get("data_dir")
    if not raw:
        return None
    return Path(str(raw))


def is_recording(state: dict | None) -> bool:
    if not state:
        return False
    return bool(nested_get(state, "video", "record", "is_recording", default=False))


def find_processes(needles: list[str]) -> list[dict]:
    try:
        import psutil
    except ImportError:
        return _find_processes_pgrep(needles)

    matches = []
    self_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] == self_pid:
            continue
        cmdline = proc.info.get("cmdline") or []
        joined = " ".join(cmdline)
        if "health.monitor" in joined or "health/monitor" in joined:
            continue
        if "health.checkout" in joined or "health.day_summary" in joined:
            continue
        if all(needle in joined or needle == proc.info.get("name") for needle in needles):
            matches.append(
                {
                    "pid": proc.info["pid"],
                    "name": proc.info.get("name"),
                    "cmdline": joined,
                }
            )
    return matches


def _find_processes_pgrep(needles: list[str]) -> list[dict]:
    pattern = needles[0]
    try:
        out = subprocess.check_output(
            ["pgrep", "-af", pattern], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    matches = []
    self_pid = os.getpid()
    for line in out.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == self_pid:
            continue
        cmd = parts[1] if len(parts) > 1 else ""
        if "health.monitor" in cmd or "health/monitor" in cmd:
            continue
        if "health.checkout" in cmd or "health.day_summary" in cmd:
            continue
        if all(n in cmd for n in needles):
            matches.append({"pid": pid, "name": None, "cmdline": cmd})
    return matches


def check_process(cfg: dict, state: dict | None, state_error: str | None) -> dict:
    procs_cfg = cfg.get("processes") or {}
    details = {"processes": {}, "http": {}}
    failed = []
    warnings = []

    for name, spec in procs_cfg.items():
        needles = spec.get("needles") if isinstance(spec, dict) else spec
        required = spec.get("required", True) if isinstance(spec, dict) else True
        found = find_processes(list(needles))
        details["processes"][name] = {"required": required, "matches": found}
        if not found:
            msg = f"{name} process not found"
            if required:
                failed.append(msg)
            else:
                warnings.append(msg)

    details["http"]["ok"] = state is not None
    details["http"]["error"] = state_error
    if state is not None:
        details["http"]["session_running"] = session_running(state)
        details["http"]["arena_bridge"] = nested_get(state, "arena", "bridge", default={})
        details["http"]["acquiring"] = {
            src_id: nested_get(src, "acquiring", default=None)
            for src_id, src in (nested_get(state, "video", "image_sources", default={}) or {}).items()
        }
    else:
        failed.append(f"/state unreachable ({state_error})")

    if failed:
        return result("process", False, "fail", "; ".join(failed), details)
    if warnings:
        return result("process", True, "warn", "; ".join(warnings), details)
    return result("process", True, "ok", "main, arena, and HTTP /state are up", details)


def load_heartbeat(cfg: dict) -> dict | None:
    path = health_dir(cfg) / "experiment_heartbeat.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def check_heartbeat(cfg: dict, state: dict | None, hb: dict | None) -> dict:
    require_session = cfg.get("require_session_for_heartbeat_and_files", True)
    stale_sec = float(cfg.get("heartbeat_stale_sec", 180))
    running = session_running(state)
    if not running and hb:
        running = bool(hb.get("is_running")) and state is None

    details = {
        "require_session": require_session,
        "session_running": session_running(state),
        "stale_sec": stale_sec,
        "heartbeat": hb,
        "arena_timestamp": nested_get(state, "arena", "timestamp") if state else None,
    }

    if require_session and not session_running(state) and not (state is None and hb and hb.get("is_running")):
        return skip("heartbeat", "no session running; heartbeat not required", details)

    if hb is None:
        return result("heartbeat", False, "fail", "experiment heartbeat file missing", details)

    ts = hb.get("ts")
    if not isinstance(ts, (int, float)):
        return result("heartbeat", False, "fail", "heartbeat file has no timestamp", details)

    age = time.time() - float(ts)
    details["age_sec"] = round(age, 1)
    if age > stale_sec:
        return result(
            "heartbeat",
            False,
            "fail",
            f"experiment heartbeat stale ({age:.0f}s > {stale_sec:.0f}s)",
            details,
        )

    arena_ts = nested_get(state, "arena", "timestamp") if state else None
    if isinstance(arena_ts, (int, float)):
        arena_age = time.time() - float(arena_ts)
        details["arena_age_sec"] = round(arena_age, 1)
        poll_interval = 60
        if arena_age > max(stale_sec, poll_interval * 3):
            return result(
                "heartbeat",
                False,
                "fail",
                f"arena poll timestamp stale ({arena_age:.0f}s)",
                details,
            )

    return result("heartbeat", True, "ok", f"heartbeat fresh ({age:.0f}s old)", details)


def _bbox_experiment(cfg: dict, state: dict | None, hb: dict | None) -> str | None:
    name = None
    if state:
        name = nested_get(state, "session", "experiment")
    if not name and hb:
        name = hb.get("experiment")
    if not name:
        return None
    name = str(name)
    allowed = cfg.get("bbox_experiments") or [
        "magnetoreception_train",
        "magnetoreception_exp",
        "onboarding",
    ]
    for prefix in allowed:
        if name == prefix or name.startswith(prefix) or prefix in name:
            return name
    if "magnetoreception" in name:
        return name
    return None


def _as_int(value):
    if value is None or value is False:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def check_bbox_listener(cfg: dict, state: dict | None, hb: dict | None) -> dict:
    """Catch orphaned bbox listeners after video_config restarts."""
    require_session = cfg.get("require_session_for_heartbeat_and_files", True)
    listener_stale = float(cfg.get("bbox_listener_stale_sec", 90))
    exp_name = _bbox_experiment(cfg, state, hb)
    running = session_running(state)
    phase = None
    attached_gen = None
    last_bbox = None
    if state:
        phase = nested_get(state, "session", "magnetoreception_phase") or nested_get(
            state, "session", "onboarding_phase"
        )
        attached_gen = nested_get(state, "session", "bbox_listener_generation")
        last_bbox = nested_get(state, "session", "last_bbox_ts")
    if hb:
        if phase is None:
            phase = hb.get("phase")
        if attached_gen is None:
            attached_gen = hb.get("bbox_listener_generation")
        if last_bbox is None:
            last_bbox = hb.get("last_bbox_ts")
    phase = str(phase).lower() if phase is not None else None

    obs_gen = nested_get(state, "video", "observers_generation") if state else None
    obs_gen_i = _as_int(obs_gen)
    attached_gen_i = _as_int(attached_gen)

    details = {
        "experiment": exp_name,
        "session_running": running,
        "phase": phase,
        "observers_generation": obs_gen_i if obs_gen_i is not None else obs_gen,
        "bbox_listener_generation": attached_gen_i if attached_gen_i is not None else attached_gen,
        "last_bbox_ts": last_bbox,
        "listener_stale_sec": listener_stale,
    }

    if require_session and not running:
        return skip("bbox_listener", "no session running; bbox listener not required", details)
    if exp_name is None:
        return skip("bbox_listener", "experiment does not use bbox zone listeners", details)

    if attached_gen is None and last_bbox is None:
        return result(
            "bbox_listener",
            True,
            "warn",
            "bbox listener telemetry missing; restart the experiment to enable this check",
            details,
        )

    if obs_gen_i is not None and attached_gen_i is not None and obs_gen_i != attached_gen_i:
        return result(
            "bbox_listener",
            False,
            "fail",
            (
                f"bbox listener orphaned after video restart "
                f"(observers_generation {obs_gen_i} != attached {attached_gen_i})"
            ),
            details,
        )

    if last_bbox is None:
        return result(
            "bbox_listener",
            False,
            "fail",
            "experiment is running but last_bbox_ts is missing (listener never ticked)",
            details,
        )

    bbox_age = time.time() - float(last_bbox)
    details["bbox_age_sec"] = round(bbox_age, 1)
    if bbox_age > listener_stale:
        return result(
            "bbox_listener",
            False,
            "fail",
            f"bbox listener stale ({bbox_age:.0f}s > {listener_stale:.0f}s); zone commands will not fire",
            details,
        )

    return result(
        "bbox_listener",
        True,
        "ok",
        f"bbox listener fresh ({bbox_age:.0f}s old, phase {phase or '?'})",
        details,
    )


def _disk_usage(path: Path) -> dict | None:
    check_path = path
    while not check_path.exists() and check_path != check_path.parent:
        check_path = check_path.parent
    if not check_path.exists():
        return None
    usage = shutil.disk_usage(check_path)
    used_pct = (usage.used / usage.total) * 100 if usage.total else 0
    return {
        "path": str(path),
        "checked_path": str(check_path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_pct": round(used_pct, 1),
    }


def check_disk(cfg: dict) -> dict:
    warn_pct = float(cfg.get("disk_warn_pct", 85))
    fail_pct = float(cfg.get("disk_fail_pct", 95))
    mounts = [
        _disk_usage(resolve_path(cfg, "session_data_root", "/data/reptilearn/sessions")),
        _disk_usage(resolve_path(cfg, "media_dir", "/data/reptilearn/media")),
    ]
    # Deduplicate by checked_path so sessions/ and media/ on the same volume count once.
    seen = {}
    for item in mounts:
        if item is None:
            continue
        seen[item["checked_path"]] = item
    volumes = list(seen.values())
    details = {"warn_pct": warn_pct, "fail_pct": fail_pct, "volumes": volumes}

    if not volumes:
        return result("disk", False, "fail", "could not measure disk usage", details)

    worst = max(v["used_pct"] for v in volumes)
    if worst >= fail_pct:
        return result("disk", False, "fail", f"disk {worst:.1f}% used (>= {fail_pct:.0f}%)", details)
    if worst >= warn_pct:
        return result("disk", True, "warn", f"disk {worst:.1f}% used (>= {warn_pct:.0f}%)", details)
    return result("disk", True, "ok", f"disk {worst:.1f}% used", details)


def check_gpu(cfg: dict) -> dict:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "-L"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except FileNotFoundError:
        return result("gpu", False, "fail", "nvidia-smi not found; GPU not visible", {})
    except subprocess.CalledProcessError as exc:
        return result(
            "gpu",
            False,
            "fail",
            "nvidia-smi failed",
            {"returncode": exc.returncode, "output": (exc.output or "")[-500:]},
        )
    except Exception as exc:
        return result("gpu", False, "fail", f"nvidia-smi error: {exc}", {})

    gpus = [line.strip() for line in out.splitlines() if line.strip()]
    details = {"gpus": gpus}
    if not gpus:
        return result("gpu", False, "fail", "nvidia-smi listed no GPUs", details)
    return result("gpu", True, "ok", f"{len(gpus)} GPU(s) visible", details)


def _file_stats(path: Path) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return {"path": str(path), "mtime": st.st_mtime, "size": st.st_size}


def _session_watch_files(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    names = ["events.csv", "session.log", "session_state.json"]
    files = [data_dir / name for name in names if (data_dir / name).exists()]
    files.extend(sorted(data_dir.glob("*.mp4")))
    files.extend(sorted(p for p in data_dir.glob("*.csv") if p.name != "events.csv"))
    return files


def check_files(cfg: dict, state: dict | None, hb: dict | None, persist: bool = True) -> dict:
    require_session = cfg.get("require_session_for_heartbeat_and_files", True)
    stale_sec = float(cfg.get("files_stale_sec", 180))
    snapshot_path = health_dir(cfg) / "files_snapshot.json"
    data_dir = session_data_dir(state, hb)
    recording = is_recording(state)
    running = session_running(state)

    details = {
        "data_dir": str(data_dir) if data_dir else None,
        "session_running": running,
        "is_recording": recording,
        "stale_sec": stale_sec,
    }

    if require_session and not running:
        return skip("files", "no session running; file growth not required", details)
    if require_session and not recording:
        return skip("files", "session running but not recording; file growth not required", details)
    if data_dir is None:
        return result("files", False, "fail", "session data_dir unknown", details)
    if not data_dir.exists():
        return result("files", False, "fail", f"session directory missing: {data_dir}", details)

    watched = _session_watch_files(data_dir)
    current = {}
    for path in watched:
        stats = _file_stats(path)
        if stats:
            current[str(path)] = stats
    details["files"] = current

    prev = {}
    if snapshot_path.exists():
        try:
            prev = json.loads(snapshot_path.read_text())
        except Exception:
            prev = {}

    prev_dir = prev.get("data_dir")
    prev_files = prev.get("files") or {}
    now = time.time()
    grew = []
    newest_mtime = None
    for path_str, stats in current.items():
        mtime = stats["mtime"]
        newest_mtime = mtime if newest_mtime is None else max(newest_mtime, mtime)
        old = prev_files.get(path_str) if prev_dir == str(data_dir) else None
        if old is None:
            continue
        if stats["size"] > old.get("size", 0) or mtime > old.get("mtime", 0) + 0.01:
            grew.append(path_str)

    if persist:
        atomic_write_json(
            snapshot_path,
            {"ts": now, "data_dir": str(data_dir), "files": current},
        )

    if not current:
        return result("files", False, "fail", "no session output files found", details)

    details["grew"] = grew
    details["newest_age_sec"] = round(now - newest_mtime, 1) if newest_mtime else None

    if prev_dir != str(data_dir) or not prev_files:
        if persist:
            return result(
                "files",
                True,
                "ok",
                "file snapshot seeded; will compare on next run",
                details,
            )
        if newest_mtime is not None and (now - newest_mtime) <= stale_sec:
            return result(
                "files",
                True,
                "ok",
                f"session files recently written ({now - newest_mtime:.0f}s ago)",
                details,
            )

    if grew:
        return result("files", True, "ok", f"{len(grew)} session file(s) still growing", details)

    if newest_mtime is not None and (now - newest_mtime) <= stale_sec:
        return result(
            "files",
            True,
            "ok",
            f"session files recently written ({now - newest_mtime:.0f}s ago)",
            details,
        )

    return result(
        "files",
        False,
        "fail",
        f"session files not growing for >{stale_sec:.0f}s",
        details,
    )


def list_serial_ports():
    from serial.tools import list_ports

    return list(list_ports.comports())


def match_serial(serial_number: str, ports) -> list:
    return [
        port
        for port in ports
        if port.serial_number and serial_number in port.serial_number
    ]


def is_arduino_port(port) -> bool:
    if getattr(port, "vid", None) == ARDUINO_VID:
        return True
    blob = " ".join(
        str(x)
        for x in (port.description, port.manufacturer, port.product, port.hwid)
        if x
    ).lower()
    return "arduino" in blob or "2341:" in blob


def by_id_for_device(device: str) -> str | None:
    by_id_dir = Path("/dev/serial/by-id")
    if not by_id_dir.exists():
        return None
    try:
        target = Path(device).resolve()
    except OSError:
        target = Path(device)
    for link in by_id_dir.iterdir():
        try:
            if link.resolve() == target:
                return str(link)
        except OSError:
            continue
    return None


def load_arena_config(cfg: dict) -> dict:
    path = resolve_path(cfg, "arena_config", "config/arena_config.json")
    with open(path, "r") as f:
        return json.load(f)


def expected_boards(cfg: dict, arena_conf: dict) -> dict:
    skip = set(cfg.get("skip_serial_numbers") or ["0"])
    names = cfg.get("expected_boards")
    boards = {}
    for name, port_conf in arena_conf.items():
        serial = str(port_conf.get("serial_number", ""))
        if serial in skip or not serial:
            continue
        if names is not None and name not in names:
            continue
        boards[name] = serial
    return boards


def check_arduino(cfg: dict) -> tuple[dict, dict]:
    """Return (check_result, current_inventory_boards)."""
    try:
        arena_conf = load_arena_config(cfg)
        ports = list_serial_ports()
    except Exception as exc:
        return (
            result("arduino", False, "fail", f"could not enumerate Arduino ports: {exc}", {}),
            {},
        )

    expected = expected_boards(cfg, arena_conf)
    current = {}
    missing = []
    ambiguous = []
    present = []
    port_summaries = [
        {
            "device": p.device,
            "description": p.description,
            "serial_number": p.serial_number,
            "vid": getattr(p, "vid", None),
            "pid": getattr(p, "pid", None),
        }
        for p in ports
        if p.serial_number or is_arduino_port(p)
    ]

    for name, serial in expected.items():
        matches = match_serial(serial, ports)
        if len(matches) == 0:
            missing.append(name)
            current[name] = {
                "config_serial": serial,
                "serial_number": None,
                "device": None,
                "by_id": None,
                "status": "missing",
            }
        elif len(matches) > 1:
            ambiguous.append(name)
            current[name] = {
                "config_serial": serial,
                "serial_number": [m.serial_number for m in matches],
                "device": [m.device for m in matches],
                "by_id": None,
                "status": "ambiguous",
            }
        else:
            port = matches[0]
            present.append(name)
            current[name] = {
                "config_serial": serial,
                "serial_number": port.serial_number,
                "device": port.device,
                "by_id": by_id_for_device(port.device),
                "status": "present",
            }

    matched_serials = set()
    for info in current.values():
        sn = info.get("serial_number")
        if isinstance(sn, str):
            matched_serials.add(sn)

    extras = []
    for port in ports:
        if not is_arduino_port(port):
            continue
        if not port.serial_number:
            extras.append({"device": port.device, "serial_number": None, "reason": "no serial"})
            continue
        if port.serial_number in matched_serials:
            continue
        if any(cfg_sn in port.serial_number for cfg_sn in expected.values()):
            continue
        extras.append(
            {
                "device": port.device,
                "serial_number": port.serial_number,
                "description": port.description,
            }
        )

    details = {
        "expected": expected,
        "boards": current,
        "ports": port_summaries,
        "extras": extras,
    }

    problems = []
    if missing:
        problems.append("missing: " + ", ".join(missing))
    if ambiguous:
        problems.append("ambiguous/switched ID: " + ", ".join(ambiguous))
    if extras:
        extra_ids = ", ".join(e.get("serial_number") or e.get("device") for e in extras)
        problems.append("unexpected Arduino: " + extra_ids)

    if problems:
        return result("arduino", False, "fail", "; ".join(problems), details), current
    return (
        result(
            "arduino",
            True,
            "ok",
            f"{len(present)} Arduino board(s) uniquely matched",
            details,
        ),
        current,
    )


def check_arduino_id(cfg: dict, current_boards: dict, persist: bool = True) -> dict:
    inv_path = health_dir(cfg) / "arduino_inventory.json"
    details = {"inventory_path": str(inv_path), "current": current_boards}

    present = {
        name: info
        for name, info in current_boards.items()
        if info.get("status") == "present" and isinstance(info.get("serial_number"), str)
    }

    if not inv_path.exists():
        if present and persist:
            atomic_write_json(
                inv_path,
                {"ts": time.time(), "boards": present},
            )
            return result(
                "arduino_id",
                True,
                "ok",
                "Arduino serial inventory seeded",
                details,
            )
        return skip("arduino_id", "no Arduino inventory to compare", details)

    try:
        previous = json.loads(inv_path.read_text())
    except Exception as exc:
        return result("arduino_id", False, "fail", f"could not read inventory: {exc}", details)

    prev_boards = previous.get("boards") or {}
    switched = []
    tty_only = []
    for name, info in present.items():
        old = prev_boards.get(name)
        if not old:
            continue
        if old.get("serial_number") and old["serial_number"] != info["serial_number"]:
            switched.append(
                {
                    "board": name,
                    "was": old.get("serial_number"),
                    "now": info["serial_number"],
                }
            )
        elif old.get("device") and old.get("device") != info.get("device"):
            tty_only.append(
                {
                    "board": name,
                    "was": old.get("device"),
                    "now": info.get("device"),
                }
            )

    if persist:
        merged = dict(prev_boards)
        merged.update(present)
        atomic_write_json(inv_path, {"ts": time.time(), "boards": merged})

    details["switched"] = switched
    details["tty_remap"] = tty_only

    if switched:
        names = ", ".join(item["board"] for item in switched)
        return result(
            "arduino_id",
            False,
            "fail",
            f"Arduino USB serial changed for: {names}",
            details,
        )
    if tty_only:
        names = ", ".join(item["board"] for item in tty_only)
        return result(
            "arduino_id",
            True,
            "ok",
            f"ttyACM remapped for {names} (serial unchanged)",
            details,
        )
    return result("arduino_id", True, "ok", "Arduino USB serials match inventory", details)


def run_checks(cfg: dict, persist: bool = True) -> list[dict]:
    state, state_error = fetch_state(cfg)
    hb = load_heartbeat(cfg)
    checks = [
        check_process(cfg, state, state_error),
        check_heartbeat(cfg, state, hb),
        check_disk(cfg),
        check_gpu(cfg),
        check_files(cfg, state, hb, persist=persist),
        check_bbox_listener(cfg, state, hb),
    ]
    arduino_result, current_boards = check_arduino(cfg)
    checks.append(arduino_result)
    checks.append(check_arduino_id(cfg, current_boards, persist=persist))
    return checks


def build_report(checks: list[dict]) -> dict:
    failed = [c["id"] for c in checks if c["severity"] == "fail"]
    warned = [c["id"] for c in checks if c["severity"] == "warn"]
    return {
        "ts": time.time(),
        "ok": len(failed) == 0,
        "failed": failed,
        "warned": warned,
        "checks": checks,
    }


def previous_failed_ids(status_path: Path) -> set[str] | None:
    """Return failed check ids from the last written status.json, or None if unknown."""
    if not status_path.exists():
        return None
    try:
        prev = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(prev, dict):
        return None
    failed = prev.get("failed")
    if failed is None:
        return set()
    return {str(item) for item in failed}


def write_outputs(cfg: dict, report: dict) -> None:
    dest = health_dir(cfg)
    dest.mkdir(parents=True, exist_ok=True)
    status_path = dest / "status.json"
    prev_failed = previous_failed_ids(status_path)
    new_failed = {str(item) for item in report["failed"]}
    atomic_write_json(status_path, report)
    if not report["ok"] and prev_failed != new_failed:
        alert_line = json.dumps(
            {
                "ts": report["ts"],
                "failed": report["failed"],
                "summaries": {
                    c["id"]: c["summary"] for c in report["checks"] if c["id"] in report["failed"]
                },
            },
            default=str,
        )
        with open(dest / "alerts.jsonl", "a") as f:
            f.write(alert_line + "\n")


def format_console(report: dict) -> str:
    status = "OK" if report["ok"] else "UNHEALTHY"
    lines = [f"ReptiLearn health: {status}"]
    if report["failed"]:
        lines.append("failed: " + ", ".join(report["failed"]))
    if report.get("warned"):
        lines.append("warned: " + ", ".join(report["warned"]))
    for check in report["checks"]:
        mark = {"ok": "ok", "warn": "warn", "fail": "FAIL", "skip": "skip"}.get(
            check["severity"], check["severity"]
        )
        lines.append(f"  [{mark}] {check['id']}: {check['summary']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReptiLearn deterministic health monitor")
    parser.add_argument("--config", type=Path, default=None, help="Path to health config.json")
    parser.add_argument("--json", action="store_true", help="Print full report JSON to stdout")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
        checks = run_checks(cfg)
        report = build_report(checks)
        write_outputs(cfg, report)
    except Exception as exc:
        sys.stderr.write(f"health monitor error: {exc}\n")
        return EXIT_ERROR

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_console(report))

    return EXIT_OK if report["ok"] else EXIT_UNHEALTHY


if __name__ == "__main__":
    raise SystemExit(main())
