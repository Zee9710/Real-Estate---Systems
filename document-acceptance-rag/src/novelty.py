"""
Distance-based novelty detector.

Calibration: at each reindex, compute the distribution of self-distances
over the validated historical set, then set the threshold at the configured
percentile. This makes the threshold adaptive — it self-tightens as the
dataset densifies.

Novelty check: a new case is flagged if its mean distance to its k nearest
historical neighbours exceeds the calibrated threshold.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class CalibrationResult:
    threshold: float
    percentile: int
    n_cases: int
    mean_self_distance: float
    p50_self_distance: float
    p95_self_distance: float


@dataclass
class NoveltyResult:
    is_novel: bool
    nn_distance: float
    retrieved_ids: List[str]
    threshold: float


class NoveltyDetector:
    _CALIBRATION_CACHE = "chroma_db/calibration.json"

    def __init__(
        self,
        vector_store,
        embedding_service,
        k: int = 5,
        threshold_percentile: int = 95,
    ):
        self.store = vector_store
        self.embeddings = embedding_service
        self.k = k
        self.percentile = threshold_percentile
        self._threshold: Optional[float] = self._load_cached_threshold()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate(self, historical_cases: List[dict]) -> CalibrationResult:
        """
        Compute self-distance distribution over validated historical cases and
        set the threshold at the configured percentile.

        Call this after every reindex.
        """
        if len(historical_cases) < self.k + 1:
            # Not enough data; use a permissive default
            self._threshold = 1.0
            return CalibrationResult(
                threshold=1.0,
                percentile=self.percentile,
                n_cases=len(historical_cases),
                mean_self_distance=0.0,
                p50_self_distance=0.0,
                p95_self_distance=0.0,
            )

        self_distances = []
        for case in historical_cases:
            emb = self.embeddings.embed_case(case)
            # Query k+1 because the case itself may be in the index
            ids, dists, _ = self.store.query(emb, n_results=self.k + 1)
            case_id = case.get("case_id", "")
            # Filter out self-match
            filtered = [d for i, d in zip(ids, dists) if i != case_id]
            if filtered:
                self_distances.append(np.mean(filtered[: self.k]))

        arr = np.array(self_distances)
        threshold = float(np.percentile(arr, self.percentile))
        self._threshold = threshold
        self._save_cached_threshold(threshold)

        return CalibrationResult(
            threshold=threshold,
            percentile=self.percentile,
            n_cases=len(historical_cases),
            mean_self_distance=float(arr.mean()),
            p50_self_distance=float(np.percentile(arr, 50)),
            p95_self_distance=float(np.percentile(arr, 95)),
        )

    def _save_cached_threshold(self, threshold: float):
        os.makedirs(os.path.dirname(self._CALIBRATION_CACHE), exist_ok=True)
        with open(self._CALIBRATION_CACHE, "w") as f:
            json.dump({"threshold": threshold, "percentile": self.percentile}, f)

    def _load_cached_threshold(self) -> Optional[float]:
        if os.path.exists(self._CALIBRATION_CACHE):
            with open(self._CALIBRATION_CACHE) as f:
                data = json.load(f)
            return data.get("threshold")
        return None

    @property
    def threshold(self) -> float:
        return self._threshold if self._threshold is not None else 1.0

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def check(self, case_dict: dict) -> NoveltyResult:
        emb = self.embeddings.embed_case(case_dict)
        ids, dists, _ = self.store.query(emb, n_results=self.k)
        if not dists:
            # Empty index — everything is novel
            return NoveltyResult(
                is_novel=True,
                nn_distance=1.0,
                retrieved_ids=[],
                threshold=self.threshold,
            )
        mean_dist = float(np.mean(dists))
        return NoveltyResult(
            is_novel=mean_dist > self.threshold,
            nn_distance=mean_dist,
            retrieved_ids=ids,
            threshold=self.threshold,
        )
