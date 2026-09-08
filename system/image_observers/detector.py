import torch
import cv2
import numpy as np
from typing import List, Dict, Union
import os
import sys
import contextlib

def letterbox(img: np.ndarray, new_shape=(640, 640), color=(114,), auto=True, stride=32):
    """
    Resize and pad image while meeting stride-multiple constraints.
    Modified for grayscale input.
    """
    shape = img.shape[:2]  # current shape [height, width]

    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

    # Compute padding
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding

    if auto:  # minimum rectangle
        dw, dh = np.mod(dw, stride), np.mod(dh, stride)  # wh padding

    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img




@contextlib.contextmanager
def yolo_repo_context(repo_path: str):
    """Context manager to safely import YOLO code from a configured repo path."""
    # Store original state
    original_cwd = os.getcwd()
    original_path = sys.path.copy()

    try:
        expanded_repo_path = os.path.expanduser(repo_path)
        if not os.path.isdir(expanded_repo_path):
            raise FileNotFoundError(f"YOLO repo path does not exist: {expanded_repo_path}")

        # Add configured YOLO repo to sys.path
        sys.path.insert(0, expanded_repo_path)

        # Change working directory to repo root
        os.chdir(expanded_repo_path)

        yield
    finally:
        # Restore original state
        os.chdir(original_cwd)
        sys.path = original_path


class _YOLORepoDetectorBase:
    """Base detector for repositories exposing YOLOv7-style models/utils modules."""

    def __init__(self, model_path: str, yolo_repo_path: str):
        self.model_path = model_path
        self.yolo_repo_path = yolo_repo_path

    def load(self):
        # Load model
        with yolo_repo_context(self.yolo_repo_path):
            from models.experimental import attempt_load
            from utils.general import check_img_size
            from utils.torch_utils import select_device
            self.model = attempt_load(self.model_path)

        if not self.model:
            raise RuntimeError("No YOLO model was loaded.")

        # Modify first layer for grayscale input if needed
        if self.model.model[0].conv.in_channels == 3:
            print("Converting model from RGB to grayscale input")
            self._convert_to_grayscale()

        self.stride = int(self.model.stride.max())
        self.img_size = check_img_size(640, s=self.stride)  # Ensure image size is multiple of stride

        self.names = self.model.module.names if hasattr(self.model, 'module') else self.model.names


    def _convert_to_grayscale(self):
        """Convert the first layer of the model to accept grayscale input"""
        # Get the first conv layer
        first_conv = self.model.model[0].conv

        # Create new conv layer with 1 input channel
        new_conv = torch.nn.Conv2d(
            in_channels=1,
            out_channels=first_conv.out_channels,
            kernel_size=first_conv.kernel_size,
            stride=first_conv.stride,
            padding=first_conv.padding,
            bias=True if first_conv.bias is not None else False
        )

        # Average the weights across the RGB channels
        if first_conv.weight.shape[1] == 3:  # If it was previously RGB
            new_conv.weight.data = first_conv.weight.data.sum(dim=1, keepdim=True) / 3.0
            if first_conv.bias is not None:
                new_conv.bias.data = first_conv.bias.data

        # Replace the first conv layer
        self.model.model[0].conv = new_conv

    def detect(self, image: np.ndarray, conf_threshold: float = 0.25) -> List[Dict[str, Union[float, List[float]]]]:
        """
        Detect objects in a grayscale image

        Args:
            image: Input image in grayscale format
            conf_threshold: Confidence threshold for detections

        Returns:
            List of dictionaries containing:
                - bbox: [x1, y1, x2, y2] (normalized coordinates)
                - center: [cx, cy] (normalized coordinates)
                - confidence: Detection confidence
                - class_id: Predicted class ID
                - class_name: Class name from model's names list
        """
        # Import here to avoid circular imports

        # Get original image dimensions
        height, width = image.shape[:2]

        # Ensure image is 2D grayscale
        if len(image.shape) == 3:
            if image.shape[2] == 3:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            elif image.shape[2] == 1:
                image = image.squeeze()

        # Preprocess image
        img = letterbox(image, self.img_size, stride=self.stride)
        img = img[None]  # Add channel dimension
        img = np.ascontiguousarray(img)
        img = torch.from_numpy(img)
        img = img.float()
        img /= 255.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Inference
        with torch.no_grad():
            pred = self.model(img)[0]
        with yolo_repo_context(self.yolo_repo_path):
            from utils.general import non_max_suppression
            pred = non_max_suppression(pred, conf_thres=conf_threshold)

        # Process detections
        detections = []
        if len(pred[0]):  # If there are detections
            # Rescale boxes from img_size to original image size
            with yolo_repo_context(self.yolo_repo_path):
                from utils.general import scale_coords
                pred[0][:, :4] = scale_coords(img.shape[2:], pred[0][:, :4], image.shape).round()

            # Convert to normalized coordinates and create detection objects
            for *xyxy, conf, cls in pred[0]:
                # Normalize coordinates
                x1, y1, x2, y2 = (
                    xyxy[0].item() / width,
                    xyxy[1].item() / height,
                    xyxy[2].item() / width,
                    xyxy[3].item() / height
                )

                # Calculate center point
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                class_id = int(cls.item())
                detections.append({
                    'bbox': [x1, y1, x2, y2],
                    'center': [cx, cy],
                    'confidence': conf.item(),
                    'class_id': class_id,
                    'class_name': self.names[class_id]
                })

        return detections


