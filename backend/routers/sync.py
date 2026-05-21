from __future__ import annotations

import json
from typing import Generator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from routers.common import build_services, read_documents, read_keywords

router = APIRouter(prefix="/sync", tags=["sync"])


def _emit(line: str, event_type: str) -> str:
    return f"data: {json.dumps({'line': line, 'type': event_type})}\n\n"


def _run_sync(reindex_all: bool) -> Generator[str, None, None]:
    services = build_services()
    tracker = services["tracker"]
    manager = services["manager"]
    ingestor = services["ingestor"]

    if not manager.health_check():
        yield _emit(
            "Elasticsearch is unavailable at ES_HOST. Start Elasticsearch and retry.",
            "error",
        )
        return

    if reindex_all:
        yield _emit("Clearing state and rebuilding indexes...", "new")
        tracker.clear()
        manager.delete_indices()
        manager.create_indices()
        yield _emit("State cleared, indices recreated.", "ok")

    keywords = read_keywords()
    documents = read_documents()

    new_keywords = tracker.get_new_keywords(keywords)
    new_documents = tracker.get_new_documents(documents)

    yield _emit(
        f"Keywords: {len(keywords)} total | {len(keywords) - len(new_keywords)} indexed | {len(new_keywords)} new",
        "new" if new_keywords else "skip",
    )
    if new_keywords:
        count = ingestor.index_new_keywords(new_keywords)
        if count == 0 and len(new_keywords) > 0:
            yield _emit("Failed to index new keywords (Elasticsearch unavailable/error).", "error")
            return
        yield _emit(f"Indexed {count} new keywords.", "ok")
    else:
        yield _emit("No new keywords to index.", "skip")

    yield _emit(
        f"Documents: {len(documents)} total | {len(documents) - len(new_documents)} indexed | {len(new_documents)} new",
        "new" if new_documents else "skip",
    )
    if new_documents:
        result = ingestor.index_new_documents(new_documents)
        if result["success"] == 0 and result["sent"] > 0:
            yield _emit("Failed to index documents (Elasticsearch unavailable/error).", "error")
            return
        if result["failed"] > 0:
            yield _emit(
                f"Indexed {result['success']} documents, {result['failed']} failed.",
                "error",
            )
        else:
            yield _emit(f"Indexed {result['success']} new documents.", "ok")
    else:
        yield _emit("No new documents to index.", "skip")

    yield _emit("Sync complete.", "ok")


@router.get("")
def run_sync_stream() -> StreamingResponse:
    return StreamingResponse(_run_sync(reindex_all=False), media_type="text/event-stream")


@router.get("/all")
def run_sync_all_stream() -> StreamingResponse:
    return StreamingResponse(_run_sync(reindex_all=True), media_type="text/event-stream")
