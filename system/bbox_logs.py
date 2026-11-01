"""
Locate bbox/pose logs written by BBoxDataCollector.

Live runs still append CSV chunks ({obs_id}.csv and {obs_id}_YYYYMMDD-HHMMSS.csv).
Archived chunks may be stored as Parquet with the same stem. When both exist,
readers use the Parquet file.
"""

from pathlib import Path


def bbox_log_paths(directory: Path, obs_id: str) -> list[Path]:
    """CSV and Parquet chunks for one observer, Parquet preferred per stem."""
    directory = Path(directory)
    found: list[Path] = []
    for path in (
        directory / f"{obs_id}.csv",
        directory / f"{obs_id}.parquet",
    ):
        if path.is_file():
            found.append(path)
    found.extend(p for p in directory.glob(f"{obs_id}_*.csv") if p.is_file())
    found.extend(p for p in directory.glob(f"{obs_id}_*.parquet") if p.is_file())
    return _prefer_parquet(found)


def prefer_parquet(paths: list[Path]) -> list[Path]:
    by_stem: dict[str, Path] = {}
    for path in paths:
        key = str(path.with_suffix(""))
        current = by_stem.get(key)
        if current is None or path.suffix == ".parquet":
            by_stem[key] = path
    return [by_stem[key] for key in sorted(by_stem)]


def _prefer_parquet(paths: list[Path]) -> list[Path]:
    return prefer_parquet(paths)
