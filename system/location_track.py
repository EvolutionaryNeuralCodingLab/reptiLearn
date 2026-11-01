"""
Bbox track and live detection for the location tab.

The picture asks for the playhead time. The reader seeks to that time in the
bbox logs and returns the few seconds around it, at about 10 Hz. The whole
session stays on disk. Heading is not stored; the UI infers it from trial events.
"""

import csv
import json
import math
import threading
import time
from pathlib import Path

from bbox_logs import bbox_log_paths

SAMPLE_PERIOD = 0.1
WINDOW_BEFORE = 6.0
WINDOW_AFTER = 12.0
ZONE_GAP_SECONDS = 0.5
ZONE_CHUNK_SECONDS = 30.0

_events_cache = {}
_bounds_cache = {}
_zone_jobs = {}
_zone_guard = threading.Lock()

# Suffixes after the last "/". Both magnetoreception/ and
# magnetoreception_training/ names are kept.
_EVENT_SUFFIXES = {
    "trial_start",
    "point_b",
    "back_doors_open",
    "reward",
    "point_d",
    "point_d_via_a",
    "phase_change",
    "exit_door",
    "c_dwell_complete",
    "b_hold_complete",
    "waiting_at_a",
}

_CSV_COLUMNS = ("time", "x1", "y1", "x2", "y2")


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _event_suffix(name):
    if not isinstance(name, str) or not name:
        return ""
    return name.rsplit("/", 1)[-1]


def zones_from_params(params):
    """Rectangle and circle zones from session point_* params."""
    if not isinstance(params, dict):
        return []
    zones = []
    for key, value in params.items():
        if not isinstance(key, str) or not key.startswith("point_"):
            continue
        if not isinstance(value, dict):
            continue
        location = value.get("location")
        if not isinstance(location, (list, tuple)) or len(location) < 2:
            continue
        try:
            coords = [float(item) for item in location]
        except (TypeError, ValueError):
            continue
        zone = {
            "id": key[len("point_") :].upper(),
            "key": key,
            "location": coords,
        }
        radius = _finite(value.get("radius"))
        if radius is not None:
            zone["radius"] = radius
        zones.append(zone)
    return zones


def _session_root():
    from configure import get_config

    return Path(get_config().session_data_root)


def _safe_session_dir(name):
    if not isinstance(name, str) or not name or name != Path(name).name or name in (".", ".."):
        raise ValueError("Invalid session name")
    path = _session_root() / name
    if not (path / "session_state.json").is_file():
        raise FileNotFoundError(f"No session '{name}'")
    return path


def _info_from_dir(path: Path):
    with (path / "session_state.json").open() as handle:
        state = json.load(handle)
    params = state.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return {
        "path": path,
        "id": state.get("id") or path.name,
        "experiment": state.get("experiment"),
        "params": params,
    }


def current_session_info():
    """Open session, or None when no session is loaded."""
    import experiment

    state = experiment.session_state
    try:
        if not state.exists(()):
            return None
        data_dir = state.get("data_dir", None)
    except Exception:
        return None
    if not data_dir:
        return None
    path = Path(str(data_dir))
    params = state.get("params", {}) or {}
    if not isinstance(params, dict):
        params = {}
    return {
        "path": path,
        "id": state.get("id", path.name),
        "experiment": state.get("experiment", None),
        "params": params,
    }


def _image_size(src_id):
    import video_system

    config = video_system.video_config or {}
    sources = config.get("image_sources") or {}
    src = sources.get(src_id) or {}
    shape = src.get("image_shape")
    if not shape or len(shape) < 2:
        return None, None
    height = int(shape[0])
    width = int(shape[1])
    if width <= 0 or height <= 0:
        return None, None
    return width, height


def _bbox_paths(directory: Path, obs_id: str):
    return bbox_log_paths(directory, obs_id)


