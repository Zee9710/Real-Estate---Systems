"""
bge-m3 multilingual embedding service.

Embeds case ATTRIBUTES ONLY — never decision or reason_code.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

ATTRIBUTE_FIELDS = [
    "document_type",
    "owner_name",
    "property_type",
    "area_sqm",
    "address",
    "city",
    "notarized",
    "owner_signature",
    "liens_present",
]


def case_to_text(case_dict: dict) -> str:
    """Concatenate attribute fields into a single string for embedding."""
    parts = []
    for field in ATTRIBUTE_FIELDS:
        val = case_dict.get(field, "")
        if val is not None and str(val).strip():
            parts.append(f"{field}: {val}")
    return " | ".join(parts)


@lru_cache(maxsize=1)
def _load_model(model_name: str, device: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, device=device)


class EmbeddingService:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu"):
        self.model_name = model_name
        self.device = device

    @property
    def model(self) -> SentenceTransformer:
        return _load_model(self.model_name, self.device)

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

    def embed_case(self, case_dict: dict) -> List[float]:
        text = case_to_text(case_dict)
        return self.embed([text])[0]
