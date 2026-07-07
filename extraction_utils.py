"""Shared helpers for document extraction deduplication."""
from __future__ import annotations

from typing import Any, Dict, List, TypeVar
from urllib.parse import urlparse, urlunparse

T = TypeVar("T", bound=Dict[str, Any])


def normalize_source_url(url: str) -> str:
    """Normalize a source URL for duplicate detection."""
    url = url.strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))
    return normalized


def dedupe_extractions_by_filename(rows: List[T]) -> List[T]:
    """Keep the latest row per filename (by processed_at), sorted oldest-first."""
    by_filename: Dict[str, T] = {}
    for row in rows:
        filename = row.get("filename", "")
        existing = by_filename.get(filename)
        if not existing or row.get("processed_at", "") > existing.get("processed_at", ""):
            by_filename[filename] = row

    return sorted(by_filename.values(), key=lambda r: r.get("processed_at", ""))
