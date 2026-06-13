"""Fallback status lookup when in-memory jobs are unavailable."""
from __future__ import annotations

import logging
from typing import Optional

from backend.schemas import GenderPipelineResponse, PipelineStatusResponse
from supabase_client import SupabaseClient, SupabaseConfigError

logger = logging.getLogger(__name__)


def load_completed_status_from_supabase(chat_id_topic: str) -> Optional[PipelineStatusResponse]:
    """Return completed status if Supabase has stored extractions for this session."""
    try:
        supabase = SupabaseClient.from_env()
    except SupabaseConfigError:
        return None

    try:
        extractions = supabase.get_all_extraction_texts(chat_id_topic)
        if not extractions:
            return None

        metadata = supabase.get_pipeline_metadata(chat_id_topic) or {}
        
        # Fetch generated PDF URL from database
        generated_doc = supabase.get_generated_document(chat_id_topic)
        generated_pdf_url = generated_doc["blob_url"] if generated_doc else None
        
        return PipelineStatusResponse(
            status="completed",
            chat_id_topic=chat_id_topic,
            comments="Pipeline completed successfully (retrieved from storage)",
            result=GenderPipelineResponse(
                chat_id_topic=chat_id_topic,
                run="first",
                ai_extractions=extractions,
                documents_processed=len(extractions),
                total_documents=len(extractions),
                undownloadable_links=metadata.get("undownloadable_links") or [],
                blob_links=metadata.get("blob_links") or [],
                ocr_errors=[],
                generated_pdf_url=generated_pdf_url,
            ),
        )
    except Exception as exc:
        logger.warning("Supabase status fallback failed for %s: %s", chat_id_topic, exc)
        return None
