"""Score a magnetoreception trial from command logs and magnetometer.csv.

The board ack in session.log is the command. events.csv arena_command is the
publish. Magnetometer rows are the field. A trial stays bad once a reason is
latched; later good samples do not clear it.
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ACK_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[arena/info/Magnets (Forward|Reverse|Stop)\]"
)
LOG_TIME_FORMAT = "%Y-%d-%m %H:%M:%S"
COMMANDS = {"forward", "reverse", "stop"}
# session.log timestamps are whole seconds, so an ack can look up to 1s earlier
# than the events.csv publish it confirms.
ACK_CLOCK_SLACK_SEC = 1.0
TRIAL_HEALTH_IDS = ("arduino", "arduino_id", "heartbeat", "bbox_listener")
OPEN_PHASES = {"a_delay", "b", "b_wait", "b_hold", "c", "d"}
STATUS_FIELDS = (
    "trial_status",
    "trial_status_reasons",
    "trial_status_detail",
    "last_trial_status",
    "last_trial_status_trial",
    "last_trial_status_reasons",
    "last_trial_status_detail",
)


@dataclass(frozen=True)
class MagnetThresholds:
    forward_min_uT: float = 90.0
    reverse_max_uT: float = 20.0
    min_pass_fraction: float = 2.0 / 3.0
    settle_sec: float = 5.0
    pair_window_sec: float = 3.0
    alert_min_samples: int = 1
    timezone: str = "Asia/Jerusalem"


@dataclass(frozen=True)
class Command:
    time: float
    kind: str


@dataclass(frozen=True)
class Sample:
    time: float
    trial: int | None
    b_uT: float


def load_thresholds(config_path: Path | None = None) -> MagnetThresholds:
    path = config_path or (Path(__file__).resolve().parents[1] / "health" / "config.json")
    raw = {}
    timezone = "Asia/Jerusalem"
    if path.exists():
        try:
            cfg = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            cfg = {}
        if isinstance(cfg, dict):
            raw = cfg.get("magnet") or {}
            timezone = str(cfg.get("day_summary_timezone") or timezone)
    return MagnetThresholds(
        forward_min_uT=float(raw.get("forward_min_uT", 90)),
        reverse_max_uT=float(raw.get("reverse_max_uT", 20)),
        min_pass_fraction=float(raw.get("min_pass_fraction", 2.0 / 3.0)),
        settle_sec=float(raw.get("settle_sec", 5)),
        pair_window_sec=float(raw.get("pair_window_sec", 3)),
        alert_min_samples=int(raw.get("alert_min_samples", 1)),
        timezone=timezone,
    )


def health_directory(config_path: Path | None = None) -> Path:
    path = config_path or (Path(__file__).resolve().parents[1] / "health" / "config.json")
    default = Path("/data/reptilearn/health")
    if not path.exists():
        return default
    try:
        cfg = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default
    return Path((cfg or {}).get("health_dir") or default)


def _parse_log_time(text: str, timezone: str) -> float | None:
    try:
        parsed = datetime.strptime(text, LOG_TIME_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo(timezone)).timestamp()


def _command_kind(value) -> str | None:
    parsed = value
    for _ in range(2):
        if not isinstance(parsed, str):
            break
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, list) and parsed:
        kind = str(parsed[0]).strip().lower()
        if kind in COMMANDS:
            return kind
    return None


def parse_acks(path: Path, timezone: str) -> list[Command]:
    if not path.exists():
        return []
    acks = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        match = ACK_RE.search(line)
        if match is None:
            continue
        stamp = _parse_log_time(match.group(1), timezone)
        if stamp is None:
            continue
        acks.append(Command(stamp, match.group(2).lower()))
    acks.sort(key=lambda item: item.time)
    return acks


def parse_publishes(path: Path) -> list[Command]:
    if not path.exists():
        return []
    publishes = []
    try:
        handle = path.open(newline="")
    except OSError:
        return []
    with handle:
        reader = csv.DictReader(handle)
        try:
            rows = list(reader)
        except csv.Error:
            return publishes
    for row in rows:
        if (row.get("event") or "") != "arena_command":
            continue
        kind = _command_kind(row.get("value"))
        if kind is None:
            continue
        try:
            stamp = float(row.get("time"))
        except (TypeError, ValueError):
            continue
        publishes.append(Command(stamp, kind))
    publishes.sort(key=lambda item: item.time)
    return publishes


def parse_samples(path: Path) -> list[Sample]:
    if not path.exists():
        return []
    samples = []
    try:
        handle = path.open(newline="")
    except OSError:
        return []
    with handle:
        reader = csv.DictReader(handle)
        try:
            rows = list(reader)
        except csv.Error:
            return samples
    for row in rows:
        try:
            stamp = float(row.get("time"))
            field = float(row.get("b_uT"))
        except (TypeError, ValueError):
            continue
        trial_raw = (row.get("trial") or "").strip()
        trial = None
        if trial_raw:
            try:
                trial = int(float(trial_raw))
            except ValueError:
                trial = None
        samples.append(Sample(stamp, trial, field))
    samples.sort(key=lambda item: item.time)
    return samples


def _paired(ack: Command, pub: Command, window: float) -> bool:
    if ack.kind != pub.kind:
        return False
    delta = ack.time - pub.time
    return -ACK_CLOCK_SLACK_SEC <= delta <= window


def _has_publish(ack: Command, publishes: list[Command], window: float) -> bool:
    return any(_paired(ack, pub, window) for pub in publishes)


def _has_ack(pub: Command, acks: list[Command], window: float) -> bool:
    return any(_paired(ack, pub, window) for ack in acks)


def _sample_in_trial(sample: Sample, trial: int | None) -> bool:
    if trial is None or sample.trial is None:
        return True
    return sample.trial == int(trial)


def _passes(kind: str, field: float, thresholds: MagnetThresholds) -> bool:
    if kind == "forward":
        return field > thresholds.forward_min_uT
    if kind == "reverse":
        return field < thresholds.reverse_max_uT
    return False


def _ratio_ok(passed: int, total: int, fraction: float) -> bool:
    if total <= 0:
        return False
    return (passed / total) >= float(fraction) - 1e-6


def _detail_for(counts: dict[str, tuple[int, int]], thresholds: MagnetThresholds, waiting_kind: str | None) -> str:
    parts = []
    if counts.get("forward", (0, 0))[1]:
        passed, total = counts["forward"]
        parts.append(
            f"forward {passed}/{total} above {thresholds.forward_min_uT:g}"
        )
    if counts.get("reverse", (0, 0))[1]:
        passed, total = counts["reverse"]
        parts.append(
            f"reverse {passed}/{total} under {thresholds.reverse_max_uT:g}"
        )
    if parts:
        return "; ".join(parts)
    if waiting_kind in COMMANDS and waiting_kind != "stop":
        return f"{waiting_kind}: waiting for a sample"
    return ""


def _empty(detail: str = "") -> dict:
    return {
        "status": "good",
        "reasons": [],
        "detail": detail,
        "passed": 0,
        "scored": 0,
        "commanded_on": False,
    }


def score_window(
    data_dir: Path,
    t_start: float,
    t_end: float,
    *,
    trial: int | None = None,
    closed: bool = False,
    thresholds: MagnetThresholds | None = None,
    now: float | None = None,
) -> dict:
    """Score magnet samples and command pairing inside [t_start, t_end]."""
    thresholds = thresholds or load_thresholds()
    now = time.time() if now is None else now
    data_dir = Path(data_dir)
    acks = parse_acks(data_dir / "session.log", thresholds.timezone)
    publishes = parse_publishes(data_dir / "events.csv")
    samples = parse_samples(data_dir / "magnetometer.csv")

    reasons: list[str] = []
    for ack in acks:
        if t_start - 1e-3 <= ack.time <= t_end and not _has_publish(
            ack, publishes, thresholds.pair_window_sec
        ):
            reasons.append("command_mismatch")
            break
    for pub in publishes:
        if not (t_start <= pub.time <= t_end):
            continue
        if _has_ack(pub, acks, thresholds.pair_window_sec):
            continue
        if not closed and now < pub.time + thresholds.pair_window_sec:
            continue
        reasons.append("command_unacked")
        break

    relevant = [ack for ack in acks if ack.time <= t_end]
    counts = {"forward": [0, 0], "reverse": [0, 0]}
    commanded_on = False
    waiting_kind = None
    for index, ack in enumerate(relevant):
        if ack.kind == "stop":
            continue
        nxt = relevant[index + 1].time if index + 1 < len(relevant) else t_end
        seg_end = min(nxt, t_end)
        if seg_end <= t_start:
            continue
        commanded_on = True
        waiting_kind = ack.kind
        ready = ack.time + thresholds.settle_sec
        following = relevant[index + 1].time if index + 1 < len(relevant) else None
        for sample in samples:
            if sample.time < max(ready, t_start) or sample.time > t_end:
                continue
            if following is not None and sample.time >= following:
                continue
            if not _sample_in_trial(sample, trial):
                continue
            counts[ack.kind][1] += 1
            if _passes(ack.kind, sample.b_uT, thresholds):
                counts[ack.kind][0] += 1

    passed = counts["forward"][0] + counts["reverse"][0]
    scored = counts["forward"][1] + counts["reverse"][1]
    count_pairs = {
        kind: (values[0], values[1])
        for kind, values in counts.items()
        if values[1]
    }
    detail = _detail_for(count_pairs, thresholds, waiting_kind if commanded_on else None)

    min_samples = 1 if closed else max(1, thresholds.alert_min_samples)
    if commanded_on and scored >= min_samples and not _ratio_ok(
        passed, scored, thresholds.min_pass_fraction
    ):
        reasons.append("magnet")
    elif closed and commanded_on and scored == 0:
        reasons.append("magnet_short")
        if waiting_kind:
            detail = f"{waiting_kind}: no magnetometer samples"

    # Preserve first-seen order while dropping duplicates.
    unique = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return {
        "status": "bad" if unique else "good",
        "reasons": unique,
        "detail": detail,
        "passed": passed,
        "scored": scored,
        "commanded_on": commanded_on,
    }


def score_current_command(
    data_dir: Path,
    thresholds: MagnetThresholds | None = None,
    now: float | None = None,
) -> dict | None:
    """Score the command that is on now. None when the magnets are off."""
    thresholds = thresholds or load_thresholds()
    now = time.time() if now is None else now
    data_dir = Path(data_dir)
    acks = parse_acks(data_dir / "session.log", thresholds.timezone)
    publishes = parse_publishes(data_dir / "events.csv")
    latest_ack = acks[-1] if acks else None
    latest_pub = publishes[-1] if publishes else None

    publish_is_newer = latest_pub is not None and (
        latest_ack is None or latest_pub.time > latest_ack.time + ACK_CLOCK_SLACK_SEC
    )
    if latest_ack is None or publish_is_newer:
        if latest_pub is None or latest_pub.kind == "stop":
            return None
        if now < latest_pub.time + thresholds.pair_window_sec:
            return _empty(f"{latest_pub.kind}: waiting for a sample")
        return {
            "status": "bad",
            "reasons": ["command_unacked"],
            "detail": f"{latest_pub.kind}: command not acknowledged",
            "passed": 0,
            "scored": 0,
            "commanded_on": True,
        }

    if latest_ack.kind == "stop":
        return None
    return score_window(
        data_dir,
        latest_ack.time,
        now,
        closed=False,
        thresholds=thresholds,
        now=now,
    )


def current_health_reasons(t_start: float, t_end: float, health_dir: Path | None = None) -> list[str]:
    """Health-check ids that failed during the trial and are still worth latching."""
    dest = Path(health_dir) if health_dir is not None else health_directory()
    found: list[str] = []

    def add(ids) -> None:
        for item in ids or []:
            name = str(item)
            if name in TRIAL_HEALTH_IDS and name not in found:
                found.append(name)

    alerts = dest / "alerts.jsonl"
    if alerts.exists():
        try:
            lines = alerts.read_text(errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                stamp = float(payload.get("ts"))
            except (TypeError, ValueError):
                continue
            if t_start <= stamp <= t_end:
                add(payload.get("failed"))

    status_path = dest / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text())
        except (OSError, json.JSONDecodeError):
            status = None
        if isinstance(status, dict):
            add(status.get("failed"))
    return found


def _as_reasons(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item) for item in value if str(item).strip()]


def _union(existing, extra) -> list[str]:
    merged = []
    for item in _as_reasons(existing) + _as_reasons(extra):
        if item not in merged:
            merged.append(item)
    return merged


def _session_dir() -> Path | None:
    import experiment as exp

    try:
        data_dir = exp.session_state["data_dir"]
    except Exception:
        return None
    if not data_dir:
        return None
    return Path(data_dir)


def _publish_status(owner) -> None:
    import experiment as exp

    for name in STATUS_FIELDS:
        exp.session_state[owner._state_key(name)] = getattr(owner, name, None)


def _apply_verdict(owner, verdict: dict, t_start: float, t_end: float) -> None:
    health = current_health_reasons(t_start, t_end)
    incoming = _union(verdict.get("reasons"), health)
    reasons = _union(getattr(owner, "trial_status_reasons", None), incoming)
    owner.trial_status = "bad" if reasons else "good"
    owner.trial_status_reasons = reasons
    detail = verdict.get("detail") or ""
    if verdict.get("status") == "bad" and detail:
        owner.trial_status_detail = detail
    elif not getattr(owner, "trial_status_detail", None):
        owner.trial_status_detail = detail


def find_trial_start(data_dir: Path, trial: int) -> float | None:
    path = Path(data_dir) / "events.csv"
    if not path.exists():
        return None
    found = None
    try:
        handle = path.open(newline="")
    except OSError:
        return None
    with handle:
        reader = csv.DictReader(handle)
        try:
            rows = list(reader)
        except csv.Error:
            return found
    for row in rows:
        if row.get("event") != "magnetoreception/trial_start":
            continue
        try:
            value = json.loads(row.get("value") or "null")
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        try:
            if int(value.get("trial")) != int(trial):
                continue
            found = float(row.get("time"))
        except (TypeError, ValueError):
            continue
    return found


def trial_status_logged(data_dir: Path, trial: int) -> bool:
    path = Path(data_dir) / "events.csv"
    if not path.exists():
        return False
    try:
        handle = path.open(newline="")
    except OSError:
        return False
    with handle:
        reader = csv.DictReader(handle)
        try:
            rows = list(reader)
        except csv.Error:
            return False
    for row in rows:
        if row.get("event") != "magnetoreception/trial_status":
            continue
        try:
            value = json.loads(row.get("value") or "null")
        except json.JSONDecodeError:
            continue
        try:
            if isinstance(value, dict) and int(value.get("trial")) == int(trial):
                return True
        except (TypeError, ValueError):
            continue
    return False


def format_status_line(trial: int, status: str, reasons, detail: str) -> str:
    if status != "bad":
        return f"Trial {trial}: status good"
    reason_text = ", ".join(_as_reasons(reasons)) or "bad"
    if detail:
        return f"Trial {trial}: status bad: {reason_text} ({detail})"
    return f"Trial {trial}: status bad: {reason_text}"


def restore_open_trial(owner) -> None:
    data_dir = _session_dir()
    trial = int(getattr(owner, "trial_num", 0) or 0)
    owner._trial_status_written = False
    owner.trial_started_at = None
    if data_dir is None or trial <= 0:
        return
    already_logged = trial_status_logged(data_dir, trial)
    if getattr(owner, "phase", None) in OPEN_PHASES:
        owner.trial_started_at = find_trial_start(data_dir, trial) or time.time()
        owner._trial_status_written = already_logged
    elif already_logged:
        owner._trial_status_written = True


def refresh_open_trial(owner) -> None:
    if getattr(owner, "_trial_status_written", False):
        return
    t_start = getattr(owner, "trial_started_at", None)
    if not t_start:
        return
    data_dir = _session_dir()
    if data_dir is None:
        return
    t_end = time.time()
    verdict = score_window(
        data_dir,
        float(t_start),
        t_end,
        trial=getattr(owner, "trial_num", None),
        closed=False,
    )
    _apply_verdict(owner, verdict, float(t_start), t_end)
    _publish_status(owner)


def commit_trial_status(owner) -> None:
    if getattr(owner, "_trial_status_written", False):
        return
    trial = int(getattr(owner, "trial_num", 0) or 0)
    if trial <= 0:
        return
    data_dir = _session_dir()
    if data_dir is None:
        return
    if not getattr(owner, "trial_started_at", None):
        owner.trial_started_at = find_trial_start(data_dir, trial)
    t_start = getattr(owner, "trial_started_at", None)
    if not t_start:
        return
    t_end = time.time()
    try:
        verdict = score_window(
            data_dir,
            float(t_start),
            t_end,
            trial=trial,
            closed=True,
        )
        _apply_verdict(owner, verdict, float(t_start), t_end)
        owner._trial_status_written = True
        owner.last_trial_status = owner.trial_status
        owner.last_trial_status_trial = trial
        owner.last_trial_status_reasons = list(owner.trial_status_reasons or [])
        owner.last_trial_status_detail = owner.trial_status_detail or ""
        owner.log.info(
            format_status_line(
                trial,
                owner.trial_status,
                owner.trial_status_reasons,
                owner.trial_status_detail or "",
            )
        )
        owner._log_event(
            "magnetoreception/trial_status",
            {
                "trial": trial,
                "status": owner.trial_status,
                "reasons": list(owner.trial_status_reasons or []),
                "detail": owner.trial_status_detail or "",
            },
        )
        if hasattr(owner, "_sync_session_state"):
            owner._sync_session_state()
        else:
            _publish_status(owner)
    except Exception:
        owner._trial_status_written = False
        owner.log.exception("Failed to record trial status")
