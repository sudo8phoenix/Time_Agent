"""Build and persist a local-only index for a pinned schedule snapshot."""
from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ActivityEmbedding
from .index import cache_key, compose_description


def composed_text_hash(activity: Any) -> str:
    return hashlib.sha256(compose_description(activity).encode("utf-8")).hexdigest()


def _activity_id(activity: Any) -> str:
    return str(activity.get("id", "") if isinstance(activity, Mapping) else activity.id)


def _valid_vector(value: Sequence[float]) -> list[float]:
    vector = [float(component) for component in value]
    if not vector or not all(math.isfinite(component) for component in vector):
        raise ValueError("embedding vector must contain finite values")
    return vector


def ensure_activity_embeddings(
    db: Session,
    activities: Iterable[Any],
    embed: Callable[[str], Sequence[float]],
    model_revision: str,
) -> dict[str, list[float]]:
    """Reuse matching vectors and persist only stale local embeddings.

    The caller owns the transaction.  No network operation is performed here;
    callers should pass only a local embedder.
    """
    rows = list(activities)
    ids = [getattr(row, "id", None) for row in rows]
    existing = {
        str(row.activity_id): row
        for row in db.scalars(
            select(ActivityEmbedding).where(
                ActivityEmbedding.activity_id.in_(ids),
                ActivityEmbedding.model_revision == model_revision,
            )
        )
    } if ids else {}
    vectors: dict[str, list[float]] = {}
    for activity in rows:
        activity_id = _activity_id(activity)
        text_hash = composed_text_hash(activity)
        stored = existing.get(activity_id)
        if stored is not None and stored.composed_text_hash == text_hash:
            vectors[activity_id] = _valid_vector(stored.vector)
            continue
        vector = _valid_vector(embed(compose_description(activity)))
        if stored is None:
            db.add(ActivityEmbedding(
                activity_id=getattr(activity, "id"), model_revision=model_revision,
                composed_text_hash=text_hash, vector=vector,
            ))
        else:
            stored.composed_text_hash = text_hash
            stored.vector = vector
        vectors[activity_id] = vector
    return vectors

class LocalEmbeddingModel:
    """Lazy local sentence-transformer loader; it never downloads model weights."""
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("local embeddings require the sentence-transformers package") from exc
        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)
        except TypeError:
            # Older releases don't expose local_files_only; avoid them because
            # their constructor may fetch weights from the network.
            raise RuntimeError("installed sentence-transformers must support local_files_only")
        except Exception as exc:
            raise RuntimeError(f"local embedding model is unavailable: {model_name}") from exc
        self.model_name = model_name
        # This is deliberately explicit rather than a mutable "latest" label.
        # Operators can pass an immutable Hugging Face revision in model_name.
        self.model_revision = model_name

    def __call__(self, text):
        return self.model.encode(text, normalize_embeddings=True).tolist()

def rebuild_index(activities, schedule_version_id, *, model_version="none", text_version="text-v1"):
    """Build deterministic local index metadata without network/model downloads."""
    return {"schedule_version_id": str(schedule_version_id), "cache_key": cache_key(schedule_version_id, activities, model_version, text_version), "model_version": model_version, "text_version": text_version, "descriptions": [{"activity_id": str(getattr(a, "id", a.get("id", "")) if isinstance(a, dict) else getattr(a, "id", "")), "text": compose_description(a)} for a in activities]}