def _sample(t, x1, y1, x2, y2):
    return {
        "t": t,
        "cx": (x1 + x2) / 2.0,
        "cy": (y1 + y2) / 2.0,
        "w": abs(x2 - x1),
        "h": abs(y2 - y1),
    }


def _push_sample(samples, last_t, t, x1, y1, x2, y2, period):
    if None in (t, x1, y1, x2, y2):
        return last_t
    if last_t is not None and t < last_t + period - 1e-4:
        return last_t
    samples.append(_sample(t, x1, y1, x2, y2))
    return t


def _parse_row(parts, cols):
    try:
        return (
            _finite(parts[cols["time"]]),
            _finite(parts[cols["x1"]]),
            _finite(parts[cols["y1"]]),
            _finite(parts[cols["x2"]]),
            _finite(parts[cols["y2"]]),
        )
    except IndexError:
        return None, None, None, None, None


def _csv_open(path: Path):
    """Return (handle, columns, data_start) or None when the header is unusable."""
    handle = path.open("rb")
    header = handle.readline().decode("utf-8", "replace").strip().split(",")
    cols = {name: i for i, name in enumerate(header)}
    if any(name not in cols for name in _CSV_COLUMNS):
        handle.close()
        return None
    return handle, cols, handle.tell()


def _line_at(handle, pos, data_start, file_size):
    """
    The first complete data line at or after pos.
    Returns (line_start, line_bytes) or None at the end of the file.
    """
    if pos < data_start:
        pos = data_start
    if pos >= file_size:
        return None
    handle.seek(pos)
    if pos > data_start:
        handle.readline()
    line_start = handle.tell()
    if line_start >= file_size:
        return None
    line = handle.readline()
    if not line:
        return None
    return line_start, line


def _seek_time(path: Path, target):
    """
    Byte offset of the first data line whose time is >= target.
    The file size when every row is earlier.
    """
    opened = _csv_open(path)
    if opened is None:
        return None
    handle, cols, data_start = opened
    try:
        file_size = path.stat().st_size
        lo = data_start
        hi = file_size
        while lo < hi:
            mid = (lo + hi) // 2
            found = _line_at(handle, mid, data_start, file_size)
            if found is None:
                hi = mid
                continue
            line_start, line = found
            if line_start >= hi:
                hi = mid
                continue
            t = _parse_row(line.decode("utf-8", "replace").strip().split(","), cols)[0]
            if t is None or t < target:
                lo = handle.tell()
            else:
                hi = line_start
        return lo
    finally:
        handle.close()


def _previous_line(handle, data_start, pos):
    """The data line that ends at pos. pos is the start of the following line."""
    if pos <= data_start:
        return None
    back = min(pos - data_start, 8192)
    while True:
        handle.seek(pos - back)
        chunk = handle.read(back)
        # The byte just before pos is the newline that ends the line we want,
        # so search only in front of that trailing break.
        cut = chunk.rfind(b"\n", 0, max(0, len(chunk) - 1))
        if cut >= 0:
            handle.seek(pos - back + cut + 1)
            return handle.readline()
        if pos - back <= data_start:
            handle.seek(data_start)
            return handle.readline()
        back = min(pos - data_start, back * 4)


def _row_from_line(line, cols):
    if not line:
        return None
    t, x1, y1, x2, y2 = _parse_row(line.decode("utf-8", "replace").strip().split(","), cols)
    if None in (t, x1, y1, x2, y2):
        return None
    return _sample(t, x1, y1, x2, y2)


def _read_csv_between(path: Path, t0, t1, period):
    opened = _csv_open(path)
    if opened is None:
        return []
    handle, cols, data_start = opened
    samples = []
    last_t = None
    try:
        offset = _seek_time(path, t0)
        if offset is None:
            return []
        file_size = path.stat().st_size
        if offset >= file_size:
            return []
        handle.seek(offset)
        rows = 0
        while True:
            line = handle.readline()
            if not line:
                break
            rows += 1
            if rows % 4000 == 0:
                time.sleep(0.002)
            t, x1, y1, x2, y2 = _parse_row(line.decode("utf-8", "replace").strip().split(","), cols)
            if t is None:
                continue
            if t < t0:
                continue
            if t > t1:
                break
            last_t = _push_sample(samples, last_t, t, x1, y1, x2, y2, period)
    finally:
        handle.close()
    return samples


