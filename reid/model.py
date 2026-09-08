"""MiewID feature extractor wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as transforms
from PIL import Image
from transformers import AutoModel

DEFAULT_MODEL_ID = "conservationxlabs/miewid-msv3"
IMAGE_SIZE = 440
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

ImageInput = Union[str, Path, Image.Image]


class MiewIdEmbedder:
    """Load MiewID-msv3 and extract L2-normalized 2152-d embeddings."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: str | None = None,
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)
        self.model = AutoModel.from_pretrained(
            model_id,
            trust_remote_code=True,
        )
        self.model.to(self.device)
        self.model.eval()
        self.preprocess = transforms.Compose(
            [
                transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
                transforms.ToTensor(),
                transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ]
        )

    @staticmethod
    def _load_image(image: ImageInput) -> Image.Image:
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        return Image.open(image).convert("RGB")

    @torch.inference_mode()
    def embed(self, image: ImageInput) -> np.ndarray:
        """Return a single L2-normalized embedding as float32 (2152,)."""
        pil = self._load_image(image)
        batch = self.preprocess(pil).unsqueeze(0).to(self.device)
        emb = self.model(batch)
        emb = F.normalize(emb, dim=-1)
        return emb.squeeze(0).detach().cpu().numpy().astype(np.float32)

    @torch.inference_mode()
    def embed_many(self, images: list[ImageInput]) -> np.ndarray:
        """Embed multiple images; returns (N, 2152) float32."""
        if not images:
            return np.empty((0, 2152), dtype=np.float32)
        tensors = []
        for image in images:
            pil = self._load_image(image)
            tensors.append(self.preprocess(pil))
        batch = torch.stack(tensors, dim=0).to(self.device)
        emb = self.model(batch)
        emb = F.normalize(emb, dim=-1)
        return emb.detach().cpu().numpy().astype(np.float32)
