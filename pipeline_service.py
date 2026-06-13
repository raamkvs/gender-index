"""Gender Reviewer pipeline: first run and rerun."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from blob_client import BlobClient, BlobConfigError, DocGeneratedBlobClient
from doc_catalog import build_catalog
from keyword_ocr_pipeline import build_keyword_index
from llm_client import analyze_document_with_llm
from ocr import analyze_pdf_paragraphs, get_azure_settings
from pdf_generator import generate_gender_report_pdf
from pipeline_download import FailedLink, download_pdfs_detailed
from supabase_client import SupabaseClient, SupabaseConfigError

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
PIPELINE_DOWNLOAD_ROOT = ROOT_DIR / "downloads" / "pipeline"
KEYWORDS_FILE = ROOT_DIR / "registries" / "keywords.json"
DEFAULT_DOWNLOAD_TIMEOUT = 120


def _load_keywords() -> List[str]:
    with KEYWORDS_FILE.open("r", encoding="utf-8") as fh:
        return [str(k) for k in json.load(fh)]


def _init_supabase() -> SupabaseClient:
    try:
        return SupabaseClient.from_env()
    except SupabaseConfigError as exc:
        raise RuntimeError(f"Supabase not configured: {exc}") from exc


def _init_blob() -> BlobClient:
    try:
        return BlobClient.from_env()
    except BlobConfigError as exc:
        raise RuntimeError(f"Vercel Blob not configured: {exc}") from exc


def _generate_and_upload_pdf(
    chat_id_topic: str,
    ai_extractions: List[str],
    documents_processed: int,
    run_type: str,
    supabase: SupabaseClient,
) -> Optional[str]:
    """
    Generate PDF report, upload to docs-generated blob store, and save to Supabase.
    
    Returns:
        URL of the uploaded PDF, or None if generation fails
    """
    if not ai_extractions:
        logger.info("No AI extractions available, skipping PDF generation")
        return None
    
    try:
        # Generate PDF
        pdf_path = generate_gender_report_pdf(
            chat_id_topic=chat_id_topic,
            ai_extractions=ai_extractions,
            documents_processed=documents_processed,
            run_type=run_type,
        )
        
        # Upload to docs-generated blob store
        doc_blob_client = DocGeneratedBlobClient.from_env()
        pdf_url = doc_blob_client.upload_pdf_report(pdf_path, chat_id_topic)
        
        # Store in Supabase
        supabase.store_generated_document(
            chat_id_topic=chat_id_topic,
            blob_url=pdf_url,
            filename=f"{chat_id_topic}-report.pdf",
            document_count=len(ai_extractions),
        )
        
        # Clean up temp file
        pdf_path.unlink()
        
        logger.info(f"PDF report generated and uploaded successfully: {pdf_url}")
        return pdf_url
    except Exception as e:
        logger.error(f"Failed to generate or upload PDF report: {e}")
        # Don't fail the entire pipeline if PDF generation fails
        return None


def _extract_and_store_documents(
    chat_id_topic: str,
    pdf_paths: List[Path],
    url_by_file: Dict[str, str],
    blob_url_by_file: Dict[str, str],
    output_schema_hint: Optional[str],
    keywords: List[str],
    azure_endpoint: str,
    azure_key: str,
    supabase: SupabaseClient,
) -> List[Dict[str, str]]:
    """OCR → in-memory keyword search → AI extract → store per-document in Supabase.

    Returns a list of ocr_errors dicts.
    """
    ocr_errors: List[Dict[str, str]] = []

    for pdf_path in pdf_paths:
        source_url = url_by_file.get(pdf_path.name) or None
        blob_url = blob_url_by_file.get(pdf_path.name) or None

        try:
            paragraphs = analyze_pdf_paragraphs(pdf_path, azure_endpoint, azure_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR failed for %s", pdf_path.name)
            ocr_errors.append(
                {"file": pdf_path.name, "url": source_url or "", "error": str(exc)}
            )
            continue

        # In-memory keyword search scoped to this document
        keyword_index = build_keyword_index({pdf_path.name: paragraphs}, keywords)
        matched_keywords = [kw for kw, matches in keyword_index.items() if matches]
        relevant_excerpts = [
            m["paragraph"]
            for kw_matches in keyword_index.values()
            for m in kw_matches
        ]

        # Build catalog entry with keyword excerpts included for LLM context
        catalog_entry = build_catalog(
            chat_id_topic,
            [
                {
                    "source_url": source_url or "",
                    "filename": pdf_path.name,
                    "paragraphs": paragraphs,
                    "relevant_excerpts": relevant_excerpts,
                }
            ],
        )["documents"][0]

        try:
            ai_extraction = analyze_document_with_llm(
                catalog_entry, output_schema_hint=output_schema_hint
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM extraction failed for %s", pdf_path.name)
            ai_extraction = f"Extraction failed: {exc}"

        supabase.store_document_extraction(
            chat_id_topic=chat_id_topic,
            filename=pdf_path.name,
            ai_extraction=ai_extraction,
            source_url=source_url,
            blob_url=blob_url,
            keywords=matched_keywords,
        )

    return ocr_errors


def run_gender_pipeline(
    chat_id_topic: str,
    links: List[str],
    run: Literal["first", "rerun"] = "first",
    output_schema_hint: Optional[str] = None,
    download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
) -> Dict[str, Any]:
    """
    Run "first": Download PDFs from links → upload to Blob → OCR → AI per doc → Supabase.
    Run "rerun": Pull unprocessed uploads (chat_id + processed=false) → OCR → AI → Supabase.
    Both runs return ALL ai_extractions for the chat_id_topic.
    """
    if not chat_id_topic.strip():
        raise ValueError("chat_id_topic is required")

    if run == "first" and not links:
        raise ValueError('links are required for run="first"')

    if run == "first":
        return _run_pipeline_first(
            chat_id_topic.strip(), links, output_schema_hint, download_timeout
        )
    if run == "rerun":
        return _run_pipeline_rerun(
            chat_id_topic.strip(), output_schema_hint, download_timeout
        )
    raise ValueError(f"Invalid run type {run!r}. Must be 'first' or 'rerun'.")


def _run_pipeline_first(
    chat_id_topic: str,
    links: List[str],
    output_schema_hint: Optional[str],
    download_timeout: int,
) -> Dict[str, Any]:
    supabase = _init_supabase()
    blob = _init_blob()
    azure_endpoint, azure_key = get_azure_settings()
    keywords = _load_keywords()

    # Download PDFs
    download_dir = PIPELINE_DOWNLOAD_ROOT / chat_id_topic
    download_result = download_pdfs_detailed(download_dir, links, timeout=download_timeout)
    failed_links: List[FailedLink] = list(download_result.failed_links)

    # Upload downloaded PDFs to Vercel Blob (independent path — runs even if OCR fails later)
    blob_links: List[Dict[str, str]] = []
    blob_url_by_file: Dict[str, str] = {}
    for pdf_path in download_result.files:
        try:
            url = blob.upload_file(pdf_path, pdf_path.name)
            blob_links.append({"url": url, "filename": pdf_path.name})
            blob_url_by_file[pdf_path.name] = url
        except Exception as exc:  # noqa: BLE001
            logger.warning("Blob upload failed for %s: %s", pdf_path.name, exc)

    # OCR → keyword search → AI → store per doc in Supabase
    ocr_errors: List[Dict[str, str]] = []
    if download_result.files:
        ocr_errors = _extract_and_store_documents(
            chat_id_topic=chat_id_topic,
            pdf_paths=download_result.files,
            url_by_file=download_result.url_by_file,
            blob_url_by_file=blob_url_by_file,
            output_schema_hint=output_schema_hint,
            keywords=keywords,
            azure_endpoint=azure_endpoint,
            azure_key=azure_key,
            supabase=supabase,
        )

    # Persist pipeline metadata (undownloadable links + blob links)
    supabase.upsert_pipeline_metadata(
        chat_id_topic=chat_id_topic,
        undownloadable_links=[{"url": f.url, "reason": f.reason} for f in failed_links],
        blob_links=blob_links,
    )

    all_extractions = supabase.get_all_extraction_texts(chat_id_topic)

    # Generate PDF report and upload to docs-generated blob store
    generated_pdf_url = _generate_and_upload_pdf(
        chat_id_topic=chat_id_topic,
        ai_extractions=all_extractions,
        documents_processed=len(download_result.files),
        run_type="first",
        supabase=supabase,
    )

    return {
        "chat_id_topic": chat_id_topic,
        "run": "first",
        "ai_extractions": all_extractions,
        "documents_processed": len(download_result.files),
        "total_documents": len(all_extractions),
        "undownloadable_links": [{"url": f.url, "reason": f.reason} for f in failed_links],
        "blob_links": blob_links,
        "ocr_errors": ocr_errors,
        "generated_pdf_url": generated_pdf_url,
    }


def _run_pipeline_rerun(
    chat_id_topic: str,
    output_schema_hint: Optional[str],
    download_timeout: int,
) -> Dict[str, Any]:
    supabase = _init_supabase()
    blob = _init_blob()
    azure_endpoint, azure_key = get_azure_settings()
    keywords = _load_keywords()

    # Query uploads WHERE chat_id_topic = X AND processed = false
    unprocessed = supabase.get_unprocessed_uploads(chat_id_topic)

    if not unprocessed:
        all_extractions = supabase.get_all_extraction_texts(chat_id_topic)
        return {
            "chat_id_topic": chat_id_topic,
            "run": "rerun",
            "ai_extractions": all_extractions,
            "documents_processed": 0,
            "total_documents": len(all_extractions),
            "undownloadable_links": [],
            "blob_links": [],
            "ocr_errors": [],
        }

    # Download each unprocessed file from Blob
    download_dir = PIPELINE_DOWNLOAD_ROOT / f"{chat_id_topic}_rerun"
    download_dir.mkdir(parents=True, exist_ok=True)

    pdf_paths: List[Path] = []
    blob_url_by_file: Dict[str, str] = {}
    blob_links: List[Dict[str, str]] = []

    for upload in unprocessed:
        dest = download_dir / upload["filename"]
        try:
            blob.download_file(upload["blob_url"], dest, timeout=download_timeout)
            pdf_paths.append(dest)
            blob_url_by_file[upload["filename"]] = upload["blob_url"]
            blob_links.append({"url": upload["blob_url"], "filename": upload["filename"]})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to download blob %s: %s", upload["blob_url"], exc
            )

    # OCR → keyword search → AI → store per doc in Supabase
    ocr_errors: List[Dict[str, str]] = []
    if pdf_paths:
        ocr_errors = _extract_and_store_documents(
            chat_id_topic=chat_id_topic,
            pdf_paths=pdf_paths,
            url_by_file={},
            blob_url_by_file=blob_url_by_file,
            output_schema_hint=output_schema_hint,
            keywords=keywords,
            azure_endpoint=azure_endpoint,
            azure_key=azure_key,
            supabase=supabase,
        )

    # Mark all queried uploads as processed (even if some failed OCR/AI)
    supabase.mark_uploads_processed([u["id"] for u in unprocessed])

    all_extractions = supabase.get_all_extraction_texts(chat_id_topic)

    # Generate PDF report and upload to docs-generated blob store
    generated_pdf_url = _generate_and_upload_pdf(
        chat_id_topic=chat_id_topic,
        ai_extractions=all_extractions,
        documents_processed=len(pdf_paths),
        run_type="rerun",
        supabase=supabase,
    )

    return {
        "chat_id_topic": chat_id_topic,
        "run": "rerun",
        "ai_extractions": all_extractions,
        "documents_processed": len(pdf_paths),
        "total_documents": len(all_extractions),
        "undownloadable_links": [],
        "blob_links": blob_links,
        "ocr_errors": ocr_errors,
        "generated_pdf_url": generated_pdf_url,
    }