def _latest_csv_at_or_before(path: Path, t):
    opened = _csv_open(path)
    if opened is None:
        return None
    handle, cols, data_start = opened
    try:
        offset = _seek_time(path, t)
        if offset is None:
            return None
        file_size = path.stat().st_size
        if offset < file_size:
            handle.seek(offset)
            sample = _row_from_line(handle.readline(), cols)
            if sample is not None and sample["t"] <= t:
                return sample
        line = _previous_line(handle, data_start, min(offset, file_size))
        sample = _row_from_line(line, cols)
        if sample is not None and sample["t"] <= t:
            return sample
        return None
    finally:
        handle.close()


def _parquet_bounds(path: Path):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    names = list(parquet.schema_arrow.names)
    if "time" not in names:
        return None, None
    index = names.index("time")
    groups = parquet.num_row_groups
    if groups <= 0:
        return None, None
    first = parquet.metadata.row_group(0).column(index).statistics
    last = parquet.metadata.row_group(groups - 1).column(index).statistics
    if first is None or last is None or not first.has_min_max or not last.has_min_max:
        return None, None
    return _finite(first.min), _finite(last.max)


def _read_parquet_between(path: Path, t0, t1, period):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    names = list(parquet.schema_arrow.names)
    if any(name not in names for name in _CSV_COLUMNS):
        return []
    index = names.index("time")
    samples = []
    last_t = None
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(index).statistics
        if stats is not None and stats.has_min_max:
            if stats.max < t0 or stats.min > t1:
                continue
        table = parquet.read_row_group(group, columns=list(_CSV_COLUMNS))
        frame = table.to_pandas()
        for t, x1, y1, x2, y2 in zip(
            frame["time"], frame["x1"], frame["y1"], frame["x2"], frame["y2"]
        ):
            t = _finite(t)
            if t is None or t < t0:
                continue
            if t > t1:
                return samples
            last_t = _push_sample(
                samples, last_t, t, _finite(x1), _finite(y1), _finite(x2), _finite(y2), period
            )
    return samples


def _latest_parquet_at_or_before(path: Path, t):
    samples = _read_parquet_between(path, t - 5.0, t, 0.0)
    if not samples:
        return None
    return samples[-1]


def _first_csv_time(path: Path):
    opened = _csv_open(path)
    if opened is None:
        return None
    handle, cols, _data_start = opened
    try:
        sample = _row_from_line(handle.readline(), cols)
        return None if sample is None else sample["t"]
    finally:
        handle.close()


def _last_csv_time(path: Path):
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - 16384))
        chunk = handle.read()
    lines = [line for line in chunk.splitlines() if line]
    if handle_start_partial(size):
        lines = lines[1:]
    opened = _csv_open(path)
    if opened is None:
        return None
    _handle, cols, _data_start = opened
    _handle.close()
    for line in reversed(lines):
        sample = _row_from_line(line, cols)
        if sample is not None:
            return sample["t"]
    return None


def handle_start_partial(size):
    return size > 16384


def _file_bounds(path: Path):
    try:
        size = path.stat().st_size
    except OSError:
        return None, None
    key = str(path)
    cached = _bounds_cache.get(key)
    if cached and cached["size"] == size:
        return cached["t0"], cached["t1"]
    if path.suffix == ".parquet":
        t0, t1 = _parquet_bounds(path)
    else:
        t0 = cached["t0"] if cached and cached.get("t0") is not None else _first_csv_time(path)
        t1 = _last_csv_time(path)
    _bounds_cache[key] = {"size": size, "t0": t0, "t1": t1}
    return t0, t1


