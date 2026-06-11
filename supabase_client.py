"""Supabase client for Gender Reviewer pipeline state management."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SupabaseConfigError(RuntimeError):
    pass


class SupabaseClient:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    @classmethod
    def from_env(cls) -> "SupabaseClient":
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()
        if not url or not key:
            raise SupabaseConfigError("SUPABASE_URL or SUPABASE_KEY not configured")
        return cls(url, key)

    # ------------------------------------------------------------------
    # document_extractions
    # ------------------------------------------------------------------

    def store_document_extraction(
        self,
        chat_id_topic: str,
        filename: str,
        ai_extraction: str,
        source_url: Optional[str] = None,
        blob_url: Optional[str] = None,
        keywords: Optional[List[str]] = None,
    ) -> str:
        """Store one document's AI extraction. Returns the new row ID."""
        result = (
            self._client.table("document_extractions")
            .insert(
                {
                    "chat_id_topic": chat_id_topic,
                    "filename": filename,
                    "ai_extraction": ai_extraction,
                    "source_url": source_url or None,
                    "blob_url": blob_url or None,
                    "keywords": keywords or [],
                }
            )
            .execute()
        )
        return result.data[0]["id"]

    def get_all_extractions(self, chat_id_topic: str) -> List[Dict[str, Any]]:
        """Get all document extraction rows for a chat_id_topic, oldest first."""
        result = (
            self._client.table("document_extractions")
            .select("*")
            .eq("chat_id_topic", chat_id_topic)
            .order("processed_at")
            .execute()
        )
        return result.data or []

    def get_all_extraction_texts(self, chat_id_topic: str) -> List[str]:
        """Get just the ai_extraction text for every document under a chat_id_topic."""
        rows = self.get_all_extractions(chat_id_topic)
        return [r["ai_extraction"] for r in rows]

    # ------------------------------------------------------------------
    # pipeline_results (metadata)
    # ------------------------------------------------------------------

    def get_pipeline_metadata(self, chat_id_topic: str) -> Optional[Dict[str, Any]]:
        """Fetch the pipeline_results row for a chat_id_topic. Returns None if absent."""
        result = (
            self._client.table("pipeline_results")
            .select("*")
            .eq("chat_id_topic", chat_id_topic)
            .maybe_single()
            .execute()
        )
        if result is None:
            return None
        return result.data  # None when no matching row

    def upsert_pipeline_metadata(
        self,
        chat_id_topic: str,
        undownloadable_links: Optional[List[Dict[str, str]]] = None,
        blob_links: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """Create or update pipeline_results, merging new link lists with existing ones."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_pipeline_metadata(chat_id_topic)

        if existing:
            merged_undl = (existing.get("undownloadable_links") or []) + (
                undownloadable_links or []
            )
            merged_blob = (existing.get("blob_links") or []) + (blob_links or [])
            self._client.table("pipeline_results").update(
                {
                    "undownloadable_links": merged_undl,
                    "blob_links": merged_blob,
                    "last_run_at": now,
                    "updated_at": now,
                }
            ).eq("chat_id_topic", chat_id_topic).execute()
        else:
            self._client.table("pipeline_results").insert(
                {
                    "chat_id_topic": chat_id_topic,
                    "undownloadable_links": undownloadable_links or [],
                    "blob_links": blob_links or [],
                    "last_run_at": now,
                    "updated_at": now,
                }
            ).execute()

    # ------------------------------------------------------------------
    # uploads
    # ------------------------------------------------------------------

    def get_unprocessed_uploads(self, chat_id_topic: str) -> List[Dict[str, Any]]:
        """Get uploads WHERE chat_id_topic = X AND processed = false."""
        result = (
            self._client.table("uploads")
            .select("*")
            .eq("chat_id_topic", chat_id_topic)
            .eq("processed", False)
            .execute()
        )
        return result.data or []

    def mark_uploads_processed(self, upload_ids: List[str]) -> None:
        """Set processed = true for the given upload IDs."""
        if not upload_ids:
            return
        self._client.table("uploads").update({"processed": True}).in_(
            "id", upload_ids
        ).execute()

    def create_upload_record(
        self,
        chat_id_topic: str,
        blob_url: str,
        filename: str,
    ) -> str:
        """Insert an upload record with processed=false. Returns the new row ID."""
        result = (
            self._client.table("uploads")
            .insert(
                {
                    "chat_id_topic": chat_id_topic,
                    "blob_url": blob_url,
                    "filename": filename,
                    "processed": False,
                }
            )
            .execute()
        )
        return result.data[0]["id"]
