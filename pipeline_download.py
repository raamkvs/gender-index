"""Download PDFs from URLs with per-link failure reporting."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import requests

from keyword_ocr_pipeline import ensure_output_dir

logger = logging.getLogger(__name__)


@dataclass
class FailedLink:
    url: str
    reason: str


@dataclass
class DetailedDownloadResult:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    files: List[Path] = field(default_factory=list)
    url_by_file: Dict[str, str] = field(default_factory=dict)
    failed_links: List[FailedLink] = field(default_factory=list)


def derive_filename(url: str, index: int) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if not name or name == "/":
        name = f"download_{index}.pdf"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def is_valid_pdf_file(file_path: Path) -> bool:
    """Check if a file is a valid PDF by examining magic bytes."""
    try:
        with file_path.open("rb") as f:
            header = f.read(1024)
            if not header:
                return False
            # PDF files must start with %PDF-
            if not header.startswith(b"%PDF-"):
                return False
            # Check for common HTML patterns (indicates webpage instead of PDF)
            html_markers = [b"<!DOCTYPE", b"<html", b"<HTML", b"<head", b"<body"]
            if any(marker in header for marker in html_markers):
                return False
            return True
    except Exception:
        return False


def stream_download_with_reason(url: str, dest: Path, timeout: int = 120) -> Tuple[bool, str]:
    try:
        with requests.get(url, stream=True, timeout=timeout) as response:
            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"
            
            # Check Content-Type header if available
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and "html" in content_type:
                logger.warning(f"URL {url} returned HTML content (Content-Type: {content_type})")
                return False, f"Non-PDF content type: {content_type}"

            with dest.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        file_handle.write(chunk)
            
            # Validate the downloaded file is actually a PDF
            if not is_valid_pdf_file(dest):
                logger.warning(f"Downloaded file {dest.name} is not a valid PDF (failed magic byte check)")
                dest.unlink()  # Remove invalid file
                return False, "Not a valid PDF file (HTML page or corrupted)"
            
            return True, ""
    except requests.Timeout:
        return False, "Request timed out"
    except requests.RequestException as exc:
        return False, str(exc)


def download_pdfs_detailed(
    output_dir: Path,
    links: List[str],
    timeout: int = 120,
) -> DetailedDownloadResult:
    result = DetailedDownloadResult()
    ensure_output_dir(output_dir)
    used_names: Dict[str, int] = {}

    for index, url in enumerate(links, start=1):
        url = url.strip()
        if not url:
            result.failed += 1
            result.failed_links.append(FailedLink(url=url, reason="Empty URL"))
            continue

        filename = derive_filename(url, index)
        if filename in used_names:
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            used_names[filename] += 1
            filename = f"{stem}_{used_names[filename]}{suffix}"
        else:
            used_names[filename] = 1

        destination = output_dir / filename
        if destination.exists():
            result.skipped += 1
            result.files.append(destination)
            result.url_by_file[destination.name] = url
            continue

        success, reason = stream_download_with_reason(url, destination, timeout=timeout)
        if success:
            result.downloaded += 1
            result.files.append(destination)
            result.url_by_file[destination.name] = url
        else:
            result.failed += 1
            result.failed_links.append(FailedLink(url=url, reason=reason or "Download failed"))
            if destination.exists():
                destination.unlink()

    return result