def _read_file_between(path: Path, t0, t1, period):
    if path.suffix == ".parquet":
        return _read_parquet_between(path, t0, t1, period)
    return _read_csv_between(path, t0, t1, period)


def _latest_in_file(path: Path, t):
    if path.suffix == ".parquet":
        return _latest_parquet_at_or_before(path, t)
    return _latest_csv_at_or_before(path, t)


def _overlapping_files(directory: Path, obs_id: str, t0, t1):
    chosen = []
    for path in _bbox_paths(directory, obs_id):
        start, end = _file_bounds(path)
        if start is None or end is None:
            continue
        if end < t0 or start > t1:
            continue
        chosen.append(path)
    return chosen


def _samples_between(directory: Path, obs_id: str, t0, t1, period=SAMPLE_PERIOD):
    samples = []
    last_t = None
    for path in _overlapping_files(directory, obs_id, t0, t1):
        for sample in _read_file_between(path, t0, t1, period):
            if last_t is not None and sample["t"] < last_t + period - 1e-4:
                continue
            samples.append(sample)
            last_t = sample["t"]
    return samples


def _latest_at_or_before(directory: Path, obs_id: str, t):
    previous = None
    for path in _bbox_paths(directory, obs_id):
        start, end = _file_bounds(path)
        if start is None or end is None or start > t:
            continue
        if end < t:
            previous = path
            continue
        sample = _latest_in_file(path, t)
        if sample is not None:
            return sample
    if previous is not None:
        return _latest_in_file(previous, t)
    return None


def session_span(directory: Path, obs_id: str):
    """First and last detection time in the session, from the file edges."""
    start = None
    end = None
    for path in _bbox_paths(directory, obs_id):
        t0, t1 = _file_bounds(path)
        if t0 is None or t1 is None:
            continue
        start = t0 if start is None else min(start, t0)
        end = t1 if end is None else max(end, t1)
    return start, end


def read_window(directory: Path, obs_id: str, t, before=WINDOW_BEFORE, after=WINDOW_AFTER):
    """
    Detections in [t - before, t + after], plus the last detection at or
    before t when the window itself does not contain one.
    """
    if t is None:
        return []
    samples = _samples_between(directory, obs_id, t - before, t + after)
    if not any(sample["t"] <= t for sample in samples):
        previous = _latest_at_or_before(directory, obs_id, t)
        if previous is not None:
            samples.insert(0, previous)
    return samples


def read_events(directory: Path):
    path = directory / "events.csv"
    if not path.is_file():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    key = str(path)
    cached = _events_cache.get(key)
    if cached and cached[0] == size:
        return cached[1]
    events = []
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = row.get("event") or ""
            if _event_suffix(name) not in _EVENT_SUFFIXES:
                continue
            t = _finite(row.get("time"))
            if t is None:
                continue
            value = {}
            raw = row.get("value")
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    value = parsed
            events.append({"t": t, "event": name, "value": value})
    events.sort(key=lambda item: item["t"])
    _events_cache[key] = (size, events)
    return events


def _zone_of(cx, cy, zones, width, height):
    best = None
    best_area = math.inf
    for zone in zones:
        loc = zone.get("location") or []
        if len(loc) >= 4:
            if not (loc[0] <= cx <= loc[2] and loc[1] <= cy <= loc[3]):
                continue
            area = abs((loc[2] - loc[0]) * (loc[3] - loc[1]))
        elif len(loc) >= 2 and zone.get("radius") and width and height:
            px = cx * width
            py = cy * height
            dx = px - loc[0] * width
            dy = py - loc[1] * height
            radius = zone["radius"] * min(width, height)
            if dx * dx + dy * dy > radius * radius:
                continue
            area = math.pi * radius * radius
        else:
            continue
        if area < best_area:
            best = zone.get("id")
            best_area = area
    return best


