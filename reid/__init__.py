"""Standalone turtle re-identification using MiewID embeddings."""

from reid.gallery import TurtleGallery
from reid.model import MiewIdEmbedder

__all__ = ["MiewIdEmbedder", "TurtleGallery"]
