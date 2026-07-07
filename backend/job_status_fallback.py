"""Fallback status lookup when in-memory jobs are unavailable."""
from __future__ import annotations

import logging
from typing import Optional

from backend.schemas import GenderPipelineResponse, PipelineStatusResponse
from pipeline_service import _build_ai_extractions_response
from llm_client import format_extraction_for_api
from supabase_client import SupabaseClient, SupabaseConfigError

logger = logging.getLogger(__name__)


def load_completed_status_from_supabase(chat_id_topic: str) -> Optional[PipelineStatusResponse]:
    """Return completed status if Supabase has stored extractions for this session."""
    try:
        supabase = SupabaseClient.from_env()
    except SupabaseConfigError:
        return None

    try:
        rows = supabase.get_latest_extractions_by_filename(chat_id_topic)
        if not rows:
            return None

        extractions = [
            format_extraction_for_api(row["ai_extraction"]) for row in rows
        ]
        metadata = supabase.get_pipeline_metadata(chat_id_topic) or {}
        
        # Fetch generated PDF URL and prepend to ai_extractions for chatbot access
        generated_doc = supabase.get_generated_document(chat_id_topic)
        generated_pdf_url = generated_doc["blob_url"] if generated_doc else None
        ai_extractions = _build_ai_extractions_response(
            extractions, generated_pdf_url, "first"
        )

        return PipelineStatusResponse(
            status="completed",
            chat_id_topic=chat_id_topic,
            comments="Pipeline completed successfully (retrieved from storage)",
            result=GenderPipelineResponse(
                chat_id_topic=chat_id_topic,
                run="first",
                report_pdf_url=generated_pdf_url,
                ai_extractions=ai_extractions,
                documents_processed=len(extractions),
                total_documents=len(extractions),
                undownloadable_links=metadata.get("undownloadable_links") or [],
                blob_links=metadata.get("blob_links") or [],
                ocr_errors=[],
            ),
        )
    except Exception as exc:
        logger.warning("Supabase status fallback failed for %s: %s", chat_id_topic, exc)
        return None
