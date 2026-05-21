from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class StateTracker:
    def __init__(self, state_file: str = "state/indexed_state.json") -> None:
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Dict[str, Dict[str, str]]] = self._load_state()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _default_state(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        return {"keywords": {}, "documents": {}}

    def _load_state(self) -> Dict[str, Dict[str, Dict[str, str]]]:
        if not self.state_file.exists():
            return self._default_state()

        with self.state_file.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)

        keywords = loaded.get("keywords", {})
        documents = loaded.get("documents", {})
        return {"keywords": keywords, "documents": documents}

    def _save_state(self) -> None:
        tmp_file = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        with tmp_file.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2, ensure_ascii=True)
        os.replace(tmp_file, self.state_file)

    def get_new_keywords(self, all_keywords: List[str]) -> List[str]:
        return [
            keyword
            for keyword in all_keywords
            if self._hash(keyword) not in self.state["keywords"]
        ]

    def get_new_documents(self, all_docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        new_docs: List[Dict[str, Any]] = []
        for doc in all_docs:
            doc_id = str(doc.get("doc_id", ""))
            if not doc_id:
                continue
            doc_hash = self._hash(doc_id)
            if doc_hash not in self.state["documents"]:
                new_docs.append(doc)
        return new_docs

    def mark_keywords_indexed(self, keywords: List[str]) -> None:
        indexed_at = self._utc_iso()
        for keyword in keywords:
            self.state["keywords"][self._hash(keyword)] = {
                "value": keyword,
                "indexed_at": indexed_at,
            }
        self._save_state()

    def mark_documents_indexed(self, docs: List[Dict[str, Any]]) -> None:
        indexed_at = self._utc_iso()
        for doc in docs:
            doc_id = str(doc["doc_id"])
            self.state["documents"][self._hash(doc_id)] = {
                "doc_id": doc_id,
                "indexed_at": indexed_at,
            }
        self._save_state()

    def clear(self) -> None:
        self.state = self._default_state()
        self._save_state()

    def remove_document(self, doc_id: str) -> bool:
        doc_hash = self._hash(doc_id)
        removed = doc_hash in self.state["documents"]
        if removed:
            del self.state["documents"][doc_hash]
            self._save_state()
        return removed

    def get_stats(
        self,
        total_keywords: Optional[int] = None,
        total_documents: Optional[int] = None,
    ) -> Dict[str, int]:
        return {
            "total_keywords": total_keywords if total_keywords is not None else 0,
            "indexed_keywords": len(self.state["keywords"]),
            "total_documents": total_documents if total_documents is not None else 0,
            "indexed_documents": len(self.state["documents"]),
        }


if __name__ == "__main__":
    tracker = StateTracker()
    sample_keywords = ["policy", "gender", "ethics"]
    sample_docs = [{"doc_id": "doc_001"}, {"doc_id": "doc_002"}]

    print("New keywords:", tracker.get_new_keywords(sample_keywords))
    print("New documents:", [d["doc_id"] for d in tracker.get_new_documents(sample_docs)])
