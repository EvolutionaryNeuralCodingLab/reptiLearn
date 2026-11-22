"""
Load shared magnetoreception defaults from system/config/experiment_config.json.

Session create and param reset call Experiment.get_default_params(), which uses
default_params_for(). A zone map value is either a shared zone name or an inline
zone dict (used for per-experiment overrides such as onboarding point_a).
"""

import json
from copy import deepcopy
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "experiment_config.json"
_SHARED_KEYS = (
    "bbox_obs_id",
    "image_source_id",
    "zone_confirm_frames",
    "zone_confirm_seconds",
    "centroid_smoothing_alpha",
)

_config = None


def load_experiment_config():
    global _config
    if _config is None:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _config = json.load(f)
    return _config


def default_params_for(experiment_name):
    """
    Flat params dict for one experiment: shared detection settings, mapped zones,
    then that experiment's own timings and trial counts.
    """
    config = load_experiment_config()
    try:
        spec = config["experiments"][experiment_name]
    except KeyError as exc:
        raise KeyError(
            f"No experiment_config entry for {experiment_name!r}"
        ) from exc

    shared = config["shared"]
    zones = shared["zones"]
    params = {key: deepcopy(shared[key]) for key in _SHARED_KEYS}

    for param_key, zone_ref in spec.get("zones", {}).items():
        if isinstance(zone_ref, str):
            try:
                params[param_key] = deepcopy(zones[zone_ref])
            except KeyError as exc:
                raise KeyError(
                    f"Unknown shared zone {zone_ref!r} for {experiment_name}"
                ) from exc
        else:
            params[param_key] = deepcopy(zone_ref)

    params.update(deepcopy(spec.get("params") or {}))
    return params
