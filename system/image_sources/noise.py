from video_stream import ImageSource
import time
import numpy as np


class NoiseImageSource(ImageSource):
    default_params = {
        **ImageSource.default_params,
        "frame_rate": 30,  # add an additional parameter with default value 30.
    }

    def _on_start(self):
        try:
            self.log.info(f"Image source starting")
            return True
        except Exception:  # return False to stop a failed image source
            self.log.exception("Exception while initializing camera:")
            return False

    def _acquire_image(self):
        try:
            t = time.time()
            img = (np.random.randint(0, 256, size=self.image_shape, dtype=np.uint8),)
            dt = time.time() - t
            time.sleep(1 / self.get_config("frame_rate") - dt)

            # generate a stream of random data for the given image shape
            return (
                img,
                time.time(),
            )

        except Exception:
            self.log.exception("Exception while acquiring image:")
            return None, None

    def _on_stop(self):
        self.log.info("Stopping image source.")
