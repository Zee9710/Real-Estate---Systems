"""
FastAPI application with background poller.

Endpoints:
  GET  /health
  POST /process          — process all pending incoming rows
  POST /process?case_id= — process a specific case
  POST /reindex          — rebuild Chroma from historical_cases and recalibrate
  GET  /calibration      — current novelty threshold + stats
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from fastapi import FastAPI, Query

from .db_client import DBClient
from .embeddings import EmbeddingService
from .growth_loop import GrowthLoop, seed_collection
from .llm import QwenClient
from .novelty import NoveltyDetector
from .recommender import Recommender
from .vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

db = DBClient(cfg["db"]["path"])

embedding_service = EmbeddingService(
    model_name=cfg["embeddings"]["model"],
    base_url=cfg["embeddings"]["base_url"],
)

vector_store = VectorStore(
    persist_directory=cfg["chroma"]["persist_directory"],
    collection_prefix=cfg["chroma"]["collection_prefix"],
)

novelty_detector = NoveltyDetector(
    vector_store=vector_store,
    embedding_service=embedding_service,
    k=cfg["novelty"]["k_neighbours"],
    threshold_percentile=cfg["novelty"]["threshold_percentile"],
)

qwen = QwenClient(
    base_url=cfg["ollama"]["base_url"],
    model=cfg["ollama"]["model"],
    timeout=cfg["ollama"]["timeout_seconds"],
)

prompt_template = Path("prompts/recommendation.txt").read_text(encoding="utf-8")

recommender = Recommender(
    db=db,
    embedding_service=embedding_service,
    vector_store=vector_store,
    novelty_detector=novelty_detector,
    qwen=qwen,
    prompt_template=prompt_template,
    max_registration_age_years=cfg["rules"]["max_registration_age_years"],
)

growth_loop = GrowthLoop(
    db=db,
    vector_store=vector_store,
    embedding_service=embedding_service,
    novelty_detector=novelty_detector,
)

_calibration_cache: Dict[str, Any] = {}
_poller_running = False


async def _poll_loop():
    global _poller_running
    interval = cfg["poller"]["interval_seconds"]
    logger.info("Poller started (interval=%ds)", interval)
    while _poller_running:
        try:
            _process_pending()
            _run_growth_loop()
        except Exception as e:
            logger.error("Poller error: %s", e, exc_info=True)
        await asyncio.sleep(interval)


def _process_pending():
    rows = db.get_pending_rows()
    if rows:
        logger.info("Poller found %d pending rows", len(rows))
    for row in rows:
        recommender.process_row(row)


def _run_growth_loop():
    count = growth_loop.run_batch()
    if count:
        logger.info("Growth loop appended %d validated case(s)", count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poller_running
    _poller_running = True
    task = asyncio.create_task(_poll_loop())
    yield
    _poller_running = False
    task.cancel()


app = FastAPI(title="Document Acceptance RAG", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "chroma_count": vector_store.count(),
        "active_version": vector_store.active_version(),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/process")
def process(case_id: Optional[str] = Query(default=None)):
    if case_id:
        all_rows = db.read_incoming()
        matched = [r for r in all_rows if r["case_id"] == case_id]
        if not matched:
            return {"error": f"case_id {case_id!r} not found"}
        results = [recommender.process_row(matched[0])]
    else:
        pending = db.get_pending_rows()
        results = []
        for r in pending:
            try:
                results.append(recommender.process_row(r))
            except Exception as e:
                results.append({"error": str(e), "case_id": r.get("case_id")})
    return {"processed": len(results), "results": results}


@app.post("/reindex")
def reindex():
    all_historical = db.read_historical()
    version = seed_collection(all_historical, vector_store, embedding_service)
    calibration = novelty_detector.calibrate(all_historical)
    _calibration_cache.update({
        "version": version,
        "threshold": calibration.threshold,
        "percentile": calibration.percentile,
        "n_cases": calibration.n_cases,
        "p50": calibration.p50_self_distance,
        "p95": calibration.p95_self_distance,
        "reindexed_at": datetime.utcnow().isoformat(),
    })
    return _calibration_cache


@app.get("/calibration")
def calibration():
    if not _calibration_cache:
        return {
            "threshold": novelty_detector.threshold,
            "percentile": novelty_detector.percentile,
            "note": "No reindex run yet in this session. Run POST /reindex to calibrate.",
        }
    return _calibration_cache
