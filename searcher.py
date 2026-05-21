from __future__ import annotations

from typing import Any, Dict, List

from elasticsearch import Elasticsearch


class Searcher:
    def __init__(self, client: Elasticsearch, index_name: str) -> None:
        self.client = client
        self.index_name = index_name

    @staticmethod
    def _format_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for hit in hits:
            source = hit.get("_source", {})
            content = source.get("content", "")
            results.append(
                {
                    "doc_id": source.get("doc_id", ""),
                    "title": source.get("title", ""),
                    "keywords": source.get("keywords", []),
                    "score": hit.get("_score", 0.0),
                    "snippet": str(content)[:200],
                }
            )
        return results

    def search_by_keyword(self, keyword: str, size: int = 10) -> List[Dict[str, Any]]:
        response = self.client.search(
            index=self.index_name,
            size=size,
            query={"term": {"keywords": keyword}},
        )
        return self._format_hits(response["hits"]["hits"])

    def search_by_text(self, query: str, size: int = 10) -> List[Dict[str, Any]]:
        response = self.client.search(
            index=self.index_name,
            size=size,
            query={
                "multi_match": {
                    "query": query,
                    "fields": ["title^2", "content"],
                }
            },
        )
        return self._format_hits(response["hits"]["hits"])

    def search_combined(
        self, keyword: str, text_query: str, size: int = 10
    ) -> List[Dict[str, Any]]:
        response = self.client.search(
            index=self.index_name,
            size=size,
            query={
                "bool": {
                    "filter": [{"term": {"keywords": keyword}}],
                    "must": [
                        {
                            "multi_match": {
                                "query": text_query,
                                "fields": ["title^2", "content"],
                            }
                        }
                    ],
                }
            },
        )
        return self._format_hits(response["hits"]["hits"])


if __name__ == "__main__":
    client = Elasticsearch("http://localhost:9200")
    searcher = Searcher(client=client, index_name="documents")
    print(searcher.search_by_keyword("policy"))
