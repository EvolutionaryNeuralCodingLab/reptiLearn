"""
Draw experiment zone params (point_*) on live video streams.
"""

import cv2

ZONE_COLORS = [
    (0, 255, 0),
    (255, 0, 255),
    (0, 200, 255),
    (255, 150, 0),
    (100, 255, 150),
    (255, 100, 100),
]
CENTROID_COLOR = (0, 0, 255)


def _color_for_index(index):
    return ZONE_COLORS[index % len(ZONE_COLORS)]


def _zone_label(key):
    if key.startswith("point_"):
        name = key[6:]
    else:
        name = key
    return name[:1].upper() + name[1:] if name else key


def _normalize_location(location):
    if location is None:
        return None
    if isinstance(location, dict):
        try:
            indices = sorted(location.keys(), key=lambda k: int(k))
            return [float(location[k]) for k in indices]
        except (ValueError, TypeError):
            return None
    try:
        coords = [float(x) for x in location]
    except (TypeError, ValueError):
        return None
    return coords if len(coords) >= 2 else None


def get_zone_defs(params, src_id):
    if not params:
        return []

    source_id = params.get("image_source_id")
    if source_id and source_id != src_id:
        return []

    zones = []
    for key, val in params.items():
        if not key.startswith("point_") or not hasattr(val, "get"):
            continue
        location = _normalize_location(val.get("location"))
        if not location:
            continue
        zones.append((key, {**val, "location": location}))
    return zones


def _ensure_bgr(img):
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 1:
        return cv2.cvtColor(img.squeeze(-1), cv2.COLOR_GRAY2BGR)
    return img


def _draw_centroid(img, cx, cy):
    cv2.drawMarker(
        img,
        (cx, cy),
        CENTROID_COLOR,
        markerType=cv2.MARKER_CROSS,
        markerSize=14,
        thickness=2,
        line_type=cv2.LINE_AA,
    )
    cv2.circle(img, (cx, cy), 5, CENTROID_COLOR, -1, lineType=cv2.LINE_AA)


def _put_label(img, text, x, y, color):
    cv2.putText(
        img,
        text,
        (x, max(16, y - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        color,
        1,
        cv2.LINE_AA,
    )


def _draw_zones(img, zones):
    h, w = img.shape[:2]
    min_dim = min(w, h)

    for i, (key, zone) in enumerate(zones):
        color = _color_for_index(i)
        label = _zone_label(key)
        loc = zone["location"]

        if len(loc) == 4:
            x1, y1, x2, y2 = loc
            xa, xb = int(x1 * w), int(x2 * w)
            ya, yb = int(y1 * h), int(y2 * h)
            cv2.rectangle(img, (xa, ya), (xb, yb), color, 2)
            cx = int(round((xa + xb) / 2))
            cy = int(round((ya + yb) / 2))
            _draw_centroid(img, cx, cy)
            _put_label(img, label, xa, ya, color)
        else:
            cx = int(round(loc[0] * w))
            cy = int(round(loc[1] * h))
            radius = max(1, int(round(zone.get("radius", 0) * min_dim)))
            cv2.circle(img, (cx, cy), radius, color, 2, lineType=cv2.LINE_AA)
            _draw_centroid(img, cx, cy)
            _put_label(img, label, cx - radius, cy - radius, color)

    return img


def _get_session_params():
    import experiment

    if not experiment.session_state.exists(()):
        return None
    try:
        return experiment.session_state.get("params")
    except KeyError:
        return None


def apply_zone_overlay(img, src_id):
    params = _get_session_params()
    zones = get_zone_defs(params, src_id)
    if not zones:
        return img

    img = _ensure_bgr(img)
    return _draw_zones(img, zones)
