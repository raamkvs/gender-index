from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter

from schemas import KeywordStatus
from routers.common import build_services, hash_value, read_keywords

router = APIRouter(prefix="/keywords", tags=["keywords"])


@router.get("", response_model=List[KeywordStatus])
def get_keywords() -> List[KeywordStatus]:
    services = build_services()
    tracker = services["tracker"]
    keywords = read_keywords()

    response: List[KeywordStatus] = []
    for keyword in keywords:
        state_entry: Optional[dict] = tracker.state["keywords"].get(hash_value(keyword))
        response.append(
            KeywordStatus(
                value=keyword,
                is_indexed=state_entry is not None,
                indexed_at=state_entry.get("indexed_at") if state_entry else None,
            )
        )
    return response
