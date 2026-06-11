from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline_service import run_gender_pipeline
from ..schemas import GenderPipelineRequest, GenderPipelineResponse

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/analyze", response_model=GenderPipelineResponse)
def analyze_pipeline(request: GenderPipelineRequest) -> GenderPipelineResponse:
    """
    Run "first": Download PDFs from links, OCR, AI extract per doc, store in Supabase.
    Run "rerun": Process unprocessed uploads for this chat_id, combine with existing extractions.

    Both runs return all ai_extractions for the chat_id_topic.
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

    try:
        result = run_gender_pipeline(
            chat_id_topic=request.chat_id_topic.strip(),
            links=request.links,
            run=request.run,
            output_schema_hint=request.output_schema_hint,
            download_timeout=request.download_timeout,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return GenderPipelineResponse(**result)