class YOLOv7BBoxAdapter(_YOLORepoDetectorBase):
    """YOLOv7 bbox adapter. Uses shared yolo_repo models/utils modules."""


class YOLOv11BBoxAdapter(_YOLORepoDetectorBase):
    """
    YOLOv11 bbox adapter backed by the same yolo_repo runtime.
    Keep separate class for model-specific behavior/custom post-processing.
    """


class _UltralyticsAdapterBase:
    """Shared Ultralytics adapter implementation."""

    def __init__(self, model_path: str, device: str = "cpu", imgsz: int = 640):
        self.model_path = model_path
        self.device = device
        self.imgsz = imgsz
        self.model = None

    def load(self):
        from ultralytics import YOLO

        self.model = YOLO(self.model_path)

    def _normalize_image(self, image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if len(image.shape) == 3 and image.shape[2] == 1:
            return cv2.cvtColor(image.squeeze(), cv2.COLOR_GRAY2BGR)
        return image

    def _predict(self, image: np.ndarray, conf_threshold: float):
        if self.model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")
        normalized = self._normalize_image(image)
        return self.model.predict(
            source=normalized,
            conf=conf_threshold,
            device=self.device,
            imgsz=self.imgsz,
            verbose=False,
        )


class YOLOv7BBoxUltralyticsAdapter(_UltralyticsAdapterBase):
    """Ultralytics bbox adapter (for bbox-only models)."""

    def detect(self, image: np.ndarray, conf_threshold: float = 0.25) -> List[Dict[str, Union[float, List[float]]]]:
        height, width = image.shape[:2]
        results = self._predict(image, conf_threshold)
        dets = []
        if not results:
            return dets

        result = results[0]
        boxes = result.boxes
        names = result.names if hasattr(result, "names") else {}
        if boxes is None:
            return dets

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy()

        for i in range(len(xyxy)):
            x1, y1, x2, y2 = xyxy[i]
            x1n, y1n, x2n, y2n = x1 / width, y1 / height, x2 / width, y2 / height
            cls_id = int(clss[i])
            dets.append(
                {
                    "bbox": [x1n, y1n, x2n, y2n],
                    "center": [(x1n + x2n) / 2, (y1n + y2n) / 2],
                    "confidence": float(confs[i]),
                    "class_id": cls_id,
                    "class_name": names.get(cls_id, str(cls_id)),
                }
            )
        return dets


class YOLOv11PoseAdapter(_UltralyticsAdapterBase):
    """Dedicated YOLOv11 pose adapter with keypoint output."""

    def detect(self, image: np.ndarray, conf_threshold: float = 0.25) -> List[Dict[str, Union[float, List[float]]]]:
        height, width = image.shape[:2]
        results = self._predict(image, conf_threshold)
        dets = []
        if not results:
            return dets

        result = results[0]
        boxes = result.boxes
        names = result.names if hasattr(result, "names") else {}
        kpts_xy = None
        if getattr(result, "keypoints", None) is not None and result.keypoints.xy is not None:
            kpts_xy = result.keypoints.xy.cpu().numpy()

        if boxes is None:
            return dets

        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        clss = boxes.cls.cpu().numpy()

        for i in range(len(xyxy)):
            x1, y1, x2, y2 = xyxy[i]
            x1n, y1n, x2n, y2n = x1 / width, y1 / height, x2 / width, y2 / height
            cls_id = int(clss[i])
            det = {
                "bbox": [x1n, y1n, x2n, y2n],
                "center": [(x1n + x2n) / 2, (y1n + y2n) / 2],
                "confidence": float(confs[i]),
                "class_id": cls_id,
                "class_name": names.get(cls_id, str(cls_id)),
            }
            if kpts_xy is not None and i < len(kpts_xy):
                kp_norm = []
                for px, py in kpts_xy[i]:
                    kp_norm.append([float(px) / width, float(py) / height])
                det["keypoints"] = kp_norm
            dets.append(det)
        return dets


_ADAPTERS = {
    "yolov7_bbox_repo": YOLOv7BBoxAdapter,
    "yolov11_bbox_repo": YOLOv11BBoxAdapter,
    "yolov7_bbox": YOLOv7BBoxUltralyticsAdapter,
    "yolov11_pose": YOLOv11PoseAdapter,
}


def create_detector(adapter_name: str, model_path: str, device: str = "cpu", imgsz: int = 640, yolo_repo_path: str = ""):
    if adapter_name not in _ADAPTERS:
        supported = ", ".join(sorted(_ADAPTERS.keys()))
        raise ValueError(f"Unknown detector adapter '{adapter_name}'. Supported adapters: {supported}")
    adapter_cls = _ADAPTERS[adapter_name]
    if issubclass(adapter_cls, _YOLORepoDetectorBase):
        if not yolo_repo_path:
            raise ValueError(f"adapter '{adapter_name}' requires yolo_repo_path")
        return adapter_cls(model_path=model_path, yolo_repo_path=yolo_repo_path)
    return adapter_cls(model_path=model_path, device=device, imgsz=imgsz)