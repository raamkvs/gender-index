from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError as ESConnectionError
from elasticsearch.helpers import BulkIndexError, bulk
from rich.console import Console

from state_tracker import StateTracker


class Ingestor:
    def __init__(
        self,
        client: Elasticsearch,
        document_index: str,
        keyword_index: str,
        state_tracker: StateTracker,
    ) -> None:
        self.client = client
        self.document_index = document_index
        self.keyword_index = keyword_index
        self.state_tracker = state_tracker
        self.console = Console()
        self.err_console = Console(stderr=True)

    @staticmethod
    def _utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def index_new_documents(self, new_docs: List[Dict[str, Any]]) -> Dict[str, int]:
        if not new_docs:
            return {"sent": 0, "success": 0, "failed": 0}

        timestamp = self._utc_iso()
        actions = []
        for doc in new_docs:
            enriched = dict(doc)
            enriched["indexed_at"] = timestamp
            actions.append(
                {
                    "_index": self.document_index,
                    "_id": str(doc["doc_id"]),
                    "_source": enriched,
                }
            )

        sent = len(actions)
        try:
            success, errors = bulk(self.client, actions, raise_on_error=False)
        except ESConnectionError:
            self.err_console.print(
                "[red]Elasticsearch is unreachable. Start it with docker-compose up -d[/red]"
            )
            return {"sent": sent, "success": 0, "failed": sent}
        except BulkIndexError as exc:
            self.err_console.print(f"[red]Bulk indexing failed: {exc}[/red]")
            return {"sent": sent, "success": 0, "failed": sent}

        failed = len(errors)
        if failed:
            self.err_console.print(f"[yellow]{failed} document actions failed.[/yellow]")

        successful_docs = new_docs[:success]
        if successful_docs:
            self.state_tracker.mark_documents_indexed(successful_docs)

        return {"sent": sent, "success": success, "failed": failed}

    def index_new_keywords(self, new_keywords: List[str]) -> int:
        if not new_keywords:
            return 0

        timestamp = self._utc_iso()
        actions = [
            {
                "_index": self.keyword_index,
                "_id": keyword,
                "_source": {"keyword": keyword, "registered_at": timestamp},
            }
            for keyword in new_keywords
        ]

        try:
            success, errors = bulk(self.client, actions, raise_on_error=False)
        except ESConnectionError:
            self.err_console.print(
                "[red]Elasticsearch is unreachable. Start it with docker-compose up -d[/red]"
            )
            return 0
        except BulkIndexError as exc:
            self.err_console.print(f"[red]Bulk indexing failed: {exc}[/red]")
            return 0

        if errors:
            self.err_console.print(f"[yellow]{len(errors)} keyword actions failed.[/yellow]")

        successful_keywords = new_keywords[:success]
        if successful_keywords:
            self.state_tracker.mark_keywords_indexed(successful_keywords)

        return success


if __name__ == "__main__":
    from index_manager import IndexManager

    manager = IndexManager(
        es_host="http://localhost:9200",
        index_name="documents",
        keyword_index="keyword_registry",
    )
    tracker = StateTracker()
    ingestor = Ingestor(
        client=manager.client,
        document_index=manager.index_name,
        keyword_index=manager.keyword_index,
        state_tracker=tracker,
    )
    print(ingestor.index_new_keywords(["policy", "reform"]))
