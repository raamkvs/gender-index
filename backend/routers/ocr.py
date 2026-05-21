from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from keyword_ocr_pipeline import get_azure_settings, run_keyword_ocr
from schemas import KeywordOCRRequest, KeywordOCRResponse

router = APIRouter(prefix="/ocr", tags=["ocr"])

TEMP_OUTPUT_DIR = Path(tempfile.gettempdir()) / "doc-indexer-ocr"
TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/keyword-report", response_model=KeywordOCRResponse)
def process_keyword_ocr(request: KeywordOCRRequest) -> KeywordOCRResponse:
    """
    Process PDFs from URLs, extract paragraphs via Azure OCR, and index keywords.
    """
    try:
        endpoint, key = get_azure_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Azure configuration error: {exc}")

    if not request.pdf_urls and not request.keywords:
        raise HTTPException(status_code=400, detail="Must provide pdf_urls and keywords")

    result = run_keyword_ocr(
        links=request.pdf_urls,
        keywords=request.keywords,
        output_dir=TEMP_OUTPUT_DIR,
        endpoint=endpoint,
        key=key,
    )

    return KeywordOCRResponse(
        download_summary=result["download_summary"],
        ocr_summary=result["ocr_summary"],
        keyword_index=result["keyword_index"],
        report_available=result["report_path"] is not None,
        report_filename=Path(result["report_path"]).name if result["report_path"] else None,
    )


@router.post("/keyword-report-upload", response_model=KeywordOCRResponse)
async def process_keyword_ocr_upload(
    keywords: str = Form(...),
    files: List[UploadFile] = File(...),
) -> KeywordOCRResponse:
    """
    Process uploaded PDF files, extract paragraphs via Azure OCR, and index keywords.
    Keywords should be comma-separated string.
    """
    try:
        endpoint, key = get_azure_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Azure configuration error: {exc}")

    keyword_list = [kw.strip() for kw in keywords.split(",") if kw.strip()]
    if not keyword_list:
        raise HTTPException(status_code=400, detail="Must provide at least one keyword")

    if not files:
        raise HTTPException(status_code=400, detail="Must upload at least one PDF file")

    uploaded_paths: List[Path] = []
    upload_dir = TEMP_OUTPUT_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    try:
        for uploaded_file in files:
            if not uploaded_file.filename.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400, detail=f"Only PDF files allowed: {uploaded_file.filename}"
                )

            file_path = upload_dir / uploaded_file.filename
            content = await uploaded_file.read()
            file_path.write_bytes(content)
            uploaded_paths.append(file_path)

        result = run_keyword_ocr(
            links=[],
            keywords=keyword_list,
            output_dir=TEMP_OUTPUT_DIR,
            endpoint=endpoint,
            key=key,
            uploaded_files=uploaded_paths,
        )

        return KeywordOCRResponse(
            download_summary=result["download_summary"],
            ocr_summary=result["ocr_summary"],
            keyword_index=result["keyword_index"],
            report_available=result["report_path"] is not None,
            report_filename=Path(result["report_path"]).name if result["report_path"] else None,
        )
    finally:
        for path in uploaded_paths:
            if path.exists():
                path.unlink()


@router.get("/download-report/{filename}")
def download_report(filename: str) -> FileResponse:
    """
    Download the generated Word report.
    """
    report_path = TEMP_OUTPUT_DIR / filename
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(
        path=str(report_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
