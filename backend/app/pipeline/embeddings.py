"""
Semantic embedding generation for scenario similarity search.

Uses fastembed (ONNX-based, no PyTorch) with BAAI/bge-small-en-v1.5.
Model is 384 dimensions — matches the vector(384) pgvector column.
First call downloads the model (~24 MB) and caches it; subsequent calls
are fast (< 20ms on CPU).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from fastembed import TextEmbedding

logger = get_logger(__name__)

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DIMENSIONS = 384
_model: "TextEmbedding | None" = None


def _get_model() -> "TextEmbedding":
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        logger.info("Loading fastembed model", extra={"model": _MODEL_NAME})
        _model = TextEmbedding(model_name=_MODEL_NAME)
    return _model


def generate_embedding(text: str) -> list[float]:
    """Return a 384-dim embedding vector for the given text."""
    model = _get_model()
    vectors = list(model.embed([text]))
    return vectors[0].tolist()


def scenario_text(
    title: str,
    initial_access_vector: str | None = None,
    mitre_techniques: list[str] | None = None,
    nist_controls: list[str] | None = None,
    industry_vertical: str | None = None,
    regulatory_frameworks: list[str] | None = None,
) -> str:
    """
    Build a rich text representation of a scenario for embedding.
    Combines the most semantically meaningful fields so that queries like
    'ransomware pipeline shutdown' or 'healthcare credential theft' surface
    the right scenarios via cosine similarity.
    """
    parts = [title]
    if initial_access_vector:
        parts.append(f"Initial access: {initial_access_vector}")
    if industry_vertical:
        parts.append(f"Industry: {industry_vertical}")
    if mitre_techniques:
        parts.append("MITRE techniques: " + " ".join(mitre_techniques))
    if nist_controls:
        parts.append("NIST controls: " + " ".join(nist_controls))
    if regulatory_frameworks:
        parts.append("Frameworks: " + " ".join(regulatory_frameworks))
    return ". ".join(parts)
