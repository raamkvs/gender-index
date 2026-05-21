from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class IndexInfo(BaseModel):
    name: str
    doc_count: int
    status: Literal["green", "yellow", "red"]


class DocumentStatus(BaseModel):
    doc_id: str
    title: str
    keywords: List[str]
    source: str
    is_indexed: bool
    indexed_at: Optional[str]


class KeywordStatus(BaseModel):
    value: str
    is_indexed: bool
    indexed_at: Optional[str]


class SyncResult(BaseModel):
    keywords_new: int
    keywords_skipped: int
    documents_new: int
    documents_skipped: int
    duration_ms: int
    log_lines: List[str]


class KeywordOCRRequest(BaseModel):
    pdf_urls: List[str] = []
    keywords: List[str]


class KeywordMatch(BaseModel):
    file: str
    paragraph: str


class OCRSummary(BaseModel):
    processed: int
    failed: int
    errors: List[dict]


class DownloadSummary(BaseModel):
    downloaded: int
    skipped: int
    failed: int


class KeywordOCRResponse(BaseModel):
    download_summary: DownloadSummary
    ocr_summary: OCRSummary
    keyword_index: Dict[str, List[KeywordMatch]]
    report_available: bool
    report_filename: Optional[str]
