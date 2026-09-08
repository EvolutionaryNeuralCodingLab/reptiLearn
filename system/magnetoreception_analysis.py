"""
Server-side wrapper for magnetoreception trial analysis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import analyze_magnetoreception_trials as amt  # noqa: E402

from configure import get_config


def _sessions_root() -> Path:
    config = get_config()
    if config is not None:
        return config.session_data_root
    from config import config as default_config

    return default_config.session_data_root


def resolve_analysis_paths(scope: str, session_ids: list[str] | None = None) -> list[Path]:
    sessions_root = _sessions_root()
    session_ids = session_ids or []

    if scope == "current":
        import experiment

        if not experiment.session_state.exists(()):
            raise ValueError("No active session. Start or continue a session first.")
        events_path = Path(experiment.session_state["data_dir"]) / "events.csv"
        if not events_path.exists():
            raise ValueError(f"No events.csv found for current session: {events_path}")
        return [events_path]

    if scope == "selected":
        if not session_ids:
            raise ValueError("No sessions selected for analysis.")
        paths: list[Path] = []
        for session_id in session_ids:
            matches = list(sessions_root.glob(f"{session_id}_*/events.csv"))
            if not matches:
                direct = sessions_root / session_id / "events.csv"
                if direct.exists():
                    matches = [direct]
            if not matches:
                raise ValueError(f"No events.csv found for session '{session_id}'")
            paths.append(matches[0])
        return paths

    if scope == "all_train":
        paths = amt.collect_train_session_paths(sessions_root)
        if not paths:
            raise ValueError(f"No train_*/events.csv files found in {sessions_root}")
        return paths

    if scope == "all_exp":
        paths = amt.collect_exp_session_paths(sessions_root)
        if not paths:
            raise ValueError(f"No exp_*/events.csv files found in {sessions_root}")
        return paths

    raise ValueError(
        f"Unknown analysis scope: {scope}. "
        "Expected current, selected, all_train, or all_exp."
    )


def run_magnetoreception_analysis(
    panel: str,
    scope: str,
    session_ids: list[str] | None = None,
    bulk_name: str = "analysis",
) -> tuple[bytes, dict]:
    paths = resolve_analysis_paths(scope, session_ids)
    return amt.run_analysis_api(panel, paths, bulk_name=bulk_name)


def export_analysis_figures(output_dir: str, figures: list[dict]) -> dict:
    import base64
    import re

    if not output_dir or not str(output_dir).strip():
        raise ValueError("Export folder path is required")
    if not figures:
        raise ValueError("No figures to export")

    dest = Path(output_dir).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for item in figures:
        filename = item.get("filename")
        if not filename or not re.fullmatch(r"[\w.-]+\.png", filename):
            raise ValueError(f"Invalid export filename: {filename!r}")

        image_b64 = item.get("image")
        if not image_b64:
            raise ValueError(f"Missing image data for {filename}")

        path = dest / filename
        path.write_bytes(base64.b64decode(image_b64))
        saved.append(str(path))

    return {"output_dir": str(dest), "saved": saved, "count": len(saved)}
