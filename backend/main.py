from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import documents, indexes, keywords, ocr, sync
from routers.common import build_services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc-indexer-backend")

app = FastAPI(title="Doc Indexer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(indexes.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(keywords.router, prefix="/api")
app.include_router(ocr.router, prefix="/api")
app.include_router(sync.router, prefix="/api")


@app.get("/health")
def health_check() -> dict:
    """Simple health check endpoint for Railway and monitoring."""
    return {"status": "healthy", "service": "doc-indexer-api"}


@app.on_event("startup")
def startup_check() -> None:
    try:
        manager = build_services()["manager"]
        healthy = manager.health_check()
        if healthy:
            logger.info("Elasticsearch connection healthy.")
        else:
            logger.warning("Elasticsearch unreachable at startup.")
    except Exception as exc:
        logger.warning(f"Elasticsearch check failed: {exc}. OCR endpoints will work without ES.")
