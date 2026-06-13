"""Public download URL helpers for generated PDF reports."""
from __future__ import annotations

import os
from urllib.parse import quote

DEFAULT_API_BASE_URL = "https://gender-index-production.up.railway.app"


def build_report_download_url(chat_id_topic: str) -> str:
    """Build the public API URL that streams a generated report PDF."""
    base = os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL).strip().rstrip("/")
    encoded_chat_id = quote(chat_id_topic, safe="")
    return f"{base}/api/reports/{encoded_chat_id}/download"
