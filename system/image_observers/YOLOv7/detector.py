import torch
import cv2
import numpy as np
from typing import Tuple, List, Dict, Union
from pathlib import Path
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
def yolov7_context():
    """Context manager to safely use yolov7 code with proper imports."""
    # Store original state
    original_cwd = os.getcwd()
    original_path = sys.path.copy()

    try:
        # Add yolov7 to the path
        yolov7_path = os.path.expanduser("~/dev/yolov7")
        sys.path.insert(0, yolov7_path)

        # Change working directory to yolov7
        os.chdir(yolov7_path)

        yield
    finally:
        # Restore original state
        os.chdir(original_cwd)
        sys.path = original_path


class YOLOv7Detector:
    def __init__(self, model_path: str):
        self.model_path = model_path

    def load(self):
        # Load model
        with yolov7_context():
            from models.experimental import attempt_load
            from utils.general import check_img_size
            from utils.torch_utils import select_device
            self.model = attempt_load(self.model_path)

        if not self.model:
            raise RuntimeError('No YOLOv7 model was loaded.')

        # Modify first layer for grayscale input if needed
        if self.model.model[0].conv.in_channels == 3:
            print("Converting model from RGB to grayscale input")
            self._convert_to_grayscale()

        self.stride = int(self.model.stride.max())
        self.img_size = check_img_size(640, s=self.stride)  # Ensure image size is multiple of stride

        # Get model info
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
        with yolov7_context():
            from utils.general import non_max_suppression
            pred = non_max_suppression(pred, conf_thres=conf_threshold)

        # Process detections
        detections = []
        if len(pred[0]):  # If there are detections
            # Rescale boxes from img_size to original image size
            with yolov7_context():
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