from video_stream import ImageObserver
import numpy as np
import video_system
import data_log
import experiment as exp
from pathlib import Path
import logging
import torch

class YOLOv4ImageObserver(ImageObserver):
    default_params = {
        **ImageObserver.default_params,
        "cfg_path": None,
        "weights_path": None,
        "meta_path": "image_observers/YOLOv4/obj.data",
        "conf_thres": 0.9,
        "nms_thres": 0.6,
    }

    def _init(self):
        from image_observers.YOLOv4.detector import YOLOv4Detector

        super()._init()
        yolo_config = dict(self.config)

        del yolo_config["src_id"]
        del yolo_config["class"]

        self.detector = YOLOv4Detector(**yolo_config, return_nearest_detection=True)

    def _setup(self):
        self.detector.load()
        self.log.info(
            f"YOLOv4 detector loaded successfully ({self.detector.model_width}x{self.detector.model_height} cfg: {self.detector.cfg_path} weights: {self.detector.weights_path})."
        )
        self.nan_det = np.empty_like(self.output)
        self.nan_det[:] = np.nan

    def _on_start(self):
        self.log.info("Starting object detection.")

    def _on_stop(self):
        self.log.info("Stopping object detection.")

    def _on_image_update(self, img, _):
        if img.dtype == "uint16":
            img = (img / 256.0).astype("uint8")

        det = self.detector.detect_image(img)
        self._update_output(det if det is not None else self.nan_det)

    def _get_buffer_opts(self):
        return "d", 5, 5, np.double


def _release(self):
    """Cleanup when the observer is shut down"""
    self.log.info("Releasing YOLOv7 detector resources.")


class YOLOv7ImageObserver(ImageObserver):
    default_params = {
        **ImageObserver.default_params,
        "model_path": "/home/tal/dev/reptiLearn/system/image_observers/yolov7/turtle_test.pt",
        "yolov7_path": "/home/tal/dev/reptiLearn/system/image_observers/yolov7",
        "conf_thres": 0.5,
        "device": "cuda"  # or "cpu"
    }

    def _init(self):
        from image_observers.YOLOv7.detector import YOLOv7Detector

        from pathlib import Path
        super()._init()
        # yolo_config = dict(self.config
        #
        # del yolo_config["src_id"]
        # del yolo_config["class"]


        # Expand paths
        model_path = Path(self.default_params["model_path"]).expanduser()
        yolov7_path = Path(self.default_params["yolov7_path"]).expanduser()


        # Initialize detector
        self.detector = YOLOv7Detector(
            model_path=str(model_path),
            yolov7_path=str(yolov7_path)
        )

        # Initialize empty output array for when no detections are found
        self.nan_det = np.empty((5,), dtype=np.float64)
        self.nan_det[:] = np.nan

    def _setup(self):
        # No separate load step needed as model is loaded in __init__
        self.log.info(
            f"YOLOv7 detector loaded successfully (640x640 model)."
        )

    def _on_start(self):
        self.log.info("Starting object detection.")

    def _on_stop(self):
        self.log.info("Stopping object detection.")

    def _on_image_update(self, img, _):
        # Convert 16-bit images to 8-bit if necessary
        if img.dtype == "uint16":
            img = (img / 256.0).astype("uint8")
        self.log.info(f"cuda: {torch.cuda.is_available()}")
        # Run detection
        detections = self.detector.detect(img)

        if not detections:
            self._update_output(self.nan_det)
            return

        # Get the detection with highest confidence
        best_detection = max(detections, key=lambda x: x['confidence'])

        # Format output as [x1, y1, x2, y2, confidence]
        output = np.array(best_detection['bbox'] + [best_detection['confidence']], dtype=np.float64)
        self._update_output(output)

    def _get_buffer_opts(self):
        return "d", 5, 5, np.double


class BBoxDataCollector:
    def __init__(self, obs_id):
        self.obs = None
        self.bbox_log = None
        self.remove_listener = None
        self.obs_id = obs_id

    def start(self, listener=None):
        if self.obs_id not in video_system.image_observers:
            raise ValueError(f"Unknown image observer '{self.obs_id}'")

        self.obs: ImageObserver = video_system.image_observers[self.obs_id]

        if listener is not None:
            # NOTE: assuming this runs on the main process
            self.remove_listener = self.obs.add_listener(listener, exp.state)

        self.bbox_log = data_log.ObserverLogger(
            self.obs,
            columns=[
                ("time", "timestamptz not null"),
                ("x1", "double precision"),
                ("y1", "double precision"),
                ("x2", "double precision"),
                ("y2", "double precision"),
                ("confidence", "double precision"),
            ],
            csv_path=exp.session_state["data_dir"] / (self.obs_id + ".csv"),
            db_table_name="bbox_position",
            split_csv=True,
        )
        self.bbox_log.start()
        self.obs.start_observing()

    def stop(self):
        if self.obs:
            self.obs.stop_observing()
        if self.bbox_log:
            self.bbox_log.stop()
        if self.remove_listener:
            self.remove_listener()
