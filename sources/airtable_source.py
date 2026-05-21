"""Airtable source: turn attachments stored in an Airtable table into
indexable documents.

Two-phase API so the caller can dedup against the `StateTracker`
before paying the OCR cost:

    source = AirtableSource.from_env()
    metas = source.list_attachments()          # cheap: HTTP only
    new_metas = [m for m in metas if not tracker.is_indexed(m["doc_id"])]
    for meta in new_metas:
        doc = source.fetch_content(meta, ...)  # downloads + OCR
        ...
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from ocr import analyze_pdf_paragraphs

AIRTABLE_API_BASE = "https://api.airtable.com/v0"
DEFAULT_DOWNLOAD_DIR = Path("downloads/airtable")


class AirtableConfigError(RuntimeError):
    pass


class AirtableSource:
    def __init__(
        self,
        pat: str,
        base_id: str,
        table_name: str,
        attachment_field: str = "Attachments",
        title_field: Optional[str] = None,
        keywords_field: Optional[str] = None,
        download_dir: Path = DEFAULT_DOWNLOAD_DIR,
    ) -> None:
        self.pat = pat
        self.base_id = base_id
        self.table_name = table_name
        self.attachment_field = attachment_field
        self.title_field = title_field
        self.keywords_field = keywords_field
        self.download_dir = download_dir

    @classmethod
    def from_env(cls) -> "AirtableSource":
        pat = os.getenv("AIRTABLE_PAT", "").strip()
        base_id = os.getenv("AIRTABLE_BASE_ID", "").strip()
        table_name = os.getenv("AIRTABLE_TABLE_NAME", "").strip()
        attachment_field = os.getenv("AIRTABLE_ATTACHMENT_FIELD", "Attachments").strip()
        title_field = os.getenv("AIRTABLE_TITLE_FIELD", "").strip() or None
        keywords_field = os.getenv("AIRTABLE_KEYWORDS_FIELD", "").strip() or None
        if not pat or not base_id or not table_name:
            missing = [
                name
                for name, value in {
                    "AIRTABLE_PAT": pat,
                    "AIRTABLE_BASE_ID": base_id,
                    "AIRTABLE_TABLE_NAME": table_name,
                }.items()
                if not value
            ]
            raise AirtableConfigError(
                f"Airtable env vars missing: {', '.join(missing)}"
            )
        return cls(
            pat=pat,
            base_id=base_id,
            table_name=table_name,
            attachment_field=attachment_field,
            title_field=title_field,
            keywords_field=keywords_field,
        )

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.pat}"}

    def _iter_records(self) -> Iterable[Dict[str, Any]]:
        url = f"{AIRTABLE_API_BASE}/{self.base_id}/{self.table_name}"
        params: Dict[str, Any] = {"pageSize": 100}
        while True:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=30
            )
            response.raise_for_status()
            payload = response.json()
            for record in payload.get("records", []):
                yield record
            offset = payload.get("offset")
            if not offset:
                break
            params["offset"] = offset

    def list_attachments(self) -> List[Dict[str, Any]]:
        """Return one metadata dict per attachment. No downloads, no OCR."""
        attachments: List[Dict[str, Any]] = []
        for record in self._iter_records():
            record_id = record["id"]
            fields = record.get("fields", {}) or {}

            record_title = None
            if self.title_field:
                record_title = fields.get(self.title_field)
            if not record_title:
                record_title = fields.get("Name") or record_id

            record_keywords: List[str] = []
            if self.keywords_field:
                raw = fields.get(self.keywords_field, [])
                if isinstance(raw, list):
                    record_keywords = [str(item).strip() for item in raw if item]
                elif isinstance(raw, str):
                    record_keywords = [
                        item.strip() for item in raw.split(",") if item.strip()
                    ]

            for attachment in fields.get(self.attachment_field, []) or []:
                attachment_id = attachment.get("id")
                url = attachment.get("url")
                if not attachment_id or not url:
                    continue
                attachments.append(
                    {
                        "doc_id": f"airtable_{record_id}_{attachment_id}",
                        "title": attachment.get("filename") or record_title,
                        "record_id": record_id,
                        "record_title": record_title,
                        "record_keywords": record_keywords,
                        "attachment_id": attachment_id,
                        "url": url,
                        "filename": attachment.get("filename"),
                        "type": attachment.get("type", ""),
                        "size": attachment.get("size"),
                    }
                )
        return attachments

    def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)

    def fetch_content(
        self,
        attachment_meta: Dict[str, Any],
        azure_endpoint: str,
        azure_key: str,
    ) -> Dict[str, Any]:
        """Download the attachment, OCR if it's a PDF, return an indexable doc."""
        record_id = attachment_meta["record_id"]
        attachment_id = attachment_meta["attachment_id"]
        filename = attachment_meta.get("filename") or f"{attachment_id}.pdf"
        local_path = self.download_dir / record_id / filename

        if not local_path.exists():
            self._download(attachment_meta["url"], local_path)

        mime_type = (attachment_meta.get("type") or "").lower()
        is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"

        content = ""
        if is_pdf:
            paragraphs = analyze_pdf_paragraphs(local_path, azure_endpoint, azure_key)
            content = "\n\n".join(paragraphs)

        return {
            "doc_id": attachment_meta["doc_id"],
            "title": attachment_meta["title"],
            "content": content,
            "keywords": attachment_meta.get("record_keywords", []),
            "source": attachment_meta.get("url"),
            "origin": "airtable",
            "airtable_record_id": record_id,
            "airtable_attachment_id": attachment_id,
            "airtable_record_title": attachment_meta.get("record_title"),
            "filename": filename,
            "mime_type": mime_type,
        }
