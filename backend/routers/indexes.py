from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from ..schemas import IndexInfo
from .common import build_services

router = APIRouter(prefix="/indexes", tags=["indexes"])


@router.get("", response_model=List[IndexInfo])
def list_indexes() -> List[IndexInfo]:
    manager = build_services()["manager"]
    if not manager.health_check():
        raise HTTPException(
            status_code=503,
            detail="Elasticsearch is unavailable at ES_HOST. Start Elasticsearch and retry.",
        )
    rows = manager.client.cat.indices(format="json")
    results: List[IndexInfo] = []
    for row in rows:
        status = str(row.get("health", "red"))
        status = status if status in {"green", "yellow", "red"} else "red"
        count_value = row.get("docs.count", 0)
        try:
            doc_count = int(count_value)
        except (TypeError, ValueError):
            doc_count = 0
        results.append(
            IndexInfo(
                name=str(row.get("index", "")),
                doc_count=doc_count,
                status=status,
            )
        )
    return results
