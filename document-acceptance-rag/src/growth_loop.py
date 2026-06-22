"""
Human-gated growth loop.

The ONLY path for a case to enter the historical dataset is human validation.
No model has write access to the historical set.

Flow:
1. Reviewer sets validated_by in the Streamlit UI.
2. growth_loop.run_batch() detects the row and appends it to historical_cases.
3. ChromaDB is reindexed with the new version.
4. NoveltyDetector recalibrates over the updated validated set.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from .db_client import DBClient
from .embeddings import EmbeddingService
from .novelty import NoveltyDetector
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


def seed_collection(
    historical_rows: List[Dict[str, Any]],
    vector_store: VectorStore,
    embedding_service: EmbeddingService,
) -> str:
    """Create a new versioned Chroma collection and index all historical rows."""
    version = vector_store.create_new_version()
    logger.info("Seeding new collection version: %s (%d cases)", version, len(historical_rows))

    batch_ids, batch_embeddings, batch_metadatas = [], [], []

    for row in historical_rows:
        case_id = row.get("case_id", "")
        if not case_id:
            continue
        emb = embedding_service.embed_case(row)
        metadata = {
            "decision": row.get("decision", ""),
            "reason_code": row.get("reason_code", ""),
            "source": row.get("source", "validated"),
        }
        batch_ids.append(case_id)
        batch_embeddings.append(emb)
        batch_metadatas.append(metadata)

        if len(batch_ids) >= 50:
            vector_store.upsert(batch_ids, batch_embeddings, batch_metadatas)
            batch_ids, batch_embeddings, batch_metadatas = [], [], []

    if batch_ids:
        vector_store.upsert(batch_ids, batch_embeddings, batch_metadatas)

    logger.info("Seeded %d cases into %s", len(historical_rows), version)
    return version


class GrowthLoop:
    def __init__(
        self,
        db: DBClient,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        novelty_detector: NoveltyDetector,
    ):
        self.db = db
        self.store = vector_store
        self.embeddings = embedding_service
        self.novelty = novelty_detector

    def append_validated(self, validated_row: Dict[str, Any]) -> str:
        """
        Append a single validated case to historical_cases, reindex, recalibrate.
        Returns the new index_version.
        """
        new_version = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

        historical_row = {
            "case_id": validated_row["case_id"],
            "document_type": validated_row.get("document_type", ""),
            "owner_name": validated_row.get("owner_name", ""),
            "owner_id": validated_row.get("owner_id", ""),
            "property_id": validated_row.get("property_id", ""),
            "property_type": validated_row.get("property_type", ""),
            "area_sqm": validated_row.get("area_sqm"),
            "address": validated_row.get("address", ""),
            "city": validated_row.get("city", ""),
            "notarized": validated_row.get("notarized", 0),
            "owner_signature": validated_row.get("owner_signature", 0),
            "liens_present": validated_row.get("liens_present", 0),
            "registration_date": validated_row.get("registration_date", ""),
            "decision": validated_row.get("decision", ""),
            "reason_code": validated_row.get("reason_code", ""),
            "recommendation_en": validated_row.get("recommendation_en", ""),
            "recommendation_ar": validated_row.get("recommendation_ar", ""),
            "source": "validated",
            "added_at": datetime.utcnow().date().isoformat(),
            "index_version": new_version,
        }
        self.db.append_historical(historical_row)
        self.db.mark_appended(validated_row["case_id"])
        logger.info("Appended %s to historical set (version %s)", validated_row.get("case_id"), new_version)

        all_historical = self.db.read_historical()
        version = seed_collection(all_historical, self.store, self.embeddings)

        calibration = self.novelty.calibrate(all_historical)
        logger.info(
            "Recalibrated threshold=%.4f (p%d, n=%d)",
            calibration.threshold,
            calibration.percentile,
            calibration.n_cases,
        )
        return version

    def run_batch(self) -> int:
        """Process all pending validated rows. Returns count appended."""
        rows = self.db.get_validated_rows()
        count = 0
        for row in rows:
            try:
                self.append_validated(row)
                count += 1
            except Exception as e:
                logger.error("Failed to append %s: %s", row.get("case_id"), e, exc_info=True)
        return count
