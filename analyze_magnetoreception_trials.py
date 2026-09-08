#!/usr/bin/env python3
"""
Analyze magnetoreception experiment trial success from session logs or events CSV.

Successful trials are those where the animal chose the magnet-aligned side at point B:
  - CSV: magnetoreception/point_b events with "reason": "correct_choice"
  - Log: lines like "Magnet north toward B1 and animal at B1 -> right feeder"
         or "... B2 and animal at B2 -> left feeder"

For events CSV files, the script also reports:
  - Left vs right feeder counts among successful trials
  - A→B travel time (magnetoreception/trial_start → magnetoreception/point_b)

Usage:
    python analyze_magnetoreception_trials.py
    python analyze_magnetoreception_trials.py session_exp1.log events_exp2.csv events_exp3.csv
    python analyze_magnetoreception_trials.py session_exp1.log --output trials_summary.png
    python analyze_magnetoreception_trials.py --bulk events_exp2.csv events_exp3.csv
    python analyze_magnetoreception_trials.py --bulk ./sessions/ -o combined.png
    python analyze_magnetoreception_trials.py --bulk --sessions-dir /data/reptilearn/sessions -o combined.png

All panels (success, per-trial outcomes, feeder direction, A→B travel time) are saved
in a single figure. The A→B panel shows both mean and median reference lines.

Calendar-day JSON (scored B-choice trials only; onboarding point_b is excluded):
    python analyze_magnetoreception_trials.py --day-summary --sessions-dir /data/reptilearn/sessions
    python analyze_magnetoreception_trials.py --day-summary 2026-08-31 --json-out day.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
import pandas as pd

LOG_TIMESTAMP = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\w+\s+\w+\s+"
)
TRIAL_AT_B = re.compile(r"Trial (\d+): at B[12], closing back doors")
FEEDER_OUTCOME = re.compile(
    r"Magnet north toward (B[12]) and animal at (B[12]) -> "
    r"(right feeder|left feeder|no feeder)"
)
FEEDER_OUTCOME_EXP = re.compile(
    r"Magnet (?:forward|reverse) and animal at (B[12]) -> "
    r"(right feeder|left feeder|no feeder|feeder limit, no dispense)"
)
SESSION_START_LOG = re.compile(
    r"Starting magnetoreception (?:experiment|training)"
    r"|Running experiment magentoreception_exp"
)
EXP_SESSION_DIR = re.compile(r"^exp_(\d+)_")


@dataclass
class TrialOutcome:
    session_idx: int
    trial: int
    global_idx: int
    success: bool
    timestamp: pd.Timestamp | None
    zone: str | None
    magnet_direction: str | None
    reason: str | None
    feeder: str | None = None
    a_to_b_seconds: float | None = None


SESSION_START_EVENTS = {
    "session/run",
    "session/continue",
    "magnetoreception/experiment_start",
    "magnetoreception_training/experiment_start",
}

SUPPORTED_SUFFIXES = {".csv", ".log", ".txt"}
DIRECTORY_SCAN_SUFFIXES = {".csv", ".log"}
A_TO_B_YLIM_SECONDS = 300
A_TO_B_TREND_MIN_WINDOW = 5
A_TO_B_TREND_MAX_WINDOW = 15
ACTIVE_DAY_MIN_TRIALS = 5
FEEDER_SIDE_COLORS = {"left": "#9467bd", "right": "#ff7f0e"}
FEEDER_SIDE_UNKNOWN_COLOR = "#bbbbbb"
SUCCESS_OUTLINE_COLOR = "#2ca02c"
FAILURE_OUTLINE_COLOR = "#d62728"
ZONE_TO_FEEDER_SIDE = {"B1": "right", "B2": "left"}
LOG_OUTCOME_TO_FEEDER = {
    "right feeder": "right",
    "left feeder": "left",
}
PANELS = ("success", "learning_curve", "feeder", "a_to_b", "all")
PANEL_LABELS = {
    "success": "Success rate",
    "learning_curve": "Learning curve",
    "feeder": "Right / left split",
    "a_to_b": "A→B travel time",
    "all": "All panels",
}
TRAIN_SESSION_DIR = re.compile(r"^train_\d+_")
DEFAULT_DAY_TZ = "Asia/Jerusalem"
DEFAULT_SESSIONS_DIR = Path("/data/reptilearn/sessions")


def _parse_event_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _normalize_zone(zone) -> str | None:
    if zone is None or (isinstance(zone, float) and pd.isna(zone)):
        return None
    zone_text = str(zone).strip().strip('"').upper()
    if zone_text in ZONE_TO_FEEDER_SIDE:
        return zone_text
    return None


def _normalize_feeder_side(feeder) -> str | None:
    if feeder is None or (isinstance(feeder, float) and pd.isna(feeder)):
        return None
    side = str(feeder).strip().strip('"').lower()
    if side in FEEDER_SIDE_COLORS:
        return side
    return None


def _infer_feeder_from_event(value: dict) -> str | None:
    feeder = _normalize_feeder_side(value.get("feeder"))
    if feeder is not None:
        return feeder
    if value.get("left_feeder") is not None:
        return "left"
    if value.get("right_feeder") is not None:
        return "right"
    return None


def _session_key(session_idx: int, trial: int) -> tuple[int, int]:
    return session_idx, trial


def _detect_file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".log", ".txt"}:
        return "log"
    raise ValueError(f"Unsupported file type: {path}")


def parse_session_log(path: Path) -> list[TrialOutcome]:
    outcomes: list[TrialOutcome] = []
    session_idx = 0
    current_trial: int | None = None
    global_idx = 0

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if SESSION_START_LOG.search(line):
                session_idx += 1

            trial_match = TRIAL_AT_B.search(line)
            if trial_match:
                current_trial = int(trial_match.group(1))
                continue

            outcome_match = FEEDER_OUTCOME.search(line)
            if outcome_match:
                zone = outcome_match.group(2)
                outcome_text = outcome_match.group(3)
            else:
                outcome_match = FEEDER_OUTCOME_EXP.search(line)
                if not outcome_match:
                    continue
                zone = outcome_match.group(1)
                outcome_text = outcome_match.group(2)

            success = outcome_text in {"right feeder", "left feeder"}
            ts_match = LOG_TIMESTAMP.match(line)
            timestamp = (
                pd.to_datetime(ts_match.group(1)) if ts_match else None
            )
            zone = _normalize_zone(zone)
            feeder = LOG_OUTCOME_TO_FEEDER.get(outcome_text)
            global_idx += 1
            trial = current_trial if current_trial is not None else global_idx

            outcomes.append(
                TrialOutcome(
                    session_idx=max(session_idx, 1),
                    trial=trial,
                    global_idx=global_idx,
                    success=success,
                    timestamp=timestamp,
                    zone=zone,
                    magnet_direction=None,
                    reason="correct_choice" if success else "incorrect_side",
                    feeder=feeder,
                )
            )
            current_trial = None

    return outcomes


def parse_events_csv(path: Path) -> list[TrialOutcome]:
    df = pd.read_csv(path)
    outcomes: list[TrialOutcome] = []
    session_idx = 0
    global_idx = 0
    trial_start_times: dict[tuple[int, int], float] = {}

    for _, row in df.iterrows():
        event = row["event"]
        if event in SESSION_START_EVENTS:
            session_idx += 1
            trial_start_times = {}

        if event == "magnetoreception/trial_start":
            value = _parse_event_value(row["value"])
            trial = int(value["trial"])
            trial_start_times[_session_key(max(session_idx, 1), trial)] = float(
                row["time"]
            )
            continue

        if event != "magnetoreception/point_b":
            continue

        value = _parse_event_value(row["value"])
        reason = value.get("reason")
        success = reason == "correct_choice"
        trial = int(value.get("trial", global_idx + 1))
        global_idx += 1
        start_time = trial_start_times.get(_session_key(max(session_idx, 1), trial))
        a_to_b_seconds = (
            float(row["time"]) - start_time if start_time is not None else None
        )
        zone = _normalize_zone(value.get("zone"))
        feeder = _infer_feeder_from_event(value)

        outcomes.append(
            TrialOutcome(
                session_idx=max(session_idx, 1),
                trial=trial,
                global_idx=global_idx,
                success=success,
                timestamp=pd.to_datetime(row["time"], unit="s", utc=True),
                zone=zone,
                magnet_direction=value.get("magnet_direction"),
                reason=reason,
                feeder=feeder,
                a_to_b_seconds=a_to_b_seconds,
            )
        )

    return outcomes


def load_outcomes(path: Path) -> pd.DataFrame:
    kind = _detect_file_kind(path)
    if kind == "log":
        records = parse_session_log(path)
    else:
        records = parse_events_csv(path)

    if not records:
        return pd.DataFrame(
            columns=[
                "session_idx",
                "trial",
                "global_idx",
                "success",
                "timestamp",
                "zone",
                "magnet_direction",
                "reason",
                "feeder",
                "a_to_b_seconds",
            ]
        )

    df = pd.DataFrame([vars(r) for r in records])
    df["source"] = path.name
    return df


def collect_input_paths(
    paths: list[Path],
    recursive: bool = True,
) -> list[Path]:
    collected: list[Path] = []

    for path in paths:
        if path.is_file():
            if path.suffix.lower() in SUPPORTED_SUFFIXES:
                collected.append(path)
            else:
                print(f"Warning: skipping unsupported file type: {path}")
            continue

        if not path.is_dir():
            raise FileNotFoundError(path)

        globber = path.rglob if recursive else path.glob
        for candidate in sorted(globber("*")):
            if (
                candidate.is_file()
                and candidate.suffix.lower() in DIRECTORY_SCAN_SUFFIXES
            ):
                collected.append(candidate)

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in collected:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)

    return unique


def collect_exp_session_paths(sessions_dir: Path) -> list[Path]:
    """Collect exp_N_*/events.csv from a reptiLearn sessions directory."""
    if not sessions_dir.is_dir():
        raise FileNotFoundError(sessions_dir)

    candidates: list[tuple[int, Path]] = []
    for events_path in sessions_dir.glob("exp_*/events.csv"):
        match = EXP_SESSION_DIR.match(events_path.parent.name)
        if match:
            candidates.append((int(match.group(1)), events_path))

    return [path for _, path in sorted(candidates)]


def collect_train_session_paths(sessions_dir: Path) -> list[Path]:
    """Collect train_N_*/events.csv from a reptiLearn sessions directory."""
    if not sessions_dir.is_dir():
        raise FileNotFoundError(sessions_dir)

    paths = [
        p
        for p in sorted(sessions_dir.glob("train_*/events.csv"))
        if TRAIN_SESSION_DIR.match(p.parent.name)
    ]
    return paths


def collect_all_session_events_paths(sessions_dir: Path) -> list[Path]:
    """Collect every session */events.csv (day summaries span sessions)."""
    if not sessions_dir.is_dir():
        raise FileNotFoundError(sessions_dir)
    return sorted(p for p in sessions_dir.glob("*/events.csv") if p.is_file())


def session_kind_from_name(name: str) -> str:
    text = name.lower()
    if "onboarding" in text:
        return "onboarding"
    if "_train" in text or text.startswith("train"):
        return "train"
    if "_exp" in text or text.startswith("exp_"):
        return "exp"
    return "other"


def scored_trials(df: pd.DataFrame) -> pd.DataFrame:
    """Keep point-B trials that have a choice reason (excludes onboarding)."""
    if df.empty or "reason" not in df.columns:
        return df.iloc[0:0].copy()
    reason = df["reason"]
    mask = reason.notna() & (reason.astype(str).str.strip() != "")
    return df.loc[mask].copy()


def _local_dates(df: pd.DataFrame, tz: str) -> pd.Series:
    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return timestamps.dt.tz_convert(tz).dt.date


def filter_outcomes_for_day(df: pd.DataFrame, day: date, tz: str) -> pd.DataFrame:
    if df.empty or "timestamp" not in df.columns:
        return df.iloc[0:0].copy() if not df.empty else df.copy()
    dates = _local_dates(df, tz)
    return df.loc[dates == day].copy()


def parse_day_arg(value: str | None, tz: str) -> date:
    if value is None or value in {"today", ""}:
        return datetime.now(ZoneInfo(tz)).date()
    if value == "yesterday":
        return datetime.now(ZoneInfo(tz)).date() - timedelta(days=1)
    return date.fromisoformat(value)


def _round_or_none(value, digits=1):
    if value is None:
        return None
    return round(float(value), digits)


def _day_block(df: pd.DataFrame, tz: str) -> dict:
    stats = summarize(df)
    breakdown = summarize_outcome_by_side(df)
    timing = summarize_a_to_b_time(df)
    by_side = {}
    for side, side_timing in summarize_a_to_b_time_by_side(df).items():
        by_side[side] = {
            "count": side_timing["count"],
            "mean_seconds": _round_or_none(side_timing["mean_seconds"]),
            "median_seconds": _round_or_none(side_timing["median_seconds"]),
            "median_formatted": format_duration(side_timing["median_seconds"]),
        }
    sessions: list[str] = []
    kind_counts = {"exp": 0, "train": 0, "other": 0}
    if not df.empty:
        labels = []
        if "source_file" in df.columns:
            labels = [str(x) for x in df["source_file"].dropna().unique()]
        elif "source" in df.columns:
            labels = [str(x) for x in df["source"].dropna().unique()]
        sessions = sorted({label.split("/")[0] for label in labels})
        for label in df["source_file"] if "source_file" in df.columns else []:
            kind = session_kind_from_name(str(label))
            if kind not in kind_counts:
                kind = "other"
            kind_counts[kind] += 1

    first_local = None
    last_local = None
    if not df.empty and df["timestamp"].notna().any():
        local_ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dt.tz_convert(tz)
        local_ts = local_ts.dropna()
        if not local_ts.empty:
            first_local = local_ts.min().strftime("%H:%M")
            last_local = local_ts.max().strftime("%H:%M")

    return {
        "trials": stats["total"],
        "successes": stats["successes"],
        "failures": stats["failures"],
        "success_pct": _round_or_none(stats["success_pct"]),
        "success_by_side": breakdown["success"],
        "failure_by_side": breakdown["failure"],
        "a_to_b": {
            "count": timing["count"],
            "mean_seconds": _round_or_none(timing["mean_seconds"]),
            "median_seconds": _round_or_none(timing["median_seconds"]),
            "mean_formatted": format_duration(timing["mean_seconds"]),
            "median_formatted": format_duration(timing["median_seconds"]),
            "by_side": by_side,
        },
        "sessions": sessions,
        "kind_split": kind_counts,
        "first_trial_local": first_local,
        "last_trial_local": last_local,
    }


def _median_change(today: float | None, previous: float | None) -> dict:
    if today is None or previous is None:
        return {
            "delta_seconds": None,
            "change": None,
            "label": "no previous-day A→B median to compare",
        }
    delta = round(float(today) - float(previous), 1)
    if abs(delta) < 1.0:
        change = "similar"
        label = f"similar to yesterday ({delta:+.1f}s)"
    elif delta < 0:
        change = "better"
        label = f"better than yesterday ({abs(delta):.1f}s faster)"
    else:
        change = "worse"
        label = f"worse than yesterday ({delta:.1f}s slower)"
    return {"delta_seconds": delta, "change": change, "label": label}


def build_day_summary(
    paths: list[Path],
    day: date,
    tz: str = DEFAULT_DAY_TZ,
) -> dict:
    """Calendar-day summary of scored magnetoreception B-choice trials."""
    csv_datasets: dict[str, pd.DataFrame] = {}
    for path in paths:
        if path.suffix.lower() != ".csv":
            continue
        try:
            df = load_outcomes(path)
        except Exception:
            continue
        label = path.parent.name if path.name == "events.csv" else path.name
        if label in csv_datasets:
            label = f"{path.parent.name}/{path.name}"
        csv_datasets[label] = df
    combined = combine_datasets(csv_datasets)
    scored = scored_trials(combined)
    today_df = filter_outcomes_for_day(scored, day, tz)
    previous_day = day - timedelta(days=1)
    previous_df = filter_outcomes_for_day(scored, previous_day, tz)

    today_block = _day_block(today_df, tz)
    previous_block = _day_block(previous_df, tz)
    today_median = today_block["a_to_b"]["median_seconds"]
    previous_median = previous_block["a_to_b"]["median_seconds"]

    payload = {
        "kind": "day_summary",
        "ts": time.time(),
        "timezone": tz,
        "date": day.isoformat(),
        "previous_date": previous_day.isoformat(),
        **today_block,
        "previous": {
            "date": previous_day.isoformat(),
            "trials": previous_block["trials"],
            "successes": previous_block["successes"],
            "failures": previous_block["failures"],
            "success_pct": previous_block["success_pct"],
            "a_to_b_median_seconds": previous_median,
            "a_to_b_median_formatted": previous_block["a_to_b"]["median_formatted"],
        },
        "vs_previous": {
            "trials_delta": today_block["trials"] - previous_block["trials"],
            "successes_delta": today_block["successes"] - previous_block["successes"],
            "success_pct_delta": (
                None
                if today_block["success_pct"] is None or previous_block["success_pct"] is None
                else round(today_block["success_pct"] - previous_block["success_pct"], 1)
            ),
            "a_to_b_median": _median_change(today_median, previous_median),
        },
    }
    return payload


def dataset_label(path: Path) -> str:
    match = EXP_SESSION_DIR.match(path.parent.name)
    if match and path.name == "events.csv":
        return f"exp_{match.group(1)}"
    return path.stem


def combine_datasets(datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for label, df in datasets.items():
        if df.empty:
            continue
        part = df.copy()
        part["source_file"] = label
        parts.append(part)

    if not parts:
        return pd.DataFrame()

    combined = pd.concat(parts, ignore_index=True)
    if combined["timestamp"].notna().any():
        combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
        combined = combined.sort_values("timestamp", kind="stable")
    combined = combined.reset_index(drop=True)
    combined["global_idx"] = range(1, len(combined) + 1)
    return combined


def summarize_feeder_direction(df: pd.DataFrame) -> dict:
    if df.empty or "feeder" not in df.columns:
        return {"left": 0, "right": 0, "unknown": 0}
    successful = df.loc[df["success"]]
    if successful.empty:
        return {"left": 0, "right": 0, "unknown": 0}
    left = int((successful["feeder"] == "left").sum())
    right = int((successful["feeder"] == "right").sum())
    unknown = int(successful["feeder"].isna().sum())
    return {"left": left, "right": right, "unknown": unknown}


def summarize_feeder_side_counts(df: pd.DataFrame) -> dict[str, dict[str, int]]:
    empty = {
        "left": {"success": 0, "total": 0},
        "right": {"success": 0, "total": 0},
    }
    if df.empty:
        return empty

    for feeder, zone, success in zip(df["feeder"], df["zone"], df["success"]):
        side = _trial_chosen_side(feeder, zone)
        if side not in empty:
            continue
        empty[side]["total"] += 1
        if success:
            empty[side]["success"] += 1
    return empty


def _trial_chosen_side(feeder, zone) -> str:
    normalized_zone = _normalize_zone(zone)
    if normalized_zone is not None:
        return ZONE_TO_FEEDER_SIDE[normalized_zone]
    side = _normalize_feeder_side(feeder)
    if side is not None:
        return side
    return "unknown"


def _trial_chosen_side_color(feeder, zone) -> str:
    side = _trial_chosen_side(feeder, zone)
    if side in FEEDER_SIDE_COLORS:
        return FEEDER_SIDE_COLORS[side]
    return FEEDER_SIDE_UNKNOWN_COLOR


def summarize_outcome_by_side(df: pd.DataFrame) -> dict[str, dict[str, int]]:
    breakdown = {
        "success": {"left": 0, "right": 0, "unknown": 0},
        "failure": {"left": 0, "right": 0, "unknown": 0},
    }
    if df.empty:
        return breakdown

    for feeder, zone, success in zip(df["feeder"], df["zone"], df["success"]):
        side = _trial_chosen_side(feeder, zone)
        if side not in FEEDER_SIDE_COLORS:
            side = "unknown"
        outcome = "success" if success else "failure"
        breakdown[outcome][side] += 1
    return breakdown


def summarize_a_to_b_time(df: pd.DataFrame) -> dict:
    if df.empty or "a_to_b_seconds" not in df.columns:
        return {"count": 0, "mean_seconds": None, "median_seconds": None}
    durations = df["a_to_b_seconds"].dropna()
    if durations.empty:
        return {"count": 0, "mean_seconds": None, "median_seconds": None}
    return {
        "count": int(len(durations)),
        "mean_seconds": float(durations.mean()),
        "median_seconds": float(durations.median()),
    }


def summarize_a_to_b_time_by_side(df: pd.DataFrame) -> dict[str, dict]:
    """Median/mean A→B time grouped by chosen side (B2=left, B1=right)."""
    sides = ("left", "right", "unknown")
    result = {side: {"count": 0, "mean_seconds": None, "median_seconds": None} for side in sides}
    if df.empty or "a_to_b_seconds" not in df.columns:
        return result
    work = df.copy()
    work["_side"] = [
        _trial_chosen_side(feeder, zone)
        for feeder, zone in zip(work["feeder"], work["zone"])
    ]
    work.loc[~work["_side"].isin(("left", "right")), "_side"] = "unknown"
    for side in sides:
        result[side] = summarize_a_to_b_time(work.loc[work["_side"] == side])
    return result


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, secs = divmod(seconds, 60)
    if minutes >= 1:
        return f"{seconds:.1f}s ({int(minutes)}m {secs:.0f}s)"
    return f"{seconds:.1f}s"


def summarize(df: pd.DataFrame) -> dict:
    total = len(df)
    successes = int(df["success"].sum()) if total else 0
    failures = total - successes
    pct = 100.0 * successes / total if total else 0.0
    return {
        "total": total,
        "successes": successes,
        "failures": failures,
        "success_pct": pct,
    }


def print_csv_analysis(
    csv_datasets: dict[str, pd.DataFrame],
    combined_label: str | None = None,
) -> None:
    if not csv_datasets:
        return

    print()
    print("Successful trial feeder direction (events CSV only)")
    print(f"{'Source':<24} {'Left':>6} {'Right':>7} {'Unknown':>9}")
    print("-" * 50)
    for label, df in csv_datasets.items():
        feeders = summarize_feeder_direction(df)
        print(
            f"{label:<24} {feeders['left']:>6} {feeders['right']:>7} "
            f"{feeders['unknown']:>9}"
        )
    if combined_label is not None:
        combined = combine_datasets(csv_datasets)
        if not combined.empty:
            feeders = summarize_feeder_direction(combined)
            print("-" * 50)
            print(
                f"{combined_label:<24} {feeders['left']:>6} {feeders['right']:>7} "
                f"{feeders['unknown']:>9}"
            )

    print()
    print("A→B travel time: trial_start → point_b (events CSV only)")
    print(f"{'Source':<24} {'Trials':>7} {'Mean':>16} {'Median':>16}")
    print("-" * 68)
    for label, df in csv_datasets.items():
        timing = summarize_a_to_b_time(df)
        print(
            f"{label:<24} {timing['count']:>7} "
            f"{format_duration(timing['mean_seconds']):>16} "
            f"{format_duration(timing['median_seconds']):>16}"
        )
    if combined_label is not None:
        combined = combine_datasets(csv_datasets)
        if not combined.empty:
            timing = summarize_a_to_b_time(combined)
            print("-" * 68)
            print(
                f"{combined_label:<24} {timing['count']:>7} "
                f"{format_duration(timing['mean_seconds']):>16} "
                f"{format_duration(timing['median_seconds']):>16}"
            )


def build_stats_summary(
    df: pd.DataFrame,
    csv_df: pd.DataFrame | None = None,
) -> dict:
    stats = summarize(df)
    result = {"summary": stats}
    if csv_df is not None and not csv_df.empty:
        side_counts = summarize_feeder_side_counts(csv_df)
        result["feeder"] = {
            "left": side_counts["left"]["success"],
            "right": side_counts["right"]["success"],
            "unknown": 0,
            "left_total": side_counts["left"]["total"],
            "right_total": side_counts["right"]["total"],
        }
        timing = summarize_a_to_b_time(csv_df)
        result["a_to_b"] = {
            **timing,
            "mean_formatted": format_duration(timing["mean_seconds"]),
            "median_formatted": format_duration(timing["median_seconds"]),
        }
    return result


def _rolling_trend_window(trial_count: int) -> int:
    if trial_count <= 1:
        return 1
    window = max(A_TO_B_TREND_MIN_WINDOW, trial_count // 8)
    return min(window, A_TO_B_TREND_MAX_WINDOW, trial_count)


def _rolling_success_rate_trend(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, int]:
    plot_df = df.sort_values("global_idx", kind="stable")
    window = _rolling_trend_window(len(plot_df))
    rolling_pct = (
        plot_df["success"]
        .astype(float)
        .rolling(window=window, min_periods=1, center=True)
        .mean()
        * 100
    )
    return plot_df["global_idx"], rolling_pct, window


def _plot_success_panel(ax, df: pd.DataFrame, label: str) -> None:
    stats = summarize(df)
    if not stats["total"]:
        ax.text(
            0.5,
            0.5,
            "No trial data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return

    breakdown = summarize_outcome_by_side(df)
    bar_specs = [
        ("Successful", "success", SUCCESS_OUTLINE_COLOR),
        ("Failed", "failure", FAILURE_OUTLINE_COLOR),
    ]
    side_order = ["left", "right", "unknown"]
    side_colors = {
        "left": FEEDER_SIDE_COLORS["left"],
        "right": FEEDER_SIDE_COLORS["right"],
        "unknown": FEEDER_SIDE_UNKNOWN_COLOR,
    }
    x_positions = list(range(len(bar_specs)))
    bar_width = 0.6

    max_total = max(
        max(sum(breakdown[key].values()), 1) for _, key, _ in bar_specs
    )

    for x_idx, (_, outcome_key, outline_color) in enumerate(bar_specs):
        bottom = 0.0
        total = sum(breakdown[outcome_key].values())
        for side in side_order:
            count = breakdown[outcome_key][side]
            if count <= 0:
                continue
            ax.bar(
                x_positions[x_idx],
                count,
                bar_width,
                bottom=bottom,
                color=side_colors[side],
                edgecolor="white",
                linewidth=0.8,
                zorder=2,
            )
            label_color = "white" if side != "unknown" else "black"
            ax.text(
                x_positions[x_idx],
                bottom + count / 2,
                str(count),
                ha="center",
                va="center",
                fontsize=10,
                fontweight="bold",
                color=label_color,
                zorder=3,
            )
            bottom += count

        if total > 0:
            ax.add_patch(
                Rectangle(
                    (x_positions[x_idx] - bar_width / 2, 0),
                    bar_width,
                    total,
                    fill=False,
                    edgecolor=outline_color,
                    linewidth=3,
                    zorder=4,
                )
            )

    ax.set_xticks(x_positions)
    ax.set_xticklabels([name for name, _, _ in bar_specs], fontweight="bold")
    for tick, (_, _, outline_color) in zip(ax.get_xticklabels(), bar_specs):
        tick.set_color(outline_color)
    ax.set_ylabel("Number of trials")
    ax.set_title(
        f"{label}\n"
        f"{stats['successes']}/{stats['total']} correct "
        f"({stats['success_pct']:.1f}%)"
    )
    ax.set_ylim(0, max(stats["total"], max_total, 1) * 1.15)
    ax.set_xlim(-0.6, len(bar_specs) - 0.4)

    legend_handles = [
        Patch(facecolor=FEEDER_SIDE_COLORS["left"], label="Left (B2)"),
        Patch(facecolor=FEEDER_SIDE_COLORS["right"], label="Right (B1)"),
        Patch(
            facecolor="white",
            edgecolor=SUCCESS_OUTLINE_COLOR,
            linewidth=2,
            label="Successful trials",
        ),
        Patch(
            facecolor="white",
            edgecolor=FAILURE_OUTLINE_COLOR,
            linewidth=2,
            label="Failed trials",
        ),
    ]
    if breakdown["success"]["unknown"] or breakdown["failure"]["unknown"]:
        legend_handles.insert(
            2,
            Patch(facecolor=FEEDER_SIDE_UNKNOWN_COLOR, label="Unknown side"),
        )
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)


def _trial_day_spans(df: pd.DataFrame) -> list[tuple[object, float, float]]:
    """Contiguous trial-index ranges grouped by calendar day."""
    if df.empty or "timestamp" not in df.columns or not df["timestamp"].notna().any():
        return []

    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    dates = timestamps.dt.date.ffill().bfill()
    if dates.isna().all():
        return []

    spans: list[tuple[object, float, float]] = []
    start = 0
    for idx in range(1, len(df)):
        if dates.iloc[idx] != dates.iloc[idx - 1]:
            spans.append(
                (
                    dates.iloc[start],
                    float(df["global_idx"].iloc[start]),
                    float(df["global_idx"].iloc[idx - 1]),
                )
            )
            start = idx
    spans.append(
        (
            dates.iloc[start],
            float(df["global_idx"].iloc[start]),
            float(df["global_idx"].iloc[-1]),
        )
    )
    return spans


def _trials_per_day_counts(df: pd.DataFrame) -> pd.Series:
    if df.empty or "timestamp" not in df.columns or not df["timestamp"].notna().any():
        return pd.Series(dtype=int)

    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    dates = timestamps.dt.date.ffill().bfill()
    if dates.isna().all():
        return pd.Series(dtype=int)
    return dates.value_counts().sort_index()


def _summarize_trials_per_day(df: pd.DataFrame) -> tuple[float | None, str | None]:
    """Typical daily trial count, ignoring sparse partial days when possible."""
    day_counts = _trials_per_day_counts(df)
    if day_counts.empty:
        return None, None

    active_days = day_counts[day_counts >= ACTIVE_DAY_MIN_TRIALS]
    if not active_days.empty:
        avg = float(active_days.mean())
        return avg, f"Avg/day (≥{ACTIVE_DAY_MIN_TRIALS}): {avg:.1f} trials"

    median = float(day_counts.median())
    return median, f"Med/day: {median:.1f} trials"


def _shade_trial_days(ax, df: pd.DataFrame) -> None:
    day_shades = ("#eef2f7", "#ffffff")
    for day_idx, (day, x_start, x_end) in enumerate(_trial_day_spans(df)):
        ax.axvspan(
            x_start - 0.5,
            x_end + 0.5,
            color=day_shades[day_idx % 2],
            zorder=0,
            transform=ax.get_xaxis_transform(),
        )
        ax.text(
            (x_start + x_end) / 2,
            0.98,
            day.isoformat(),
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=7,
            color="#666666",
            clip_on=False,
        )


def _learning_curve_side_color(side: str) -> str:
    if side in FEEDER_SIDE_COLORS:
        return FEEDER_SIDE_COLORS[side]
    return FEEDER_SIDE_UNKNOWN_COLOR


def _plot_learning_curve_outcomes(ax, df: pd.DataFrame, outcome_y: float) -> list[Line2D]:
    plot_df = df.copy()
    plot_df["chosen_side"] = [
        _trial_chosen_side(feeder, zone)
        for feeder, zone in zip(plot_df["feeder"], plot_df["zone"])
    ]

    legend_handles: list[Line2D] = []
    series = [
        ("left", True, "Left · correct"),
        ("left", False, "Left · incorrect"),
        ("right", True, "Right · correct"),
        ("right", False, "Right · incorrect"),
        ("unknown", True, "Unknown · correct"),
        ("unknown", False, "Unknown · incorrect"),
    ]
    for side, success, label in series:
        mask = (plot_df["chosen_side"] == side) & (plot_df["success"] == success)
        if not mask.any():
            continue

        xs = plot_df.loc[mask, "global_idx"]
        ys = [outcome_y] * len(xs)
        color = _learning_curve_side_color(side)
        if success:
            ax.plot(
                xs,
                ys,
                "o",
                color=color,
                markerfacecolor=color,
                markeredgecolor=color,
                markersize=6,
                linestyle="none",
                zorder=3,
            )
            legend_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    color="w",
                    markerfacecolor=color,
                    markeredgecolor=color,
                    markersize=8,
                    label=label,
                )
            )
        else:
            ax.plot(
                xs,
                ys,
                "x",
                color=color,
                markeredgewidth=1.2,
                markersize=6,
                linestyle="none",
                zorder=3,
            )
            legend_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker="x",
                    color=color,
                    markeredgewidth=1.2,
                    markersize=8,
                    linestyle="None",
                    label=label,
                )
            )

    return legend_handles


def _plot_learning_curve_panel(ax, df: pd.DataFrame, label: str) -> None:
    stats = summarize(df)
    if not stats["total"]:
        ax.text(
            0.5,
            0.5,
            "No trial data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return

    x = df["global_idx"]
    _shade_trial_days(ax, df)
    outcome_y = 1.05
    outcome_handles = _plot_learning_curve_outcomes(ax, df, outcome_y)
    cumulative = df["success"].expanding().mean() * 100
    trend_x, rolling_pct, trend_window = _rolling_success_rate_trend(df)
    recent_pct = float(rolling_pct.iloc[-1]) if not rolling_pct.empty else stats["success_pct"]
    _avg_trials_per_day, trials_per_day_label = _summarize_trials_per_day(df)
    stats_lines = [
        f"Overall: {stats['success_pct']:.1f}%",
        f"Rolling: {recent_pct:.1f}%",
    ]
    if trials_per_day_label:
        stats_lines.append(trials_per_day_label)
    ax_pct = ax.twinx()
    ax_pct.plot(
        x,
        cumulative,
        color="#1f77b4",
        marker="o",
        markersize=4,
        linewidth=1.5,
        label="Running success %",
        zorder=4,
    )
    ax_pct.plot(
        trend_x,
        rolling_pct,
        color="#d94801",
        linewidth=3,
        solid_capstyle="round",
        label=f"Trend (rolling success, n={trend_window})",
        zorder=5,
    )
    ax_pct.set_ylabel("Running success (%)")
    ax_pct.set_ylim(0, 105)
    ax_pct.axhline(stats["success_pct"], color="#555555", linestyle="--", linewidth=1)
    ax_pct.text(
        0.02,
        0.02,
        "\n".join(stats_lines),
        transform=ax_pct.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        linespacing=1.2,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.85},
        zorder=6,
    )
    ax.set_xlabel("Trial index (chronological)")
    ax.set_ylabel("Outcome (side + correctness)")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["", ""])
    ax.set_title(f"{label}: per-trial side, outcome, and running success rate")
    ax.set_ylim(0, 1.2)
    if outcome_handles:
        line_handles, _line_labels = ax_pct.get_legend_handles_labels()
        ax.legend(
            handles=outcome_handles + line_handles,
            loc="lower right",
            fontsize=7,
            framealpha=0.9,
        )


def _plot_feeder_panel(ax, df: pd.DataFrame, label: str) -> None:
    counts = summarize_feeder_side_counts(df)
    side_labels = ["Left (B2)", "Right (B1)"]
    side_keys = ["left", "right"]
    totals = [counts[key]["total"] for key in side_keys]
    successes = [counts[key]["success"] for key in side_keys]
    colors = [FEEDER_SIDE_COLORS[key] for key in side_keys]

    ax.bar(
        side_labels,
        totals,
        color=colors,
        alpha=0.3,
        edgecolor="none",
        zorder=1,
    )
    success_bars = ax.bar(
        side_labels,
        successes,
        color=colors,
        edgecolor="black",
        linewidth=0.6,
        zorder=2,
    )
    ax.set_ylabel("Trials per side")
    ax.set_title(f"{label}: success rate by side chosen")
    ymax = max(max(totals, default=0), max(successes, default=0), 1) * 1.15
    ax.set_ylim(0, ymax)
    for bar, success, total in zip(success_bars, successes, totals):
        if total <= 0:
            continue
        ratio_pct = 100.0 * success / total
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() / 2 if bar.get_height() > 0 else 0.1,
            f"{ratio_pct:.0f}%",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            color="white" if bar.get_height() > ymax * 0.06 else "black",
        )


def _a_to_b_trend_window(trial_count: int) -> int:
    return _rolling_trend_window(trial_count)


def _a_to_b_rolling_median_trend(
    global_idx: pd.Series,
    durations: pd.Series,
) -> tuple[pd.Series, pd.Series, int]:
    plot_df = pd.DataFrame({"global_idx": global_idx, "duration": durations})
    plot_df = plot_df.sort_values("global_idx", kind="stable")
    window = _a_to_b_trend_window(len(plot_df))
    trend = (
        plot_df["duration"]
        .rolling(window=window, min_periods=1, center=True)
        .median()
    )
    return plot_df["global_idx"], trend, window


def _plot_a_to_b_panel(ax, df: pd.DataFrame, label: str) -> None:
    durations = df["a_to_b_seconds"].dropna()
    if durations.empty:
        ax.text(
            0.5,
            0.5,
            "No A→B timing data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return

    _shade_trial_days(ax, df)
    plot_df = df.loc[durations.index, ["global_idx", "a_to_b_seconds", "feeder", "zone"]]
    bar_colors = [
        _trial_chosen_side_color(feeder, zone)
        for feeder, zone in zip(plot_df["feeder"], plot_df["zone"])
    ]
    ax.bar(
        plot_df["global_idx"],
        plot_df["a_to_b_seconds"],
        color=bar_colors,
        width=0.85,
        edgecolor="none",
        zorder=2,
    )
    plot_idx = plot_df["global_idx"]
    durations = plot_df["a_to_b_seconds"]
    trend_durations = durations.clip(upper=A_TO_B_YLIM_SECONDS)
    trend_x, trend_y, trend_window = _a_to_b_rolling_median_trend(plot_idx, trend_durations)
    ax.plot(
        trend_x,
        trend_y,
        color="#d94801",
        linewidth=3,
        solid_capstyle="round",
        label=f"Trend (rolling median, n={trend_window})",
        zorder=5,
    )
    timing = summarize_a_to_b_time(df)
    ax.axhline(
        timing["mean_seconds"],
        color="#d62728",
        linestyle="--",
        linewidth=1.5,
        label=f"Mean: {format_duration(timing['mean_seconds'])}",
    )
    ax.axhline(
        timing["median_seconds"],
        color="#2ca02c",
        linestyle="-.",
        linewidth=1.5,
        label=f"Median: {format_duration(timing['median_seconds'])}",
    )
    ax.set_xlabel("Trial index (chronological)")
    ax.set_ylabel("Seconds")
    ax.set_title(f"{label}: A→B travel time per trial")
    ax.set_ylim(0, A_TO_B_YLIM_SECONDS)
    from matplotlib.patches import Patch

    side_handles = [
        Patch(facecolor=FEEDER_SIDE_COLORS["left"], label="Left side"),
        Patch(facecolor=FEEDER_SIDE_COLORS["right"], label="Right side"),
    ]
    if any(_trial_chosen_side(f, z) == "unknown" for f, z in zip(plot_df["feeder"], plot_df["zone"])):
        side_handles.append(
            Patch(facecolor=FEEDER_SIDE_UNKNOWN_COLOR, label="Unknown side")
        )
    line_handles, line_labels = ax.get_legend_handles_labels()
    ax.legend(
        handles=side_handles + line_handles,
        labels=[handle.get_label() for handle in side_handles] + line_labels,
        loc="upper right",
        fontsize=9,
    )


def _plot_unavailable_panel(ax, message: str) -> None:
    ax.text(
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.set_axis_off()


def plot_panel_figure(
    panel: str,
    label: str,
    df: pd.DataFrame,
    csv_df: pd.DataFrame | None = None,
) -> plt.Figure:
    if panel not in PANELS:
        raise ValueError(f"Unknown panel: {panel}. Expected one of {PANELS}")

    if panel == "all":
        fig = plt.figure(figsize=(12, 9))
        fig.suptitle(f"{label}: magnetoreception analysis", fontsize=14, fontweight="bold")
        ax_counts = fig.add_subplot(2, 2, 1)
        ax_trials = fig.add_subplot(2, 2, 2)
        ax_feeder = fig.add_subplot(2, 2, 3)
        ax_time = fig.add_subplot(2, 2, 4)
        _plot_success_panel(ax_counts, df, label)
        _plot_learning_curve_panel(ax_trials, df, label)
        if csv_df is not None and not csv_df.empty:
            _plot_feeder_panel(ax_feeder, csv_df, label)
            _plot_a_to_b_panel(ax_time, csv_df, label)
        else:
            _plot_unavailable_panel(ax_feeder, "Feeder data\n(events CSV only)")
            _plot_unavailable_panel(ax_time, "A→B timing\n(events CSV only)")
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        return fig

    fig = plt.figure(figsize=(8, 5))
    ax = fig.add_subplot(1, 1, 1)
    if panel == "success":
        _plot_success_panel(ax, df, label)
    elif panel == "learning_curve":
        _plot_learning_curve_panel(ax, df, label)
    elif panel == "feeder":
        if csv_df is None or csv_df.empty:
            _plot_unavailable_panel(ax, "Feeder data\n(events CSV only)")
        else:
            _plot_feeder_panel(ax, csv_df, label)
    elif panel == "a_to_b":
        if csv_df is None or csv_df.empty:
            _plot_unavailable_panel(ax, "A→B timing\n(events CSV only)")
        else:
            _plot_a_to_b_panel(ax, csv_df, label)
    fig.tight_layout()
    return fig


def figure_to_png_bytes(fig: plt.Figure) -> bytes:
    import io

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def prepare_bulk_plot_data(
    paths: list[Path],
    bulk_name: str | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], str, dict]:
    datasets, csv_datasets = load_all_datasets(paths)
    if not datasets:
        raise ValueError("No readable session files found")

    combined_label = bulk_name or f"combined ({len(datasets)} files)"
    combined = combine_datasets(datasets)
    if combined.empty:
        raise ValueError("No trial outcomes found across the selected files")

    plot_datasets = {combined_label: combined}
    plot_csv: dict[str, pd.DataFrame] = {}
    if csv_datasets:
        csv_combined = combine_datasets(csv_datasets)
        if not csv_combined.empty:
            plot_csv[combined_label] = csv_combined

    stats = build_stats_summary(combined, plot_csv.get(combined_label))
    stats["sessions"] = list(datasets.keys())
    stats["warnings"] = [
        f"No point-B trials in {label}" for label, df in datasets.items() if df.empty
    ]
    return plot_datasets, plot_csv, combined_label, stats


def run_analysis_api(
    panel: str,
    paths: list[Path],
    bulk_name: str = "analysis",
) -> tuple[bytes, dict]:
    plot_datasets, plot_csv, combined_label, stats = prepare_bulk_plot_data(
        paths, bulk_name=bulk_name
    )
    df = plot_datasets[combined_label]
    csv_df = plot_csv.get(combined_label)
    fig = plot_panel_figure(panel, combined_label, df, csv_df)
    stats["panel"] = panel
    stats["panel_label"] = PANEL_LABELS[panel]
    stats["label"] = combined_label
    return figure_to_png_bytes(fig), stats


def plot_analysis(
    datasets: dict[str, pd.DataFrame],
    output: Path | None,
    csv_datasets: dict[str, pd.DataFrame] | None = None,
    panel: str = "all",
) -> None:
    n_files = len(datasets)
    if n_files == 0:
        raise ValueError("No datasets to plot")

    if panel != "all" and n_files == 1:
        label, df = next(iter(datasets.items()))
        csv_df = (csv_datasets or {}).get(label)
        fig = plot_panel_figure(panel, label, df, csv_df)
        if output:
            fig.savefig(output, dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(f"Saved plot to {output}")
        else:
            plt.show()
        return

    csv_datasets = csv_datasets or {}
    include_csv_panels = bool(csv_datasets)
    n_cols = 2
    n_rows = 2 * n_files if include_csv_panels else n_files

    fig = plt.figure(figsize=(12, 4.5 * (2 if include_csv_panels else 1) * n_files))
    fig.suptitle("Magnetoreception trial analysis", fontsize=14, fontweight="bold")

    for block_idx, (label, df) in enumerate(datasets.items()):
        csv_df = csv_datasets.get(label)

        if include_csv_panels:
            panel_base = block_idx * 4
            ax_counts = fig.add_subplot(n_rows, n_cols, panel_base + 1)
            ax_trials = fig.add_subplot(n_rows, n_cols, panel_base + 2)
            ax_feeder = fig.add_subplot(n_rows, n_cols, panel_base + 3)
            ax_time = fig.add_subplot(n_rows, n_cols, panel_base + 4)
            _plot_success_panel(ax_counts, df, label)
            _plot_learning_curve_panel(ax_trials, df, label)
            if csv_df is not None and not csv_df.empty:
                _plot_feeder_panel(ax_feeder, csv_df, label)
                _plot_a_to_b_panel(ax_time, csv_df, label)
            else:
                _plot_unavailable_panel(ax_feeder, "Feeder data\n(events CSV only)")
                _plot_unavailable_panel(ax_time, "A→B timing\n(events CSV only)")
        else:
            panel_base = block_idx * 2
            ax_counts = fig.add_subplot(n_rows, n_cols, panel_base + 1)
            ax_trials = fig.add_subplot(n_rows, n_cols, panel_base + 2)
            _plot_success_panel(ax_counts, df, label)
            _plot_learning_curve_panel(ax_trials, df, label)

    fig.tight_layout(rect=[0, 0, 1, 0.97])

    if output:
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved plot to {output}")
    else:
        plt.show()


def print_summary(
    datasets: dict[str, pd.DataFrame],
    combined_label: str | None = None,
) -> None:
    print(f"{'Source':<24} {'Trials':>7} {'Success':>8} {'Failed':>7} {'Rate':>8}")
    print("-" * 58)
    for label, df in datasets.items():
        stats = summarize(df)
        print(
            f"{label:<24} {stats['total']:>7} {stats['successes']:>8} "
            f"{stats['failures']:>7} {stats['success_pct']:>7.1f}%"
        )

    if combined_label is not None:
        combined = combine_datasets(datasets)
        if not combined.empty:
            stats = summarize(combined)
            print("-" * 58)
            print(
                f"{combined_label:<24} {stats['total']:>7} {stats['successes']:>8} "
                f"{stats['failures']:>7} {stats['success_pct']:>7.1f}%"
            )


def load_all_datasets(
    paths: list[Path],
    quiet: bool = False,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    datasets: dict[str, pd.DataFrame] = {}
    csv_datasets: dict[str, pd.DataFrame] = {}

    for path in paths:
        label = dataset_label(path)
        if label in datasets:
            label = f"{path.parent.name}/{path.stem}"

        try:
            df = load_outcomes(path)
        except Exception as exc:
            if not quiet:
                print(f"Warning: skipping {path}: {exc}")
            continue

        datasets[label] = df
        if _detect_file_kind(path) == "csv":
            csv_datasets[label] = df
        if df.empty and not quiet:
            print(f"Warning: no point-B trial outcomes found in {path}")

    return datasets, csv_datasets


def run_analysis(
    datasets: dict[str, pd.DataFrame],
    csv_datasets: dict[str, pd.DataFrame],
    output: Path | None,
    bulk: bool = False,
    bulk_name: str | None = None,
    show_per_file: bool = True,
    panel: str = "all",
) -> None:
    if not datasets:
        raise ValueError("No datasets to analyze")

    combined_label = bulk_name or f"combined ({len(datasets)} files)"

    if bulk:
        combined = combine_datasets(datasets)
        if combined.empty:
            raise ValueError("No trial outcomes found across the selected files")
        plot_datasets = {combined_label: combined}
        plot_csv = (
            {combined_label: combine_datasets(csv_datasets)}
            if csv_datasets
            else {}
        )
        if plot_csv and plot_csv[combined_label].empty:
            plot_csv = {}
    else:
        plot_datasets = datasets
        plot_csv = csv_datasets
        combined_label = None

    if show_per_file and bulk:
        print_summary(datasets, combined_label=combined_label)
        print_csv_analysis(csv_datasets, combined_label=combined_label)
    else:
        print_summary(plot_datasets)
        print_csv_analysis(plot_csv)

    plot_analysis(plot_datasets, output, csv_datasets=plot_csv or None, panel=panel)


def default_inputs() -> list[Path]:
    candidates = [
        Path("session_exp1.txt"),
        Path("session_exp1.log"),
        Path("events_exp2.csv"),
        Path("events_exp3.csv"),
    ]
    paths: list[Path] = []
    seen_log = False
    for path in candidates:
        if not path.exists():
            continue
        if path.name.startswith("session_exp1"):
            if seen_log:
                continue
            seen_log = True
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze magnetoreception trial success from logs or event CSV files."
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Session log (.log/.txt), events CSV files, or directories to scan",
    )
    parser.add_argument(
        "--panel",
        choices=PANELS,
        default="all",
        help="Which figure panel to generate (default: all)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Save figure to this path instead of showing interactively",
    )
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="Combine all inputs into one analysis and one set of figures",
    )
    parser.add_argument(
        "--bulk-name",
        type=str,
        default=None,
        help="Label for combined bulk output (default: 'combined (N files)')",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="When scanning directories, do not search subdirectories",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help=(
            "Load session events.csv files from a reptiLearn sessions directory "
            "(e.g. /data/reptilearn/sessions). With --day-summary this loads every "
            "*/events.csv; otherwise it loads exp_N_*/events.csv"
        ),
    )
    parser.add_argument(
        "--day-summary",
        nargs="?",
        const="today",
        default=None,
        help=(
            "Write a calendar-day JSON summary instead of plots. "
            "Optional date YYYY-MM-DD (default: today in --timezone)"
        ),
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write --day-summary JSON to this path (default: stdout)",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_DAY_TZ,
        help=f"IANA timezone for calendar days (default: {DEFAULT_DAY_TZ})",
    )
    args = parser.parse_args()

    if args.day_summary is not None:
        try:
            day = parse_day_arg(args.day_summary, args.timezone)
        except ValueError as exc:
            parser.error(f"invalid --day-summary date: {exc}")
        sessions_dir = args.sessions_dir or DEFAULT_SESSIONS_DIR
        try:
            raw_paths = collect_all_session_events_paths(sessions_dir)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        if args.files:
            raw_paths.extend(args.files)
        try:
            paths = collect_input_paths(raw_paths, recursive=not args.no_recursive)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        if not paths:
            parser.error("No events.csv files found for day summary.")
        payload = build_day_summary(paths, day, tz=args.timezone)
        text = json.dumps(payload, indent=2, default=str) + "\n"
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(text)
            print(f"Wrote day summary to {args.json_out}")
        else:
            print(text, end="")
        return

    if args.sessions_dir:
        try:
            session_paths = collect_exp_session_paths(args.sessions_dir)
        except FileNotFoundError as exc:
            parser.error(str(exc))
        if not session_paths:
            parser.error(f"No exp_*/events.csv files found in {args.sessions_dir}")
        raw_paths = session_paths
    else:
        raw_paths = args.files or default_inputs()
        if not raw_paths:
            parser.error("No input files found. Pass paths explicitly or use --sessions-dir.")

    try:
        paths = collect_input_paths(raw_paths, recursive=not args.no_recursive)
    except FileNotFoundError as exc:
        parser.error(str(exc))

    if not paths:
        parser.error("No supported files found (.csv, .log, .txt).")

    datasets, csv_datasets = load_all_datasets(paths)
    run_analysis(
        datasets,
        csv_datasets,
        args.output,
        bulk=args.bulk,
        bulk_name=args.bulk_name,
        panel=args.panel,
    )


if __name__ == "__main__":
    main()
