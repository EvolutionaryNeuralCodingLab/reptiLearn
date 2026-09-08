"""On-demand lab checkout JSON for the OpenClaw Telegram agent.

Runs the same health checks as the timer without writing alerts.jsonl or
updating the file-growth snapshot. Also tails session.log for ERROR lines.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from health.monitor import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_UNHEALTHY,
    build_report,
    fetch_state,
    health_dir,
    load_config,
    load_heartbeat,
    nested_get,
    resolve_path,
    run_checks,
    session_data_dir,
    session_running,
)

LOG_FAIL_MARKERS = (
    " ERROR ",
    "CRITICAL",
    "observers restarted while an experiment is running",
    "BBox experiment listeners are detached",
)
LOG_SKIP_MARKERS = (
    "wrong_zone",
    "Animal detected at",
    "Logging event:",
    "werkzeug",
)
LOG_TAIL_BYTES = 65536
LOG_MAX_FINDINGS = 12


def resolve_session_dir(cfg: dict, session: str | None, state, hb) -> Path | None:
    if not session or session in {"current", "."}:
        return session_data_dir(state, hb)
    root = resolve_path(cfg, "session_data_root", "/data/reptilearn/sessions")
    direct = root / session
    if direct.is_dir():
        return direct
    matches = sorted(
        p for p in root.glob(f"{session}*") if p.is_dir()
    )
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    with_events = [p for p in matches if (p / "events.csv").exists()]
    if len(with_events) == 1:
        return with_events[0]
    return sorted(with_events or matches, key=lambda p: p.stat().st_mtime)[-1]


def scan_session_log(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"path": str(path) if path else None, "scanned_bytes": 0, "findings": []}
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {
            "path": str(path),
            "scanned_bytes": 0,
            "findings": [
                {"severity": "fail", "source": "log", "summary": f"could not read session.log: {exc}"}
            ],
        }
    tail = data[-LOG_TAIL_BYTES:].decode("utf-8", errors="replace")
    findings = []
    seen: set[str] = set()
    for line in tail.splitlines():
        if any(skip in line for skip in LOG_SKIP_MARKERS):
            continue
        if not any(marker in line for marker in LOG_FAIL_MARKERS):
            continue
        compact = " ".join(line.strip().split())
        key = compact[20:220] if len(compact) > 20 else compact
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            {
                "severity": "fail",
                "source": "log",
                "summary": compact[:240],
            }
        )
    return {
        "path": str(path),
        "scanned_bytes": min(len(data), LOG_TAIL_BYTES),
        "findings": findings[-LOG_MAX_FINDINGS:],
    }


def session_info(state, hb, data_dir: Path | None) -> dict:
    info = {
        "id": None,
        "experiment": None,
        "is_running": session_running(state),
        "data_dir": str(data_dir) if data_dir else None,
        "phase": None,
    }
    if state:
        info["id"] = nested_get(state, "session", "id") or nested_get(state, "session", "experiment")
        info["experiment"] = nested_get(state, "session", "experiment")
        info["is_running"] = session_running(state)
        info["phase"] = nested_get(state, "session", "magnetoreception_phase") or nested_get(
            state, "session", "onboarding_phase"
        )
    if hb:
        info["id"] = info["id"] or hb.get("session_id")
        info["experiment"] = info["experiment"] or hb.get("experiment")
        if data_dir is None and hb.get("data_dir"):
            info["data_dir"] = hb.get("data_dir")
        info["phase"] = info["phase"] or hb.get("phase")
        if not state:
            info["is_running"] = bool(hb.get("is_running"))
    if data_dir is not None:
        info["data_dir"] = str(data_dir)
        if not info["id"]:
            info["id"] = data_dir.name
    return info


def build_checkout(cfg: dict, session: str | None) -> dict:
    state, _state_error = fetch_state(cfg)
    hb = load_heartbeat(cfg)
    checks = run_checks(cfg, persist=False)
    health = build_report(checks)
    health_slim = {
        "ok": health["ok"],
        "failed": health["failed"],
        "warned": health["warned"],
        "checks": [
            {
                "id": c["id"],
                "ok": c["ok"],
                "severity": c["severity"],
                "summary": c["summary"],
            }
            for c in health["checks"]
        ],
    }

    data_dir = resolve_session_dir(cfg, session, state, hb)
    log_scan = scan_session_log((data_dir / "session.log") if data_dir else None)

    findings = []
    for check in health["checks"]:
        if check["severity"] in {"fail", "warn"}:
            findings.append(
                {
                    "severity": check["severity"],
                    "source": "health",
                    "id": check["id"],
                    "summary": check["summary"],
                }
            )
    findings.extend(log_scan["findings"])

    ok = all(item["severity"] != "fail" for item in findings)
    return {
        "kind": "lab_checkout",
        "ts": time.time(),
        "ok": ok,
        "session": session_info(state, hb, data_dir),
        "health": health_slim,
        "log": log_scan,
        "findings": findings,
        "status_path": str(health_dir(cfg) / "status.json"),
        "heartbeat_path": str(health_dir(cfg) / "experiment_heartbeat.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="On-demand ReptiLearn lab checkout JSON")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--session",
        default="current",
        help="current, a session id prefix (mr1_exp8), or a session directory name",
    )
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        payload = build_checkout(cfg, args.session)
    except Exception as exc:
        sys.stderr.write(f"health checkout error: {exc}\n")
        return EXIT_ERROR
    print(json.dumps(payload, indent=2, default=str))
    if not payload["ok"]:
        return EXIT_UNHEALTHY
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