def _accumulate_zones(last, samples, zones, width, height):
    """Turn detections into counted stretches. Gaps longer than half a second are dropped."""
    segments = []
    for sample in samples:
        zone = _zone_of(sample["cx"], sample["cy"], zones, width, height)
        if last is not None:
            dt = sample["t"] - last["t"]
            if 0 < dt <= ZONE_GAP_SECONDS and last["zone"]:
                segments.append({"t0": last["t"], "t1": sample["t"], "zone": last["zone"]})
        last = {"t": sample["t"], "zone": zone}
    return segments, last


def _merge_segments(existing, extra):
    for segment in extra:
        if (
            existing
            and existing[-1]["zone"] == segment["zone"]
            and abs(existing[-1]["t1"] - segment["t0"]) < 1e-3
        ):
            existing[-1]["t1"] = segment["t1"]
        else:
            existing.append(segment)


def _trial_bounds(events, t, span_end):
    if t is None:
        return None, None
    start = None
    for event in events:
        if event["t"] > t:
            break
        if _event_suffix(event["event"]) == "trial_start":
            start = event["t"]
    if start is None:
        return None, None
    end = span_end if span_end is not None else t
    for event in events:
        if event["t"] <= start:
            continue
        if _event_suffix(event["event"]) == "trial_start":
            end = event["t"]
            break
    return start, end


class _ZoneJob:
    def __init__(self, directory: Path, obs_id: str):
        self.directory = directory
        self.obs_id = obs_id
        self.lock = threading.Lock()
        self.generation = 0
        self.busy = False
        self.trial_t0 = None
        self.scanned_until = None
        self.target = None
        self.span_end = None
        self.segments = []
        self.last = None
        self.zones = []
        self.width = 0
        self.height = 0


def _zone_job(directory: Path, obs_id: str):
    key = f"{directory}:{obs_id}"
    with _zone_guard:
        job = _zone_jobs.get(key)
        if job is None:
            job = _ZoneJob(directory, obs_id)
            _zone_jobs[key] = job
        return job


def _zone_worker(job: _ZoneJob, generation):
    while True:
        with job.lock:
            if job.generation != generation:
                return
            target = job.target
            scanned = job.scanned_until
            if target is None or scanned is None or scanned >= target - 0.05:
                job.busy = False
                return
            t0 = scanned
            t1 = min(target, t0 + ZONE_CHUNK_SECONDS)
            last = job.last
            zones = list(job.zones)
            width = job.width
            height = job.height
            directory = job.directory
            obs_id = job.obs_id
            span_end = job.span_end
        samples = _samples_between(directory, obs_id, t0, t1)
        segments, last = _accumulate_zones(last, samples, zones, width, height)
        if samples:
            reached = t1
        elif span_end is not None and span_end < t1 - 1.0:
            reached = max(t0, span_end)
        else:
            reached = t1
        with job.lock:
            if job.generation != generation:
                return
            if reached <= t0 + 1e-3:
                job.busy = False
                return
            _merge_segments(job.segments, segments)
            job.last = last
            job.scanned_until = reached
        time.sleep(0.02)


def _kick_zone(job: _ZoneJob):
    with job.lock:
        if job.busy:
            return
        job.busy = True
        generation = job.generation
    threading.Thread(target=_zone_worker, args=(job, generation), daemon=True).start()


def _zone_state(directory, obs_id, events, at_time, span_end, zones, width, height):
    """
    Counted zone stretches for the trial under the playhead.
    The count is built in the background, thirty seconds at a time.
    """
    start, end = _trial_bounds(events, at_time, span_end)
    job = _zone_job(directory, obs_id)
    with job.lock:
        job.zones = zones
        job.width = width or 0
        job.height = height or 0
        job.span_end = span_end
        if start is None:
            job.generation += 1
            job.busy = False
            return [], True
        target = min(at_time, end) if end is not None else at_time
        ahead = target + ZONE_CHUNK_SECONDS
        if end is not None:
            ahead = min(ahead, end)
        if job.trial_t0 != start:
            job.generation += 1
            job.busy = False
            job.trial_t0 = start
            job.scanned_until = start
            job.segments = []
            job.last = None
        job.target = ahead
        scanned = job.scanned_until
        ready = scanned is not None and scanned >= target - 0.05
        segments = list(job.segments)
        need = scanned is None or scanned < ahead - 0.05
    if need:
        _kick_zone(job)
    return segments, ready


