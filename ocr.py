"""Azure Document Intelligence helpers, reusable across sources."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Tuple

import requests

OCR_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2


def get_azure_settings() -> Tuple[str, str]:
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "").strip()
    key = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY", "").strip()
    if not endpoint or not key:
        raise RuntimeError(
            "Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY environment variables."
        )
    return endpoint.rstrip("/"), key


def analyze_pdf_paragraphs(pdf_path: Path, endpoint: str, key: str) -> List[str]:
    """Run Azure prebuilt-read OCR on a PDF and return paragraph strings.

    Falls back to per-line content if the model does not return paragraphs.
    """
    analyze_urls = [
        f"{endpoint}/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-02-29-preview",
        f"{endpoint}/formrecognizer/documentModels/prebuilt-read:analyze?api-version=2023-07-31",
    ]
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/octet-stream",
    }

    start_response = None
    last_error: Exception | None = None
    for analyze_url in analyze_urls:
        try:
            with pdf_path.open("rb") as file_handle:
                candidate_response = requests.post(
                    analyze_url, headers=headers, data=file_handle, timeout=60
                )
            if candidate_response.status_code in (404, 405):
                continue
            candidate_response.raise_for_status()
            start_response = candidate_response
            break
        except requests.RequestException as exc:
            last_error = exc
            continue

    if start_response is None:
        if last_error:
            raise last_error
        raise RuntimeError("No compatible analyze endpoint found for this resource.")

    operation_url = start_response.headers.get("Operation-Location")
    if not operation_url:
        raise RuntimeError("Azure response missing Operation-Location header.")

    poll_headers = {"Ocp-Apim-Subscription-Key": key}
    started_at = time.time()

    while True:
        poll_response = requests.get(operation_url, headers=poll_headers, timeout=30)
        poll_response.raise_for_status()
        payload = poll_response.json()
        status = payload.get("status", "").lower()

        if status == "succeeded":
            analyze_result = payload.get("analyzeResult", {})
            paragraphs = analyze_result.get("paragraphs", [])
            paragraph_texts = [
                str(item.get("content", "")).strip()
                for item in paragraphs
                if item.get("content")
            ]
            if paragraph_texts:
                return paragraph_texts

            pages = analyze_result.get("pages", [])
            lines_fallback: List[str] = []
            for page in pages:
                for line in page.get("lines", []):
                    content = str(line.get("content", "")).strip()
                    if content:
                        lines_fallback.append(content)
            return lines_fallback

        if status == "failed":
            raise RuntimeError(f"OCR failed for {pdf_path.name}: {json.dumps(payload)}")

        if time.time() - started_at > OCR_TIMEOUT_SECONDS:
            raise TimeoutError(f"OCR timed out for {pdf_path.name}")

        time.sleep(POLL_INTERVAL_SECONDS)
