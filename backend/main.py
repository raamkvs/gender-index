from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT / ".env.local", override=False)

from backend.job_status_fallback import load_completed_status_from_supabase
from backend.response_delay import wait_for_response_window
from backend.routers import documents, indexes, keywords, ocr, pipeline, reports, sync
from backend.routers.common import build_services
from backend.schemas import GenderPipelineResponse, PipelineStatusResponse
from job_manager import get_job_manager

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
app.include_router(reports.router, prefix="/api")
app.include_router(sync.router, prefix="/api")


@app.get("/health")
async def health_check(
    chat_id: Optional[str] = None,
) -> Union[dict, PipelineStatusResponse]:
    """
    Dual-purpose endpoint:
    - No chat_id: Simple health check (instant response)
    - With chat_id: Pipeline status polling (10-25s bounded long-poll)
    """
    # Simple health check for monitoring (instant)
    if chat_id is None:
        return {"status": "healthy", "service": "doc-indexer-api"}

    chat_id = chat_id.strip()
    job_manager = get_job_manager()
    job = job_manager.get_job(chat_id)

    if job is None:
        stored = load_completed_status_from_supabase(chat_id)
        if stored is not None:
            return stored
        raise HTTPException(
            status_code=404,
            detail=(
                "Job not found. Pass the exact chat_id_topic from the analyze response "
                "(not the Copilot conversation ID). If the pipeline was just started, "
                "retry in a few seconds. If the server restarted, call analyze again."
            ),
        )

    # Bounded long-poll: wait min 10s, check every 1s, max 25s (under Copilot 30s limit)
    await wait_for_response_window(
        is_ready=lambda: job_manager.get_job(chat_id) is not None
        and job_manager.get_job(chat_id).status in ("completed", "failed")
    )

    # Re-fetch job after wait
    job = job_manager.get_job(chat_id)
    if job is None:
        stored = load_completed_status_from_supabase(chat_id)
        if stored is not None:
            return stored
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "completed":
        return PipelineStatusResponse(
            status="completed",
            chat_id_topic=job.chat_id_topic,
            comments="Pipeline completed successfully",
            result=GenderPipelineResponse(**job.result) if job.result else None,
        )

    elif job.status == "failed":
        return PipelineStatusResponse(
            status="failed",
            chat_id_topic=job.chat_id_topic,
            comments="Pipeline failed",
            error=job.error,
        )

    else:
        # Still pending or in_progress
        return PipelineStatusResponse(
            status=job.status,
            chat_id_topic=job.chat_id_topic,
            comments="wait",
        )


@app.on_event("startup")
def startup_check() -> None:
    es_host = os.getenv("ES_HOST", "").strip()
    if not es_host:
        logger.info("ES_HOST not set; skipping Elasticsearch startup check.")
        return
    try:
        manager = build_services()["manager"]
        healthy = manager.health_check()
        if healthy:
            logger.info("Elasticsearch connection healthy.")
        else:
            logger.warning("Elasticsearch unreachable at startup.")
    except Exception as exc:
        logger.warning(f"Elasticsearch check failed: {exc}. OCR endpoints will work without ES.")