def _resolve(session_name):
    current = current_session_info()
    if session_name:
        path = _safe_session_dir(session_name)
        info = _info_from_dir(path)
        is_current = False
        if current is not None:
            try:
                is_current = Path(current["path"]).resolve() == path.resolve()
            except OSError:
                is_current = Path(current["path"]).name == path.name
        return info, is_current
    if current is None:
        return None, False
    return current, True


def empty_track():
    width, height = _image_size("top")
    return {
        "session": None,
        "session_id": None,
        "experiment": None,
        "is_current": False,
        "obs_id": "1",
        "image_source_id": "top",
        "image_width": width,
        "image_height": height,
        "has_point_d": False,
        "ready": True,
        "error": None,
        "zones": [],
        "samples": [],
        "events": [],
        "span_start": None,
        "span_end": None,
        "at": None,
        "zone_segments": [],
        "zone_ready": True,
    }


def load_track(session_name=None, at_time=None):
    """
    Events for the whole session, and bbox samples around at_time.
    at_time is epoch seconds. When it is missing, the window is the end of the log.
    """
    info, is_current = _resolve(session_name)
    if info is None:
        return empty_track()
    path = Path(info["path"])
    params = info["params"]
    obs_id = str(params.get("bbox_obs_id") or "1")
    src_id = str(params.get("image_source_id") or "top")
    width, height = _image_size(src_id)
    zones = zones_from_params(params)
    events = read_events(path)
    span_start, span_end = session_span(path, obs_id)
    at = at_time if at_time is not None else span_end
    samples = read_window(path, obs_id, at) if at is not None else []
    segments, zone_ready = _zone_state(
        path, obs_id, events, at, span_end, zones, width, height
    )
    return {
        "session": path.name,
        "session_id": info.get("id"),
        "experiment": info.get("experiment"),
        "is_current": is_current,
        "ready": True,
        "error": None,
        "obs_id": obs_id,
        "image_source_id": src_id,
        "image_width": width,
        "image_height": height,
        "has_point_d": any(zone["key"] == "point_d" for zone in zones),
        "zones": zones,
        "samples": samples,
        "events": events,
        "span_start": span_start,
        "span_end": span_end,
        "at": at,
        "zone_segments": segments,
        "zone_ready": zone_ready,
    }


def live_sample():
    """Latest observer detection for the open session's bbox observer."""
    import video_system

    current = current_session_info()
    obs_id = "1"
    if current is not None:
        obs_id = str(current["params"].get("bbox_obs_id") or "1")
    observer = video_system.image_observers.get(obs_id)
    if observer is None:
        return {"obs_id": obs_id, "sample": None}
    try:
        with observer.output_buf.get_lock():
            raw = [observer.output[i] for i in range(min(5, int(observer.output.size)))]
            timestamp = float(observer.output_timestamp.value)
    except Exception:
        return {"obs_id": obs_id, "sample": None}
    if len(raw) < 4 or timestamp <= 0:
        return {"obs_id": obs_id, "sample": None}
    x1, y1, x2, y2 = (_finite(raw[0]), _finite(raw[1]), _finite(raw[2]), _finite(raw[3]))
    if None in (x1, y1, x2, y2):
        return {"obs_id": obs_id, "sample": None}
    confidence = _finite(raw[4]) if len(raw) > 4 else None
    return {
        "obs_id": obs_id,
        "sample": {
            "t": timestamp,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "cx": (x1 + x2) / 2.0,
            "cy": (y1 + y2) / 2.0,
            "confidence": confidence,
        },
    }
