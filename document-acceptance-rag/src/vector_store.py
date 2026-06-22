"""
ChromaDB wrapper with versioned collections.

Each reindex creates a new timestamped collection. The active collection pointer
is stored in a metadata collection so rollback is trivial.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings


class VectorStore:
    def __init__(self, persist_directory: str, collection_prefix: str = "historical_cases"):
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.prefix = collection_prefix
        self._meta_collection_name = f"{collection_prefix}__meta"

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def _meta(self):
        return self.client.get_or_create_collection(self._meta_collection_name)

    def active_version(self) -> Optional[str]:
        meta = self._meta()
        results = meta.get(ids=["active_version"])
        if results["documents"]:
            return results["documents"][0]
        return None

    def _set_active_version(self, version: str):
        meta = self._meta()
        meta.upsert(ids=["active_version"], documents=[version])

    def new_version_name(self) -> str:
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        return f"{self.prefix}__{ts}"

    def get_or_create_active_collection(self):
        version = self.active_version()
        if version is None:
            version = self.new_version_name()
            self._set_active_version(version)
        return self.client.get_or_create_collection(
            name=version,
            metadata={"hnsw:space": "cosine"},
        )

    def create_new_version(self) -> str:
        version = self.new_version_name()
        self.client.get_or_create_collection(
            name=version,
            metadata={"hnsw:space": "cosine"},
        )
        self._set_active_version(version)
        return version

    def rollback_to(self, version: str):
        existing = [c.name for c in self.client.list_collections()]
        if version not in existing:
            raise ValueError(f"Version {version!r} not found in ChromaDB")
        self._set_active_version(version)

    def list_versions(self) -> List[str]:
        return [
            c.name for c in self.client.list_collections()
            if c.name.startswith(self.prefix + "__") and c.name != self._meta_collection_name
        ]

    # ------------------------------------------------------------------
    # CRUD on active collection
    # ------------------------------------------------------------------

    def upsert(self, ids: List[str], embeddings: List[List[float]], metadatas: List[Dict]):
        col = self.get_or_create_active_collection()
        col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)

    def query(
        self,
        query_embedding: List[float],
        n_results: int = 5,
    ) -> Tuple[List[str], List[float], List[Dict]]:
        """Returns (ids, distances, metadatas) for the n nearest neighbours."""
        col = self.get_or_create_active_collection()
        count = col.count()
        if count == 0:
            return [], [], []
        n = min(n_results, count)
        results = col.query(
            query_embeddings=[query_embedding],
            n_results=n,
            include=["distances", "metadatas"],
        )
        ids = results["ids"][0]
        distances = results["distances"][0]
        metadatas = results["metadatas"][0]
        return ids, distances, metadatas

    def count(self) -> int:
        return self.get_or_create_active_collection().count()
