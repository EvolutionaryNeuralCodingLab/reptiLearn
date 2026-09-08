"""Write the calendar-day magnetoreception summary consumed by OpenClaw."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HEALTH_DIR = Path(__file__).resolve().parent
SYSTEM_DIR = HEALTH_DIR.parent
REPO_ROOT = SYSTEM_DIR.parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import analyze_magnetoreception_trials as amt  # noqa: E402

from health.monitor import atomic_write_json, health_dir, load_config  # noqa: E402


def build_payload(cfg: dict, day_text: str | None = None) -> dict:
    tz = cfg.get("day_summary_timezone") or amt.DEFAULT_DAY_TZ
    sessions_dir = Path(
        (cfg.get("paths") or {}).get("session_data_root", str(amt.DEFAULT_SESSIONS_DIR))
    )
    day = amt.parse_day_arg(day_text, tz)
    paths = amt.collect_all_session_events_paths(sessions_dir)
    return amt.build_day_summary(paths, day, tz=tz)


def write_payload(cfg: dict, payload: dict) -> Path:
    dest_dir = health_dir(cfg)
    dest_dir.mkdir(parents=True, exist_ok=True)
    json_path = dest_dir / "day_summary.json"
    atomic_write_json(json_path, payload)
    jsonl_path = dest_dir / "day_summaries.jsonl"
    with jsonl_path.open("a") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")
    return json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write ReptiLearn calendar-day summary JSON")
    parser.add_argument("--day", default="today", help="YYYY-MM-DD, 'today', or 'yesterday'")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout and do not write day_summary.json / jsonl",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write JSON to this path instead of the canonical 20:00 file",
    )
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    payload = build_payload(cfg, args.day)
    text = json.dumps(payload, indent=2, default=str) + "\n"
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text)
        print(f"Wrote {args.json_out} ({payload.get('date')}: {payload.get('trials')} trials)")
        return 0
    path = write_payload(cfg, payload)
    print(f"Wrote {path} ({payload.get('date')}: {payload.get('trials')} trials)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
