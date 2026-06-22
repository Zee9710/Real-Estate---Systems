"""
Ollama-based embedding service.

Uses nomic-embed-text via Ollama — no HuggingFace download needed.
Embeds case ATTRIBUTES ONLY — never decision or reason_code.
"""
from __future__ import annotations

from typing import List

import httpx

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
    parts = []
    for field in ATTRIBUTE_FIELDS:
        val = case_dict.get(field, "")
        if val is not None and str(val).strip():
            parts.append(f"{field}: {val}")
    return " | ".join(parts)


class EmbeddingService:
    def __init__(self, model_name: str = "nomic-embed-text", base_url: str = "http://localhost:11434", **kwargs):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            response = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model_name, "prompt": text},
                timeout=30,
            )
            response.raise_for_status()
            embeddings.append(response.json()["embedding"])
        return embeddings

    def embed_case(self, case_dict: dict) -> List[float]:
        text = case_to_text(case_dict)
        return self.embed([text])[0]
