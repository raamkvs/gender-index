from __future__ import annotations

from typing import Any, Dict

from elasticsearch import Elasticsearch


class IndexManager:
    def __init__(self, es_host: str, index_name: str, keyword_index: str) -> None:
        self.client = Elasticsearch(es_host)
        self.index_name = index_name
        self.keyword_index = keyword_index

    @staticmethod
    def _documents_mapping() -> Dict[str, Any]:
        return {
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "english"},
                    "content": {"type": "text", "analyzer": "english"},
                    "keywords": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "indexed_at": {"type": "date"},
                }
            }
        }

    @staticmethod
    def _keywords_mapping() -> Dict[str, Any]:
        return {
            "mappings": {
                "properties": {
                    "keyword": {"type": "keyword"},
                    "registered_at": {"type": "date"},
                }
            }
        }

    def create_indices(self) -> None:
        if not self.client.indices.exists(index=self.index_name):
            self.client.indices.create(
                index=self.index_name,
                mappings=self._documents_mapping()["mappings"],
            )

        if not self.client.indices.exists(index=self.keyword_index):
            self.client.indices.create(
                index=self.keyword_index,
                mappings=self._keywords_mapping()["mappings"],
            )

    def delete_indices(self) -> None:
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        if self.client.indices.exists(index=self.keyword_index):
            self.client.indices.delete(index=self.keyword_index)

    def health_check(self) -> bool:
        return bool(self.client.ping())


if __name__ == "__main__":
    manager = IndexManager(
        es_host="http://localhost:9200",
        index_name="documents",
        keyword_index="keyword_registry",
    )
    print("Elasticsearch reachable:", manager.health_check())
