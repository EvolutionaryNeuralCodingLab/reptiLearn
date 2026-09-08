"""
EXPERIMENTAL: Manage video overlays that display visual information on top of image source streams.

Author: Tal Eisenberg, 2021
"""

# NOTE: Do NOT import `video_system` at module load time. `video_system` imports
# `overlays.timestamp`, which in turn imports `ConfigurableOverlay`/`ImageOverlay`
# from this module. A top-level `import video_system` here therefore creates a
# circular import that fails when `overlay` is imported as the *first* module
# in a fresh process (e.g. inside a spawned VideoWriter child). `video_system`
# is only needed inside `ObserverOverlay.apply()`, so import it lazily there.

# TODO:
# - way to choose overlays

overlays = {}


def is_point_in_bounds(p, frame):
    px, py = p
    return px >= 0 and px < frame.shape[1] and py >= 0 and py < frame.shape[0]


class ImageOverlay:
    def apply(self, img, timestamp):
        return img


class ConfigurableOverlay(ImageOverlay):
    default_params = {"class": None}

    def __init__(self, config) -> None:
        self.config = config

    def get_config(self, key):
        if key in self.config:
            return self.config[key]
        elif key in self.__class__.default_params:
            return self.__class__.default_params[key]
        else:
            raise KeyError(f"Unknown config key: {key}")


class ObserverOverlay(ConfigurableOverlay):
    default_params = {
        **ConfigurableOverlay.default_params,
        "obs_id": None,
    }

    def apply(self, img, img_timestamp):
        import video_system  # lazy: see top-of-file note about the import cycle.

        obs_id = self.get_config("obs_id")
        if obs_id is None or obs_id not in video_system.image_observers:
            return img

        obs_out, obs_out_timestamp = video_system.image_observers[obs_id].get_output()
        return self.obs_apply(img, img_timestamp, obs_out, obs_out_timestamp)

    def obs_apply(self, img, img_timestamp, obs_out, obs_out_timestamp):
        return img


def apply_overlays(img, timestamp, src_id):
    img = img.copy()
    if src_id in overlays:
        for overlay in overlays[src_id]:
            img = overlay.apply(img, timestamp)
    return img
