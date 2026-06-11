from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / ".env.local", override=False)

from backend.routers import documents, indexes, keywords, ocr, pipeline, sync
from backend.routers.common import build_services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc-indexer-backend")

app = FastAPI(title="Doc Indexer API")

_cors_origins_env = os.getenv("CORS_ORIGINS", "").strip()
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(indexes.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(keywords.router, prefix="/api")
app.include_router(ocr.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
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
