from video_stream import ImageObserver
import numpy as np
import video_system
import data_log
import experiment as exp
from pathlib import Path

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


import time
from threading import Lock
from collections import deque
from functools import wraps


class RateLimiter:
    def __init__(self, max_calls=4, time_window=1.0):
        """
        Initialize rate limiter

        Args:
            max_calls (int): Maximum number of calls allowed in the time window
            time_window (float): Time window in seconds
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = deque()
        self.lock = Lock()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self.lock:
                # Remove old calls outside the time window
                now = time.time()
                while self.calls and now - self.calls[0] >= self.time_window:
                    self.calls.popleft()

                # If we've reached the limit, wait until we can make another call
                if len(self.calls) >= self.max_calls:
                    sleep_time = self.calls[0] + self.time_window - now
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                        self.calls.popleft()

                # Make the call and record the timestamp
                self.calls.append(now)
                return func(*args, **kwargs)

        return wrapper



class YOLOv7ImageObserver(ImageObserver):
    """
    YOLOv7 object detector that outputs bounding box coordinates and confidence.
    Output format: [x1, y1, x2, y2, confidence] in normalized coordinates.
    """

    default_params = {
        **ImageObserver.default_params,
        "adapter_name": "yolov7_bbox",
        "model_path": "/home/tal/dev/yolov7/turtle_test.pt",
        "yolo_repo_path": "/home/tal/dev/reptiLearn/system/image_observers/yolo_repo",
        "imgsz": 640,
        "conf_thres": 0.5,
        "device": "cuda"  # or "cpu"
    }

    def _init(self):
        """Initialize the YOLOv7 detector"""
        super()._init()

        from image_observers.detector import create_detector
        self.detector = create_detector(
            adapter_name=str(self.get_config("adapter_name")),
            model_path=str(self.get_config("model_path")),
            device=str(self.get_config("device")),
            imgsz=int(self.get_config("imgsz")),
            yolo_repo_path=str(self.get_config("yolo_repo_path")),
        )

    def _setup(self):
        """Called when the observer process starts"""
        try:
            self.detector.load()
            self.log.info(f"{self.get_config('adapter_name')} detector loaded successfully.")
            self.nan_det = np.empty_like(self.output)
            self.nan_det[:] = np.nan

        except Exception as e:
            self.log.error(f"Setup failed: {str(e)}")
            raise

    def _on_start(self):
        """Called when observation starts"""
        self.log.info("Starting object detection.")
        src_fps = self._img_src_config.get("frame_rate", 0) if self._img_src_config else 0
        self._target_frame_dt = (1.0 / src_fps) if src_fps and src_fps > 0 else None
        self._perf_warn_last_ts = 0.0

    def _on_stop(self):
        """Called when observation stops"""
        self.log.info("Stopping object detection.")

    def _on_image_update(self, img, timestamp):
        """Process new image and update output buffer"""
        t0 = time.time()

        if img.dtype == "uint16":
            img = (img / 256.0).astype("uint8")

        # Run detection
        detections = self.detector.detect(img, conf_threshold=self.get_config("conf_thres"))

        if not detections:
            self._update_output(self.nan_det)
            return

        # Get the detection with highest confidence
        best_detection = max(detections, key=lambda x: x['confidence'])
        # Output format (normalized): [x1, y1, x2, y2, confidence, kpts...]
        # For bbox-only adapters, keep keypoint slots as NaN.
        out_len = self.output_shape[0] if isinstance(self.output_shape, tuple) else int(self.output_shape)
        output = np.empty((out_len,), dtype=np.float64)
        output[:] = np.nan
        output[:5] = np.array(
            best_detection["bbox"] + [best_detection["confidence"]],
            dtype=np.float64,
        )
        keypoints = best_detection.get("keypoints")
        if keypoints:
            flat_kpts = []
            for kp in keypoints:
                if len(kp) >= 2:
                    flat_kpts.extend([kp[0], kp[1]])
            max_kpts_values = out_len - 5
            output[5 : 5 + min(len(flat_kpts), max_kpts_values)] = np.array(
                flat_kpts[:max_kpts_values],
                dtype=np.float64,
            )
        self._update_output(output)

        now = time.time()
        dt = now - t0
        if (
            self._target_frame_dt is not None
            and dt > self._target_frame_dt
            and now - self._perf_warn_last_ts > 5.0
        ):
            self.log.warning(
                "Detector processing is slower than frame interval "
                f"(dt={dt:.3f}s, frame_dt={self._target_frame_dt:.3f}s). "
                "Consider reducing detector rate or image size if stream jitter appears."
            )
            self._perf_warn_last_ts = now

    def _get_buffer_opts(self):
        # [x1, y1, x2, y2, confidence] + up to 8 keypoints (x,y) = 21 values
        return "d", 21, (21,), np.double


class YOLOv11ImageObserver(YOLOv7ImageObserver):
    """
    YOLOv11n-pose object detector and pose estimation model that outputs bounding box coordinates, pose estimation, and confidence.
    Output format: bbox coordinates, 8 poses coordinates, and confidence.
    """

    default_params = {
        **YOLOv7ImageObserver.default_params,
        "adapter_name": "yolov11_pose",
        "model_path": "/home/tal/dev/reptiLearn/system/image_observers/yolov11n-pose/model_v2.pt",
        "conf_thres": 0.7
    }

    def _init(self):
        """Initialize the YOLOv11 detector"""
        super()._init()


class BBoxDataCollector:
    """
    Session CSV (+ optional TimescaleDB) logging for one ImageObserver.

    Inference and stream overlays stay on continuously via video_system.start_processes();
    this collector only attaches the ObserverLogger queue + listener. Never call
    stop_observing() here — that would halt the model updates and overlays when an
    experiment ends.
    """

    def __init__(self, obs_id):
        self.obs = None
        self.bbox_log = None
        self.remove_listener = None
        self.obs_id = obs_id

    @staticmethod
    def _logger_columns(observer: ImageObserver):
        """CSV/DB columns: time + flattened observer buffer (bbox, conf, optional keypoints)."""
        n_out = int(np.asarray(observer.output).size)
        if n_out < 5:
            raise ValueError(
                f"Observer '{observer.id}' output length {n_out} < 5 (expected bbox + confidence)"
            )
        extra = n_out - 5
        if extra % 2 != 0:
            raise ValueError(
                f"Observer '{observer.id}' output length {n_out}: keypoint tail must have even length"
            )
        kp_pairs = extra // 2
        cols = [
            ("time", "timestamptz not null"),
            ("x1", "double precision"),
            ("y1", "double precision"),
            ("x2", "double precision"),
            ("y2", "double precision"),
            ("confidence", "double precision"),
        ]
        for i in range(1, kp_pairs + 1):
            cols.extend(
                [
                    (f"kp{i}_x", "double precision"),
                    (f"kp{i}_y", "double precision"),
                ]
            )
        return cols

    def start(self, listener=None):
        if self.obs_id not in video_system.image_observers:
            raise ValueError(f"Unknown image observer '{self.obs_id}'")

        self.obs: ImageObserver = video_system.image_observers[self.obs_id]

        if listener is not None:
            # NOTE: assuming this runs on the main process
            self.remove_listener = self.obs.add_listener(listener, exp.state)

        n_out = int(np.asarray(self.obs.output).size)
        kp_pairs = max(0, (n_out - 5) // 2)

        columns = self._logger_columns(self.obs)
        # Keeps bbox-only logs on bbox_position; pose-sized buffers use a wider hypertable.
        db_table_name = "bbox_pose" if kp_pairs > 0 else "bbox_position"

        self.bbox_log = data_log.ObserverLogger(
            self.obs,
            columns=columns,
            csv_path=exp.session_state["data_dir"] / (self.obs_id + ".csv"),
            db_table_name=db_table_name,
            split_csv=True,
        )
        self.bbox_log.start()

    def stop(self):
        if self.bbox_log:
            try:
                self.bbox_log.stop()
            except Exception:
                pass
            self.bbox_log = None
        if self.remove_listener:
            try:
                self.remove_listener()
            except Exception:
                # Observer may already be shut down after a video restart.
                pass
            self.remove_listener = None
        self.obs = None
