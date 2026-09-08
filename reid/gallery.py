"""Persistent turtle Re-ID gallery backed by JSON + NPZ."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from reid.model import MiewIdEmbedder

DEFAULT_GALLERY_DIR = Path("/data/reptilearn/reid")
DEFAULT_THRESHOLD = 0.75
EMBEDDING_DIM = 2152


@dataclass
class IdentifyHit:
    turtle_id: str
    similarity: float
    image_path: str


@dataclass
class IdentifyResult:
    matched_id: str | None
    best: IdentifyHit | None
    hits: list[IdentifyHit]


class TurtleGallery:
    """Multi-chip gallery: one embedding row per enrolled image."""

    def __init__(
        self,
        gallery_dir: str | Path = DEFAULT_GALLERY_DIR,
        embedder: MiewIdEmbedder | None = None,
    ):
        self.gallery_dir = Path(gallery_dir)
        self.images_dir = self.gallery_dir / "images"
        self.meta_path = self.gallery_dir / "gallery.json"
        self.embeddings_path = self.gallery_dir / "embeddings.npz"
        self._embedder = embedder
        self.meta: dict[str, Any] = {"turtles": {}}
        self.embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        self.turtle_ids: list[str] = []
        self.image_rels: list[str] = []
        self._ensure_dirs()
        self._load()

    @property
    def embedder(self) -> MiewIdEmbedder:
        if self._embedder is None:
            self._embedder = MiewIdEmbedder()
        return self._embedder

    def _ensure_dirs(self) -> None:
        self.gallery_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        if self.meta_path.exists():
            with open(self.meta_path, encoding="utf-8") as f:
                self.meta = json.load(f)
            if "turtles" not in self.meta:
                self.meta["turtles"] = {}

        if self.embeddings_path.exists():
            data = np.load(self.embeddings_path, allow_pickle=False)
            self.embeddings = np.asarray(data["embeddings"], dtype=np.float32)
            self.turtle_ids = [str(x) for x in data["turtle_ids"].tolist()]
            self.image_rels = [str(x) for x in data["image_rels"].tolist()]
            if self.embeddings.ndim != 2 or self.embeddings.shape[1] != EMBEDDING_DIM:
                raise ValueError(
                    f"Invalid embeddings shape {self.embeddings.shape}; "
                    f"expected (N, {EMBEDDING_DIM})"
                )
            n = self.embeddings.shape[0]
            if len(self.turtle_ids) != n or len(self.image_rels) != n:
                raise ValueError("embeddings.npz arrays have mismatched lengths")
        else:
            self.embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
            self.turtle_ids = []
            self.image_rels = []

    def _atomic_save(self) -> None:
        # Use names that already end in .json / .npz so tools don't append suffixes.
        tmp_meta = self.gallery_dir / "gallery.tmp.json"
        tmp_npz = self.gallery_dir / "embeddings.tmp.npz"
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2, sort_keys=True)
            f.write("\n")
        np.savez_compressed(
            tmp_npz,
            embeddings=self.embeddings,
            turtle_ids=np.array(self.turtle_ids, dtype=str),
            image_rels=np.array(self.image_rels, dtype=str),
        )
        tmp_meta.replace(self.meta_path)
        tmp_npz.replace(self.embeddings_path)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _copy_image(self, turtle_id: str, src: Path) -> str:
        dest_dir = self.images_dir / turtle_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        dest = dest_dir / f"{stamp}{src.suffix.lower() or '.jpg'}"
        shutil.copy2(src, dest)
        return str(dest.relative_to(self.gallery_dir))

    def enroll(
        self,
        turtle_id: str,
        image_paths: list[str | Path],
        *,
        add_images: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Enroll a turtle or append more chips to an existing ID."""
        turtle_id = turtle_id.strip()
        if not turtle_id:
            raise ValueError("turtle_id must be non-empty")
        if not image_paths:
            raise ValueError("At least one image is required")

        exists = turtle_id in self.meta["turtles"]
        if exists and not add_images and not force:
            raise ValueError(
                f"Turtle '{turtle_id}' already enrolled. "
                "Use add_images=True to append chips, or force=True to replace."
            )

        paths = [Path(p).expanduser().resolve() for p in image_paths]
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Image not found: {path}")

        if exists and force and not add_images:
            self.remove(turtle_id, save=False)

        embs = self.embedder.embed_many(paths)
        new_rels: list[str] = []
        for path in paths:
            new_rels.append(self._copy_image(turtle_id, path))

        self.embeddings = np.vstack([self.embeddings, embs]) if len(self.turtle_ids) else embs
        self.turtle_ids.extend([turtle_id] * len(paths))
        self.image_rels.extend(new_rels)

        turtle = self.meta["turtles"].setdefault(
            turtle_id,
            {
                "created_at": self._now_iso(),
                "images": [],
                "used": False,
                "used_notes": [],
            },
        )
        turtle.setdefault("images", [])
        turtle["images"].extend(new_rels)
        turtle["updated_at"] = self._now_iso()
        self._atomic_save()
        return turtle

    def identify(
        self,
        image_path: str | Path,
        *,
        top_k: int = 5,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> IdentifyResult:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        if len(self.turtle_ids) == 0:
            return IdentifyResult(matched_id=None, best=None, hits=[])

        query = self.embedder.embed(path)
        sims = self.embeddings @ query  # cosine: both L2-normalized
        k = min(top_k, len(sims))
        # argpartition then sort the top-k
        idx = np.argpartition(-sims, kth=k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]

        hits = [
            IdentifyHit(
                turtle_id=self.turtle_ids[i],
                similarity=float(sims[i]),
                image_path=self.image_rels[i],
            )
            for i in idx
        ]
        best = hits[0] if hits else None
        matched_id = (
            best.turtle_id if best is not None and best.similarity >= threshold else None
        )
        return IdentifyResult(matched_id=matched_id, best=best, hits=hits)

    def list_turtles(self) -> list[dict[str, Any]]:
        rows = []
        for turtle_id, info in sorted(self.meta["turtles"].items()):
            chip_count = sum(1 for t in self.turtle_ids if t == turtle_id)
            rows.append(
                {
                    "id": turtle_id,
                    "chip_count": chip_count,
                    "image_count": len(info.get("images", [])),
                    "used": bool(info.get("used", False)),
                    "used_notes": list(info.get("used_notes", [])),
                    "created_at": info.get("created_at"),
                    "updated_at": info.get("updated_at"),
                }
            )
        return rows

    def mark_used(self, turtle_id: str, note: str = "") -> dict[str, Any]:
        if turtle_id not in self.meta["turtles"]:
            raise KeyError(f"Unknown turtle_id: {turtle_id}")
        turtle = self.meta["turtles"][turtle_id]
        turtle["used"] = True
        notes = turtle.setdefault("used_notes", [])
        entry = {"at": self._now_iso(), "note": note}
        notes.append(entry)
        turtle["updated_at"] = self._now_iso()
        self._atomic_save()
        return turtle

    def remove(self, turtle_id: str, *, save: bool = True) -> None:
        if turtle_id not in self.meta["turtles"] and turtle_id not in self.turtle_ids:
            raise KeyError(f"Unknown turtle_id: {turtle_id}")

        keep = [i for i, tid in enumerate(self.turtle_ids) if tid != turtle_id]
        if keep:
            self.embeddings = self.embeddings[keep]
            self.turtle_ids = [self.turtle_ids[i] for i in keep]
            self.image_rels = [self.image_rels[i] for i in keep]
        else:
            self.embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
            self.turtle_ids = []
            self.image_rels = []

        self.meta["turtles"].pop(turtle_id, None)
        turtle_img_dir = self.images_dir / turtle_id
        if turtle_img_dir.exists():
            shutil.rmtree(turtle_img_dir)
        if save:
            self._atomic_save()
