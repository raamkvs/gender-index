"""Google Forms source: turn file-upload answers from a Google Form into
indexable documents.

Two-phase API (matches AirtableSource) so the caller can dedup against the
`StateTracker` before paying the OCR cost:

    source = GoogleFormsSource.from_env()
    metas = source.list_files()                # cheap: Forms API only
    new_metas = [m for m in metas if doc_id_not_indexed]
    for meta in new_metas:
        doc = source.fetch_content(meta, ...)  # downloads from Drive + OCRs
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ocr import analyze_pdf_paragraphs

DEFAULT_DOWNLOAD_DIR = Path("downloads/google_forms")
SCOPES = [
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleFormsConfigError(RuntimeError):
    pass


class GoogleFormsSource:
    def __init__(
        self,
        credentials_path: Path,
        form_id: str,
        download_dir: Path = DEFAULT_DOWNLOAD_DIR,
    ) -> None:
        self.credentials_path = credentials_path
        self.form_id = form_id
        self.download_dir = download_dir
        self._forms_service = None
        self._drive_service = None
        self._question_titles: Dict[str, str] = {}

    @classmethod
    def from_env(cls) -> "GoogleFormsSource":
        creds = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            os.getenv("GCP_CREDENTIALS_PATH", ""),
        ).strip()
        form_id = os.getenv("GOOGLE_FORM_ID", "").strip()

        missing: List[str] = []
        if not creds:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if not form_id:
            missing.append("GOOGLE_FORM_ID")
        if missing:
            raise GoogleFormsConfigError(
                f"Google Forms env vars missing: {', '.join(missing)}"
            )

        creds_path = Path(creds)
        if not creds_path.is_absolute():
            creds_path = (Path(__file__).resolve().parent.parent / creds_path).resolve()
        if not creds_path.exists():
            raise GoogleFormsConfigError(
                f"Service account file not found: {creds_path}"
            )

        return cls(credentials_path=creds_path, form_id=form_id)

    def _build_services(self) -> None:
        if self._forms_service is not None and self._drive_service is not None:
            return
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            str(self.credentials_path), scopes=SCOPES
        )
        self._forms_service = build(
            "forms", "v1", credentials=credentials, cache_discovery=False
        )
        self._drive_service = build(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )

    def _load_question_titles(self) -> Dict[str, str]:
        if self._question_titles:
            return self._question_titles
        self._build_services()
        form = self._forms_service.forms().get(formId=self.form_id).execute()  # type: ignore[union-attr]
        titles: Dict[str, str] = {}
        for item in form.get("items", []):
            question_item = item.get("questionItem", {})
            question = question_item.get("question", {})
            qid = question.get("questionId")
            if qid:
                titles[qid] = item.get("title") or qid
        self._question_titles = titles
        return titles

    def _iter_responses(self) -> List[Dict[str, Any]]:
        self._build_services()
        responses: List[Dict[str, Any]] = []
        request = self._forms_service.forms().responses().list(  # type: ignore[union-attr]
            formId=self.form_id, pageSize=100
        )
        while request is not None:
            payload = request.execute()
            responses.extend(payload.get("responses", []))
            request = self._forms_service.forms().responses().list_next(  # type: ignore[union-attr]
                previous_request=request, previous_response=payload
            )
        return responses

    def list_files(self) -> List[Dict[str, Any]]:
        """One metadata dict per uploaded file. No downloads, no OCR."""
        titles = self._load_question_titles()
        files: List[Dict[str, Any]] = []
        for response in self._iter_responses():
            response_id = response.get("responseId", "")
            create_time = response.get("createTime", "")
            answers = response.get("answers", {}) or {}
            for question_id, answer in answers.items():
                file_upload = answer.get("fileUploadAnswers")
                if not file_upload:
                    continue
                question_title = titles.get(question_id, question_id)
                for entry in file_upload.get("answers", []) or []:
                    file_id = entry.get("fileId")
                    if not file_id:
                        continue
                    files.append(
                        {
                            "doc_id": f"gform_{response_id}_{file_id}",
                            "title": entry.get("fileName") or question_title,
                            "response_id": response_id,
                            "create_time": create_time,
                            "question_id": question_id,
                            "question_title": question_title,
                            "file_id": file_id,
                            "filename": entry.get("fileName"),
                            "mime_type": entry.get("mimeType", ""),
                        }
                    )
        return files

    def _download(self, file_id: str, dest: Path) -> None:
        from googleapiclient.http import MediaIoBaseDownload

        self._build_services()
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = self._drive_service.files().get_media(fileId=file_id)  # type: ignore[union-attr]
        with io.FileIO(dest, mode="wb") as buffer:
            downloader = MediaIoBaseDownload(buffer, request, chunksize=1024 * 1024)
            done = False
            while not done:
                _status, done = downloader.next_chunk()

    def fetch_content(
        self,
        file_meta: Dict[str, Any],
        azure_endpoint: str,
        azure_key: str,
    ) -> Dict[str, Any]:
        """Download from Drive, OCR if it's a PDF, return an indexable doc."""
        response_id = file_meta["response_id"]
        file_id = file_meta["file_id"]
        filename = file_meta.get("filename") or f"{file_id}.pdf"
        local_path = self.download_dir / response_id / filename

        if not local_path.exists():
            self._download(file_id, local_path)

        mime_type = (file_meta.get("mime_type") or "").lower()
        is_pdf = (
            filename.lower().endswith(".pdf") or mime_type == "application/pdf"
        )

        content = ""
        if is_pdf:
            paragraphs = analyze_pdf_paragraphs(local_path, azure_endpoint, azure_key)
            content = "\n\n".join(paragraphs)

        return {
            "doc_id": file_meta["doc_id"],
            "title": file_meta["title"],
            "content": content,
            "keywords": [],
            "source": f"https://drive.google.com/file/d/{file_id}/view",
            "origin": "google_forms",
            "google_form_id": self.form_id,
            "google_response_id": response_id,
            "google_file_id": file_id,
            "google_question_title": file_meta.get("question_title"),
            "submitted_at": file_meta.get("create_time"),
            "filename": filename,
            "mime_type": mime_type,
        }
