from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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


class FailedLink(BaseModel):
    url: str
    reason: str


class OCRError(BaseModel):
    file: str
    url: str
    error: str


class BlobLink(BaseModel):
    url: str
    filename: str


class GenderPipelineRequest(BaseModel):
    chat_id_topic: str
    links: List[str] = Field(default_factory=list)
    input: Optional[List[str] | str] = None
    run: Literal["first", "rerun"] = "first"
    output_schema_hint: Optional[str] = None
    download_timeout: int = 120

    @model_validator(mode="after")
    def normalize_links(self) -> "GenderPipelineRequest":
        """Accept `input` as a Copilot-friendly alias for `links`."""
        if self.input and not self.links:
            if isinstance(self.input, str):
                self.links = [self.input.strip()] if self.input.strip() else []
            else:
                self.links = [
                    str(url).strip()
                    for url in self.input
                    if url and str(url).strip()
                ]
        return self


class GenderPipelineResponse(BaseModel):
    chat_id_topic: str
    run: str
    report_pdf_url: Optional[str] = None
    ai_extractions: List[str]
    documents_processed: int
    total_documents: int
    undownloadable_links: List[FailedLink]
    blob_links: List[BlobLink]
    ocr_errors: List[OCRError] = []
    report_pdf_url: Optional[str] = None


class GenderPipelineAcceptedResponse(BaseModel):
    status: Literal["accepted"]
    chat_id_topic: str
    message: str
    poll_interval_seconds: int


class PipelineStatusResponse(BaseModel):
    status: Literal["pending", "in_progress", "completed", "failed"]
    chat_id_topic: str
    comments: str
    result: Optional[GenderPipelineResponse] = None
    error: Optional[str] = None
