"""
Seed ChromaDB from data/historical_cases.csv.

Run this once after generating synthetic data, and again after each
batch of validated cases are appended to Historical_Cases.

Usage:
  python scripts/seed_chroma.py [--csv data/historical_cases.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.embeddings import EmbeddingService
from src.growth_loop import seed_collection
from src.novelty import NoveltyDetector
from src.vector_store import VectorStore


def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="data/historical_cases.csv")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    rows = load_csv(args.csv)
    validated = [r for r in rows if r.get("source") == "validated"]
    print(f"Loaded {len(validated)} validated cases from {args.csv}")

    embedding_service = EmbeddingService(
        model_name=cfg["embeddings"]["model"],
        base_url=cfg["embeddings"]["base_url"],
    )
    vector_store = VectorStore(
        persist_directory=cfg["chroma"]["persist_directory"],
        collection_prefix=cfg["chroma"]["collection_prefix"],
    )

    version = seed_collection(validated, vector_store, embedding_service)
    print(f"Indexed into collection: {version}")

    novelty_detector = NoveltyDetector(
        vector_store=vector_store,
        embedding_service=embedding_service,
        k=cfg["novelty"]["k_neighbours"],
        threshold_percentile=cfg["novelty"]["threshold_percentile"],
    )
    calibration = novelty_detector.calibrate(validated)
    print(
        f"Calibrated threshold={calibration.threshold:.4f} "
        f"(p{calibration.percentile}, n={calibration.n_cases}, "
        f"p50={calibration.p50_self_distance:.4f}, p95={calibration.p95_self_distance:.4f})"
    )


if __name__ == "__main__":
    main()
