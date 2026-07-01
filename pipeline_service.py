"""Gender Reviewer pipeline: first run and rerun."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from blob_client import BlobClient, BlobConfigError, DocGeneratedBlobClient
from doc_catalog import build_catalog
from keyword_ocr_pipeline import build_keyword_index
from llm_client import analyze_document_with_llm, format_extraction_for_api
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


def _build_ai_extractions_response(
    extraction_texts: List[str],
    pdf_url: Optional[str],
    run_type: str,
) -> List[str]:
    """Prepend the generated PDF download link as the first ai_extractions entry."""
    if not pdf_url:
        return extraction_texts
    report_label = (
        "Gender Reviewer Report (Updated)"
        if run_type == "rerun"
        else "Gender Reviewer Report"
    )
    link_entry = f"{report_label} — Download PDF: {pdf_url}"
    return [link_entry, *extraction_texts]


def _generate_and_upload_pdf(
    chat_id_topic: str,
    documents: List[Dict[str, Any]],
    undownloadable_links: List[Dict[str, str]],
    run_type: str,
    supabase: SupabaseClient,
) -> Optional[str]:
    """
    Generate PDF report, upload to docs-generated blob store, and save to Supabase.
    
    Args:
        chat_id_topic: Session ID
        documents: List of document dicts with 'filename', 'ai_extraction', 'blob_url'
        undownloadable_links: List of failed downloads with 'url' and 'reason'
        run_type: "first" or "rerun"
        supabase: Supabase client
    
    Returns:
        URL of the uploaded PDF, or None if generation fails
    """
    if not documents:
        logger.info("No documents available, skipping PDF generation")
        return None
    
    try:
        # Generate PDF
        pdf_path = generate_gender_report_pdf(
            chat_id_topic=chat_id_topic,
            documents=documents,
            undownloadable_links=undownloadable_links,
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
            document_count=len(documents),
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

        logger.info(f"[PIPELINE] Processing document: {pdf_path.name}")
        
        try:
            logger.info(f"[PIPELINE] Starting OCR for {pdf_path.name}")
            paragraphs = analyze_pdf_paragraphs(pdf_path, azure_endpoint, azure_key)
            logger.info(f"[PIPELINE] OCR completed for {pdf_path.name}, extracted {len(paragraphs)} text segments")
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR failed for %s", pdf_path.name)
            ocr_errors.append(
                {"file": pdf_path.name, "url": source_url or "", "error": str(exc)}
            )
            continue

        # In-memory keyword search scoped to this document
        logger.info(f"[PIPELINE] Running keyword search for {pdf_path.name}")
        keyword_index = build_keyword_index({pdf_path.name: paragraphs}, keywords)
        matched_keywords = [kw for kw, matches in keyword_index.items() if matches]
        relevant_excerpts = [
            m["paragraph"]
            for kw_matches in keyword_index.values()
            for m in kw_matches
        ]
        logger.info(f"[PIPELINE] Found {len(matched_keywords)} keyword matches in {pdf_path.name}")

        # Build catalog entry (no longer includes excerpts, just full text)
        catalog_entry = build_catalog(
            chat_id_topic,
            [
                {
                    "source_url": source_url or "",
                    "filename": pdf_path.name,
                    "paragraphs": paragraphs,
                    "relevant_excerpts": [],  # Not used anymore
                }
            ],
        )["documents"][0]

        try:
            logger.info(f"[PIPELINE] Starting AI extraction for {pdf_path.name}")
            ai_extraction = analyze_document_with_llm(
                catalog_entry,
                output_schema_hint=output_schema_hint,
            )
            extraction_data = json.loads(ai_extraction)
            paragraphs_list = extraction_data.get("relevant_paragraphs", [])
            document_name = extraction_data.get("document_name", pdf_path.name)
            logger.info(
                "[PIPELINE] AI extraction completed: %d paragraphs from %s (document: %s)",
                len(paragraphs_list),
                pdf_path.name,
                document_name[:50] + "..." if len(document_name) > 50 else document_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM extraction failed for %s", pdf_path.name)
            ai_extraction = json.dumps(
                {
                    "document_name": pdf_path.name,
                    "document_type": "A",
                    "relevant_paragraphs": [],
                    "case_studies": [],
                    "error": f"Extraction failed: {exc}",
                }
            )

        logger.info(f"[PIPELINE] Storing extraction in Supabase for {pdf_path.name}")
        supabase.store_document_extraction(
            chat_id_topic=chat_id_topic,
            filename=pdf_path.name,
            ai_extraction=ai_extraction,
            source_url=source_url,
            blob_url=blob_url,
            keywords=matched_keywords,
        )
        logger.info(f"[PIPELINE] Successfully stored extraction for {pdf_path.name}")

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
    logger.info(f"[PIPELINE] Starting FIRST run for session: {chat_id_topic}")
    logger.info(f"[PIPELINE] Processing {len(links)} document links")
    
    supabase = _init_supabase()
    blob = _init_blob()
    azure_endpoint, azure_key = get_azure_settings()
    keywords = _load_keywords()

    # Download PDFs
    logger.info(f"[PIPELINE] Stage 1: Downloading PDFs from {len(links)} links")
    download_dir = PIPELINE_DOWNLOAD_ROOT / chat_id_topic
    download_result = download_pdfs_detailed(download_dir, links, timeout=download_timeout)
    failed_links: List[FailedLink] = list(download_result.failed_links)
    logger.info(f"[PIPELINE] Download complete: {len(download_result.files)} successful, {len(failed_links)} failed")

    # Upload downloaded PDFs to Vercel Blob (independent path — runs even if OCR fails later)
    logger.info(f"[PIPELINE] Stage 2: Uploading {len(download_result.files)} PDFs to blob storage")
    blob_links: List[Dict[str, str]] = []
    blob_url_by_file: Dict[str, str] = {}
    for pdf_path in download_result.files:
        try:
            url = blob.upload_file(pdf_path, pdf_path.name)
            blob_links.append({"url": url, "filename": pdf_path.name})
            blob_url_by_file[pdf_path.name] = url
            logger.info(f"[PIPELINE] Uploaded {pdf_path.name} to blob storage")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Blob upload failed for {pdf_path.name}: {exc}", exc_info=True)
    logger.info(f"[PIPELINE] Blob upload complete: {len(blob_links)} files uploaded")

    # OCR → keyword search → AI → store per doc in Supabase
    logger.info(f"[PIPELINE] Stage 3: Starting OCR, keyword search, and AI extraction")
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
    logger.info(f"[PIPELINE] Document processing complete: {len(ocr_errors)} OCR errors")

    # Persist pipeline metadata (undownloadable links + blob links)
    logger.info(f"[PIPELINE] Stage 4: Persisting pipeline metadata to Supabase")
    undownloadable_list = [{"url": f.url, "reason": f.reason} for f in failed_links]
    supabase.upsert_pipeline_metadata(
        chat_id_topic=chat_id_topic,
        undownloadable_links=undownloadable_list,
        blob_links=blob_links,
    )

    # Get all document records (with filename, blob_url, ai_extraction)
    all_documents = supabase.get_all_extractions(chat_id_topic)
    all_extraction_texts = [
        format_extraction_for_api(doc["ai_extraction"]) for doc in all_documents
    ]
    logger.info(f"[PIPELINE] Retrieved {len(all_documents)} document extractions from Supabase")

    # Generate PDF report and upload to docs-generated blob store
    logger.info(f"[PIPELINE] Stage 5: Generating PDF report")
    generated_pdf_url = _generate_and_upload_pdf(
        chat_id_topic=chat_id_topic,
        documents=all_documents,
        undownloadable_links=undownloadable_list,
        run_type="first",
        supabase=supabase,
    )
    ai_extractions = _build_ai_extractions_response(
        all_extraction_texts, generated_pdf_url, "first"
    )

    logger.info(f"[PIPELINE] FIRST run completed successfully for session: {chat_id_topic}")
    logger.info(f"[PIPELINE] Summary: {len(download_result.files)} documents processed, {len(all_extraction_texts)} total extractions")
    
    return {
        "chat_id_topic": chat_id_topic,
        "run": "first",
        "report_pdf_url": generated_pdf_url,
        "ai_extractions": ai_extractions,
        "documents_processed": len(download_result.files),
        "total_documents": len(all_extraction_texts),
        "undownloadable_links": undownloadable_list,
        "blob_links": blob_links,
        "ocr_errors": ocr_errors,
    }


def _run_pipeline_rerun(
    chat_id_topic: str,
    output_schema_hint: Optional[str],
    download_timeout: int,
) -> Dict[str, Any]:
    logger.info(f"[PIPELINE] Starting RERUN for session: {chat_id_topic}")
    
    supabase = _init_supabase()
    blob = _init_blob()
    azure_endpoint, azure_key = get_azure_settings()
    keywords = _load_keywords()

    # Query uploads WHERE chat_id_topic = X AND processed = false
    logger.info(f"[PIPELINE] Querying unprocessed uploads for session: {chat_id_topic}")
    unprocessed = supabase.get_unprocessed_uploads(chat_id_topic)
    logger.info(f"[PIPELINE] Found {len(unprocessed)} unprocessed uploads")

    if not unprocessed:
        logger.info(f"[PIPELINE] No unprocessed uploads found, returning existing data")
        all_documents = supabase.get_all_extractions(chat_id_topic)
        all_extraction_texts = [
            format_extraction_for_api(doc["ai_extraction"]) for doc in all_documents
        ]
        generated_doc = supabase.get_generated_document(chat_id_topic)
        generated_pdf_url = generated_doc["blob_url"] if generated_doc else None
        
        # Get pipeline metadata for undownloadable_links
        pipeline_meta = supabase.get_pipeline_metadata(chat_id_topic)
        undownloadable_list = pipeline_meta.get("undownloadable_links", []) if pipeline_meta else []
        
        ai_extractions = _build_ai_extractions_response(
            all_extraction_texts, generated_pdf_url, "rerun"
        )
        logger.info(f"[PIPELINE] RERUN completed (no new documents): {len(all_extraction_texts)} total extractions")
        return {
            "chat_id_topic": chat_id_topic,
            "run": "rerun",
            "report_pdf_url": generated_pdf_url,
            "ai_extractions": ai_extractions,
            "documents_processed": 0,
            "total_documents": len(all_extraction_texts),
            "undownloadable_links": undownloadable_list,
            "blob_links": [],
            "ocr_errors": [],
        }

    # Download each unprocessed file from Blob
    logger.info(f"[PIPELINE] Stage 1: Downloading {len(unprocessed)} unprocessed files from blob storage")
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
            logger.info(f"[PIPELINE] Downloaded {upload['filename']} from blob storage")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to download blob %s: %s", upload["blob_url"], exc
            )
    logger.info(f"[PIPELINE] Downloaded {len(pdf_paths)} files successfully")

    # OCR → keyword search → AI → store per doc in Supabase
    logger.info(f"[PIPELINE] Stage 2: Starting OCR, keyword search, and AI extraction")
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
    logger.info(f"[PIPELINE] Document processing complete: {len(ocr_errors)} OCR errors")

    # Mark all queried uploads as processed (even if some failed OCR/AI)
    logger.info(f"[PIPELINE] Marking {len(unprocessed)} uploads as processed")
    supabase.mark_uploads_processed([u["id"] for u in unprocessed])

    # Get all document records and pipeline metadata
    all_documents = supabase.get_all_extractions(chat_id_topic)
    all_extraction_texts = [
        format_extraction_for_api(doc["ai_extraction"]) for doc in all_documents
    ]
    logger.info(f"[PIPELINE] Retrieved {len(all_documents)} document extractions from Supabase")

    # Get undownloadable links from pipeline metadata
    pipeline_meta = supabase.get_pipeline_metadata(chat_id_topic)
    undownloadable_list = pipeline_meta.get("undownloadable_links", []) if pipeline_meta else []

    # Generate PDF report and upload to docs-generated blob store
    logger.info(f"[PIPELINE] Stage 3: Generating PDF report")
    generated_pdf_url = _generate_and_upload_pdf(
        chat_id_topic=chat_id_topic,
        documents=all_documents,
        undownloadable_links=undownloadable_list,
        run_type="rerun",
        supabase=supabase,
    )
    ai_extractions = _build_ai_extractions_response(
        all_extraction_texts, generated_pdf_url, "rerun"
    )

    logger.info(f"[PIPELINE] RERUN completed successfully for session: {chat_id_topic}")
    logger.info(f"[PIPELINE] Summary: {len(pdf_paths)} new documents processed, {len(all_extraction_texts)} total extractions")
    
    return {
        "chat_id_topic": chat_id_topic,
        "run": "rerun",
        "report_pdf_url": generated_pdf_url,
        "ai_extractions": ai_extractions,
        "documents_processed": len(pdf_paths),
        "total_documents": len(all_extraction_texts),
        "undownloadable_links": undownloadable_list,
        "blob_links": blob_links,
        "ocr_errors": ocr_errors,
    }
