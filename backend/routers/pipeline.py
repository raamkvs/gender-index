from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from job_manager import get_job_manager
from pipeline_service import run_gender_pipeline
from ..schemas import (
    GenderPipelineAcceptedResponse,
    GenderPipelineRequest,
    GenderPipelineResponse,
)
from ..response_delay import wait_for_response_window

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


def _run_pipeline_background(
    chat_id_topic: str,
    links: list[str],
    run: str,
    output_schema_hint: str | None,
    download_timeout: int,
) -> None:
    """Run pipeline in background thread and update job status."""
    job_manager = get_job_manager()

    try:
        logger.info("Starting background pipeline for chat_id_topic=%s", chat_id_topic)
        job_manager.update_job(chat_id_topic, status="in_progress")

        result = run_gender_pipeline(
            chat_id_topic=chat_id_topic,
            links=links,
            run=run,
            output_schema_hint=output_schema_hint,
            download_timeout=download_timeout,
        )

        job_manager.update_job(chat_id_topic, status="completed", result=result)
        logger.info("Pipeline completed for chat_id_topic=%s", chat_id_topic)

    except Exception as exc:
        logger.exception("Pipeline failed for chat_id_topic=%s", chat_id_topic)
        job_manager.update_job(chat_id_topic, status="failed", error=str(exc))


@router.post("/analyze", response_model=GenderPipelineAcceptedResponse, status_code=202)
async def analyze_pipeline(request: GenderPipelineRequest) -> GenderPipelineAcceptedResponse:
    """
    Start async pipeline execution. Returns immediately with accepted status.
    Client should poll /health?chat_id={chat_id_topic} for status and results.

    Response timing: ~10 seconds (enforced minimum)
    """
    if not request.chat_id_topic.strip():
        raise HTTPException(status_code=400, detail="chat_id_topic is required")

    if request.run not in ("first", "rerun"):
        raise HTTPException(
            status_code=400, detail='run must be "first" or "rerun"'
        )

    if request.run == "first" and not request.links:
        raise HTTPException(
            status_code=400, detail='links are required for run="first"'
        )

    chat_id_topic = request.chat_id_topic.strip()
    job_manager = get_job_manager()

    # Create job with pending status
    job_manager.create_job(chat_id_topic)

    # Start background thread
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(
            chat_id_topic,
            request.links,
            request.run,
            request.output_schema_hint,
            request.download_timeout,
        ),
        daemon=True,
    )
    thread.start()

    # Hold response for minimum 10 seconds
    await wait_for_response_window(is_ready=lambda: False)

    return GenderPipelineAcceptedResponse(
        status="accepted",
        chat_id_topic=chat_id_topic,
        message=f"Pipeline request accepted. Poll /health?chat_id={chat_id_topic} for status.",
        poll_interval_seconds=10,
    )
