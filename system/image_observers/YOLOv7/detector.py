import torch
import cv2
import numpy as np
from typing import Tuple, List, Dict, Union
import sys
from pathlib import Path


class YOLOv7Detector:
    def __init__(self, model_path: str, yolov7_path: str, device: str = 'cuda' if torch.cuda.is_available() else 'cpu'):
        """
        Initialize YOLOv7 detector

        Args:
            model_path: Path to the trained YOLOv7 weights
            yolov7_path: Path to the YOLOv7 repository directory
            device: Device to run inference on ('cuda' or 'cpu')
        """
        # Add YOLOv7 to path
        yolov7_path = Path(yolov7_path)
        if not yolov7_path.exists():
            raise FileNotFoundError(f"YOLOv7 path does not exist: {yolov7_path}")
        sys.path.append(str(yolov7_path))

        # Import YOLOv7 modules
        from image_observers.yolov7.models.experimental import attempt_load
        from image_observers.yolov7.utils.general import check_img_size
        from image_observers.yolov7.utils.torch_utils import select_device

        self.device = select_device(device)

        # Load model
        self.model = attempt_load(model_path)#, device=self.device)
        self.stride = int(self.model.stride.max())
        self.img_size = check_img_size(640, s=self.stride)  # Ensure image size is multiple of stride

        # Get model info
        self.names = self.model.module.names if hasattr(self.model, 'module') else self.model.names

    def detect(self, image: np.ndarray, conf_threshold: float = 0.25) -> List[Dict[str, Union[float, List[float]]]]:
        """
        Detect objects in an image

        Args:
            image: Input image in BGR format (OpenCV default)
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
        from image_observers.yolov7.utils.general import non_max_suppression, scale_coords


        # Get original image dimensions
        height, width = image.shape[:2]

        # Preprocess image
        img = letterbox(image, self.img_size, stride=self.stride, auto=True)[0]
        # img = img.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
        img = np.ascontiguousarray(img)

        img = torch.from_numpy(img).to(self.device)
        img = img.float()
        img /= 255.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Inference
        with torch.no_grad():
            pred = self.model(img)[0]

        # Apply NMS
        pred = non_max_suppression(pred, conf_threshold)

        # Process detections
        detections = []
        if len(pred[0]):  # If there are detections
            # Rescale boxes from img_size to original image size
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


def letterbox(img: np.ndarray, new_shape=(640, 640), color=(114, 114, 114), auto=True, stride=32):
    """
    Resize and pad image while meeting stride-multiple constraints.
    Returns resized and padded image.
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