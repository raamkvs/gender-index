from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from index_manager import IndexManager
from ingestor import Ingestor
from state_tracker import StateTracker


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture()
def setup_env(tmp_path: Path) -> Dict[str, Any]:
    state_file = tmp_path / "test_indexed_state.json"
    tracker = StateTracker(str(state_file))
    manager = IndexManager(
        es_host="http://localhost:9200",
        index_name="documents_test",
        keyword_index="keyword_registry_test",
    )
    if not manager.health_check():
        pytest.skip("Elasticsearch is not running at http://localhost:9200")
    manager.delete_indices()
    manager.create_indices()
    ingestor = Ingestor(
        client=manager.client,
        document_index="documents_test",
        keyword_index="keyword_registry_test",
        state_tracker=tracker,
    )
    yield {"tracker": tracker, "manager": manager, "ingestor": ingestor, "state_file": state_file}
    manager.delete_indices()


def _make_docs(count: int, offset: int = 1) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for i in range(offset, offset + count):
        docs.append(
            {
                "doc_id": f"doc_{i:03d}",
                "title": f"Title {i}",
                "content": f"Document content {i}",
                "keywords": ["policy"],
                "source": f"source_{i}.pdf",
            }
        )
    return docs


def test_state_tracker_keyword_diff_detection(setup_env: Dict[str, Any]) -> None:
    tracker: StateTracker = setup_env["tracker"]
    ingestor: Ingestor = setup_env["ingestor"]

    initial_keywords = ["policy", "gender", "reform"]
    new_keywords = tracker.get_new_keywords(initial_keywords)
    assert len(new_keywords) == 3
    assert ingestor.index_new_keywords(new_keywords) == 3

    expanded_keywords = initial_keywords + ["ethics", "compliance"]
    new_keywords_2 = tracker.get_new_keywords(expanded_keywords)
    assert new_keywords_2 == ["ethics", "compliance"]
    assert ingestor.index_new_keywords(new_keywords_2) == 2


def test_state_tracker_document_diff(setup_env: Dict[str, Any]) -> None:
    tracker: StateTracker = setup_env["tracker"]
    ingestor: Ingestor = setup_env["ingestor"]

    docs_5 = _make_docs(5)
    assert len(tracker.get_new_documents(docs_5)) == 5
    result_5 = ingestor.index_new_documents(tracker.get_new_documents(docs_5))
    assert result_5["success"] == 5

    docs_8 = docs_5 + _make_docs(3, offset=6)
    next_new = tracker.get_new_documents(docs_8)
    assert len(next_new) == 3
    result_3 = ingestor.index_new_documents(next_new)
    assert result_3["success"] == 3
    assert len(tracker.state["documents"]) == 8


def test_noop_run(setup_env: Dict[str, Any]) -> None:
    tracker: StateTracker = setup_env["tracker"]
    ingestor: Ingestor = setup_env["ingestor"]
    docs = _make_docs(2)
    keywords = ["policy", "gender"]

    ingestor.index_new_keywords(tracker.get_new_keywords(keywords))
    ingestor.index_new_documents(tracker.get_new_documents(docs))

    assert tracker.get_new_keywords(keywords) == []
    assert tracker.get_new_documents(docs) == []
    assert ingestor.index_new_keywords([]) == 0
    result = ingestor.index_new_documents([])
    assert result == {"sent": 0, "success": 0, "failed": 0}


def test_reindex_single_doc(setup_env: Dict[str, Any]) -> None:
    tracker: StateTracker = setup_env["tracker"]
    ingestor: Ingestor = setup_env["ingestor"]
    docs = _make_docs(2)
    ingestor.index_new_documents(tracker.get_new_documents(docs))

    tracker.remove_document("doc_001")
    assert _hash("doc_001") not in tracker.state["documents"]

    resend = [doc for doc in docs if doc["doc_id"] == "doc_001"]
    result = ingestor.index_new_documents(resend)
    assert result["sent"] == 1
    assert result["success"] == 1


def test_state_file_integrity(setup_env: Dict[str, Any]) -> None:
    tracker: StateTracker = setup_env["tracker"]
    ingestor: Ingestor = setup_env["ingestor"]
    state_file: Path = setup_env["state_file"]
    keywords = ["policy", "ethics"]
    docs = _make_docs(2)

    ingestor.index_new_keywords(tracker.get_new_keywords(keywords))
    ingestor.index_new_documents(tracker.get_new_documents(docs))

    with state_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    for keyword in keywords:
        assert _hash(keyword) in data["keywords"]
    for doc in docs:
        assert _hash(doc["doc_id"]) in data["documents"]
