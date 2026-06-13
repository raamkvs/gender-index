"""Download endpoints for generated Gender Reviewer PDF reports."""
from __future__ import annotations

import logging
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from blob_client import BlobConfigError, DocGeneratedBlobClient
from supabase_client import SupabaseClient, SupabaseConfigError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/reports/{chat_id_topic}/download")
async def download_generated_report(chat_id_topic: str) -> StreamingResponse:
    """Stream the generated PDF report for a pipeline session."""
    try:
        supabase = SupabaseClient.from_env()
    except SupabaseConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    generated_doc = supabase.get_generated_document(chat_id_topic)
    if not generated_doc or not generated_doc.get("blob_url"):
        raise HTTPException(
            status_code=404,
            detail=f"No generated report found for session '{chat_id_topic}'.",
        )

    try:
        blob_client = DocGeneratedBlobClient.from_env()
        pdf_bytes = blob_client.download_pdf_report(generated_doc["blob_url"])
    except BlobConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to download generated report for %s", chat_id_topic)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to retrieve generated report: {exc}",
        ) from exc

    filename = generated_doc.get("filename") or f"{chat_id_topic}-report.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
