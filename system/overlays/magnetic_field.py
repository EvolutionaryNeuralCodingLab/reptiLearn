import cv2
from overlay import ConfigurableOverlay


def _resolve_text_color(img, color):
    """
    OpenCV putText on grayscale images only accepts a scalar; a BGR tuple uses
    the first element (often 0 → black). Convert BGR to luminance for 1-channel frames.
    """
    if len(img.shape) == 2 or (len(img.shape) == 3 and img.shape[2] == 1):
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            b, g, r = float(color[0]), float(color[1]), float(color[2])
            return int(0.114 * b + 0.587 * g + 0.299 * r)
        if isinstance(color, (int, float)):
            return int(color)
        return 255
    if isinstance(color, (list, tuple)):
        return tuple(int(c) for c in color[:3])
    return color


class MagneticFieldOverlay(ConfigurableOverlay):
    """
    Draw TMAG5273 (or other arena magnetometer) readings on the live video stream.
    Expects arena values as [x, y, z, |B|] in microTesla from a tmag5273 interface.

    Readings are cached and updated via a state callback so we never query the state
    store on every video frame (that deep-copies all state and stalled the stream).
    """

    default_params = {
        **ConfigurableOverlay.default_params,
        "interface": "Magnetic Field",
        "arena_state": None,
        "color": (255, 255, 255),
        "font_scale": 2,
        "margin": 10,
        "line_spacing": 28,
        "position": "bottom",
        "timestamp_clearance": 55,
    }

    def __init__(self, config) -> None:
        super().__init__(config)
        self._reading = None
        iface = self.get_config("interface")
        arena_state = self.get_config("arena_state")
        if arena_state is None:
            return

        self._refresh_reading()

        try:

            def on_update(_old, new):
                self._reading = new

            arena_state.add_callback(("values", iface), on_update)
        except Exception:
            pass

    def _refresh_reading(self):
        arena_state = self.get_config("arena_state")
        iface = self.get_config("interface")
        if arena_state is None:
            return
        try:
            if arena_state.exists(("values", iface)):
                self._reading = arena_state["values", iface]
        except Exception:
            pass

    def apply(self, img, timestamp):
        try:
            reading = self._reading
            if reading is None:
                self._refresh_reading()
                reading = self._reading
            if reading is None:
                return img
            if not isinstance(reading, (list, tuple)) or len(reading) < 4:
                return img

            x_uT, y_uT, z_uT, b_uT = (
                float(reading[0]),
                float(reading[1]),
                float(reading[2]),
                float(reading[3]),
            )
            lines = [
                f"X: {x_uT:.1f} uT  Y: {y_uT:.1f} uT  Z: {z_uT:.1f} uT",
                f"|B|: {b_uT:.1f} uT",
            ]

            im_h, _im_w = img.shape[:2]
            font = cv2.FONT_HERSHEY_PLAIN
            font_scale = self.get_config("font_scale")
            color = _resolve_text_color(img, self.get_config("color"))
            margin = self.get_config("margin")
            line_spacing = self.get_config("line_spacing")
            x = margin

            if self.get_config("position") == "bottom":
                clearance = self.get_config("timestamp_clearance")
                base_y = im_h - clearance
                for i, line in enumerate(reversed(lines)):
                    y = base_y - i * line_spacing
                    cv2.putText(
                        img,
                        line,
                        (x, y),
                        fontFace=font,
                        fontScale=font_scale,
                        color=color,
                        thickness=2,
                        lineType=cv2.LINE_AA,
                    )
            else:
                for i, line in enumerate(lines):
                    y = margin + (i + 1) * line_spacing
                    cv2.putText(
                        img,
                        line,
                        (x, y),
                        fontFace=font,
                        fontScale=font_scale,
                        color=color,
                        thickness=2,
                        lineType=cv2.LINE_AA,
                    )
        except Exception:
            pass
        return img
