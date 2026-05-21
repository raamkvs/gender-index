from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from index_manager import IndexManager
from ingestor import Ingestor
from state_tracker import StateTracker

load_dotenv()

REGISTRY_DIR = ROOT_DIR / "registries"
STATE_FILE = ROOT_DIR / "state" / "indexed_state.json"


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_keywords() -> List[str]:
    path = REGISTRY_DIR / "keywords.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [str(item) for item in payload]


def read_documents() -> List[Dict[str, Any]]:
    path = REGISTRY_DIR / "documents.json"
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload


def build_services() -> Dict[str, Any]:
    es_host = os.getenv("ES_HOST", "http://localhost:9200")
    index_name = os.getenv("ES_INDEX", "documents")
    keyword_index = os.getenv("ES_KEYWORD_INDEX", "keyword_registry")

    tracker = StateTracker(str(STATE_FILE))
    manager = IndexManager(es_host=es_host, index_name=index_name, keyword_index=keyword_index)
    ingestor = Ingestor(
        client=manager.client,
        document_index=index_name,
        keyword_index=keyword_index,
        state_tracker=tracker,
    )
    return {
        "tracker": tracker,
        "manager": manager,
        "ingestor": ingestor,
    }
