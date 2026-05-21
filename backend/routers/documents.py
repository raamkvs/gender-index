from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from schemas import DocumentStatus
from routers.common import build_services, hash_value, read_documents

router = APIRouter(prefix="/documents", tags=["documents"])


def _to_status_list() -> List[DocumentStatus]:
    services = build_services()
    tracker = services["tracker"]
    documents = read_documents()

    response: List[DocumentStatus] = []
    for doc in documents:
        doc_id = str(doc.get("doc_id", ""))
        state_entry: Optional[dict] = tracker.state["documents"].get(hash_value(doc_id))
        response.append(
            DocumentStatus(
                doc_id=doc_id,
                title=str(doc.get("title", "")),
                keywords=[str(k) for k in doc.get("keywords", [])],
                source=str(doc.get("source", "")),
                is_indexed=state_entry is not None,
                indexed_at=state_entry.get("indexed_at") if state_entry else None,
            )
        )
    return response


@router.get("", response_model=List[DocumentStatus])
def get_documents() -> List[DocumentStatus]:
    return _to_status_list()


@router.post("/{doc_id}/reindex", response_model=DocumentStatus)
def reindex_document(doc_id: str) -> DocumentStatus:
    services = build_services()
    tracker = services["tracker"]
    ingestor = services["ingestor"]
    manager = services["manager"]
    documents = read_documents()

    if not manager.health_check():
        raise HTTPException(
            status_code=503,
            detail="Elasticsearch is unavailable at ES_HOST. Start Elasticsearch and retry.",
        )

    target = next((doc for doc in documents if str(doc.get("doc_id", "")) == doc_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Document not found")

    tracker.remove_document(doc_id)
    result = ingestor.index_new_documents([target])
    if result["success"] <= 0:
        raise HTTPException(
            status_code=503,
            detail="Failed to index document. Elasticsearch may be unavailable.",
        )

    state_entry = tracker.state["documents"].get(hash_value(doc_id))
    return DocumentStatus(
        doc_id=str(target.get("doc_id", "")),
        title=str(target.get("title", "")),
        keywords=[str(k) for k in target.get("keywords", [])],
        source=str(target.get("source", "")),
        is_indexed=True,
        indexed_at=state_entry.get("indexed_at") if state_entry else None,
    )
