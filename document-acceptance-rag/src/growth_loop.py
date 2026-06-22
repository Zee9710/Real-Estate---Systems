"""
Human-gated growth loop.

The ONLY path for a case to enter the historical dataset is human validation.
No model has write access to the historical set.

Flow:
1. Operator sets validated_by on a needs_review=TRUE row in Incoming_Cases.
2. growth_loop.append_validated() is called (by the poller or /process endpoint).
3. Case is appended to Historical_Cases with source=validated, added_at, index_version.
4. seed_chroma() reindexes the new collection version.
5. NoveltyDetector.calibrate() recalibrates the threshold over the updated set.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from .embeddings import EmbeddingService
from .novelty import NoveltyDetector
from .sheets_client import SheetsClient
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
        sheets: SheetsClient,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        novelty_detector: NoveltyDetector,
        historical_tab: str,
        incoming_tab: str,
    ):
        self.sheets = sheets
        self.store = vector_store
        self.embeddings = embedding_service
        self.novelty = novelty_detector
        self.historical_tab = historical_tab
        self.incoming_tab = incoming_tab

    def get_validated_rows(self) -> List[Dict[str, Any]]:
        """Return Incoming_Cases rows with validated_by set and status=done."""
        rows = self.sheets.read_incoming(self.incoming_tab)
        return [
            r for r in rows
            if r.get("validated_by", "").strip()
            and r.get("needs_review", "").upper() == "TRUE"
            and r.get("status", "") == "done"
        ]

    def append_validated(self, validated_row: Dict[str, Any]) -> str:
        """
        Append a single validated case to Historical_Cases, reindex, and recalibrate.
        Returns the new index_version.
        """
        # Compute new version before appending
        new_version = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

        historical_row = {
            **validated_row,
            "source": "validated",
            "added_at": datetime.utcnow().date().isoformat(),
            "index_version": new_version,
        }
        self.sheets.append_historical(self.historical_tab, historical_row)
        logger.info("Appended %s to historical set (version %s)", validated_row.get("case_id"), new_version)

        # Reindex
        all_historical = self.sheets.read_historical(self.historical_tab)
        validated_only = [r for r in all_historical if r.get("source") == "validated"]
        version = seed_collection(validated_only, self.store, self.embeddings)

        # Recalibrate
        calibration = self.novelty.calibrate(validated_only)
        logger.info(
            "Recalibrated threshold=%.4f (p%d, n=%d)",
            calibration.threshold,
            calibration.percentile,
            calibration.n_cases,
        )
        return version

    def run_batch(self) -> int:
        """Process all pending validated rows. Returns count appended."""
        rows = self.get_validated_rows()
        count = 0
        for row in rows:
            try:
                self.append_validated(row)
                count += 1
            except Exception as e:
                logger.error("Failed to append %s: %s", row.get("case_id"), e, exc_info=True)
        return count
