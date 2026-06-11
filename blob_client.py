"""Vercel Blob upload and download client."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)


class BlobConfigError(RuntimeError):
    pass


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
        import vercel_blob

        with file_path.open("rb") as fh:
            result = vercel_blob.put(filename, fh.read())
        return result.url

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
