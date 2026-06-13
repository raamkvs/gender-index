"""Vercel Blob upload and download client."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Literal
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_VERCEL_BLOB_API_BASE_URL = "https://blob.vercel-storage.com"
_BLOB_API_VERSION = "10"


class BlobConfigError(RuntimeError):
    pass


def _guess_mime_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    return "application/octet-stream"


def put_blob_bytes(
    pathname: str,
    data: bytes,
    *,
    token: str,
    access: Literal["public", "private"] = "public",
    content_type: str | None = None,
    add_random_suffix: bool = True,
    timeout: int = 120,
) -> str:
    """Upload bytes to Vercel Blob and return the blob URL."""
    headers = {
        "access": access,
        "authorization": f"Bearer {token}",
        "x-api-version": _BLOB_API_VERSION,
        "x-content-type": content_type or _guess_mime_type(pathname),
        "x-cache-control-max-age": "31536000",
    }
    if add_random_suffix:
        headers["x-add-random-suffix"] = "1"

    response = requests.put(
        f"{_VERCEL_BLOB_API_BASE_URL}/?pathname={quote(pathname, safe='')}",
        headers=headers,
        data=data,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Blob upload failed (status {response.status_code}): {response.text}"
        )

    payload = response.json()
    url = payload.get("url")
    if not url:
        raise RuntimeError(f"Blob upload returned no URL: {payload!r}")
    return url


def download_blob_bytes(blob_url: str, *, token: str, timeout: int = 120) -> bytes:
    """Download blob content using authenticated access (works for private stores)."""
    response = requests.get(
        blob_url,
        headers={"authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content


class BlobClient:
    def __init__(self, token: str) -> None:
        self.token = token

    @classmethod
    def from_env(cls) -> "BlobClient":
        token = os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
        if not token:
            raise BlobConfigError("BLOB_READ_WRITE_TOKEN not configured")
        return cls(token)

    def upload_file(self, file_path: Path, filename: str) -> str:
        """Upload a file to Vercel Blob and return the public URL."""
        with file_path.open("rb") as fh:
            return put_blob_bytes(
                filename,
                fh.read(),
                token=self.token,
                access="public",
            )

    def download_file(self, blob_url: str, dest_path: Path, timeout: int = 120) -> Path:
        """Download a file from a Vercel Blob public URL to a local path."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(blob_url, stream=True, timeout=timeout)
        response.raise_for_status()
        with dest_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fh.write(chunk)
        return dest_path

    def upload_pdfs(self, pdf_paths: List[Path]) -> List[Dict[str, str]]:
        """Upload multiple PDFs to Blob. Returns list of {url, filename}."""
        results = []
        for pdf_path in pdf_paths:
            url = self.upload_file(pdf_path, pdf_path.name)
            results.append({"url": url, "filename": pdf_path.name})
        return results


class DocGeneratedBlobClient:
    """Client for uploading generated PDF reports to dedicated docs-generated blob store."""

    def __init__(self, token: str, store_id: str, access: str = "private") -> None:
        self.token = token
        self.store_id = store_id
        self.access = access if access in ("public", "private") else "private"

    @classmethod
    def from_env(cls) -> "DocGeneratedBlobClient":
        """Initialize from environment variables for docs-generated blob store."""
        token = os.getenv("BLOB_READ_WRITE_TOKEN__DOC_GENERATED", "").strip()
        store_id = os.getenv("BLOB_STORE_ID_DOC_GENERATED", "").strip()
        access = os.getenv("BLOB_DOC_GENERATED_ACCESS", "private").strip().lower()
        if not token:
            raise BlobConfigError("BLOB_READ_WRITE_TOKEN__DOC_GENERATED not configured")
        if not store_id:
            raise BlobConfigError("BLOB_STORE_ID_DOC_GENERATED not configured")
        return cls(token, store_id, access=access)

    def upload_pdf_report(self, pdf_path: Path, chat_id_topic: str) -> str:
        """
        Upload a generated PDF report to the docs-generated blob store.

        Returns:
            The blob URL (private or public depending on store configuration)
        """
        filename = f"{chat_id_topic}-report.pdf"

        with pdf_path.open("rb") as fh:
            url = put_blob_bytes(
                filename,
                fh.read(),
                token=self.token,
                access=self.access,  # type: ignore[arg-type]
                content_type="application/pdf",
            )

        logger.info("Uploaded PDF report to docs-generated blob (%s): %s", self.access, url)
        return url

    def download_pdf_report(self, blob_url: str) -> bytes:
        """Download a report PDF from blob storage using authenticated access."""
        return download_blob_bytes(blob_url, token=self.token)
