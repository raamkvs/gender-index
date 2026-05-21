from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from rich.console import Console
from rich.table import Table

from index_manager import IndexManager
from ingestor import Ingestor
from ocr import get_azure_settings
from searcher import Searcher
from sources.airtable_source import AirtableConfigError, AirtableSource
from sources.google_forms_source import GoogleFormsConfigError, GoogleFormsSource
from state_tracker import StateTracker

_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")
load_dotenv(_HERE / ".env.local", override=False)

import os


def _read_keywords(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("keywords.json must contain a list of strings")
    return [str(item) for item in data]


def _read_documents(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("documents.json must contain a list of objects")
    for doc in data:
        if "doc_id" not in doc:
            raise ValueError("Every document must include doc_id")
    return data


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Incremental Document Indexer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")
    subparsers.add_parser("sync")
    subparsers.add_parser("status")

    reindex_parser = subparsers.add_parser("reindex")
    group = reindex_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--doc-id")
    group.add_argument("--all", action="store_true")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--keyword")
    search_parser.add_argument("--text")
    search_parser.add_argument("--size", type=int, default=10)
    return parser


def _build_components() -> Dict[str, Any]:
    es_host = os.getenv("ES_HOST", "http://localhost:9200")
    index_name = os.getenv("ES_INDEX", "documents")
    keyword_index = os.getenv("ES_KEYWORD_INDEX", "keyword_registry")

    state_tracker = StateTracker("state/indexed_state.json")
    manager = IndexManager(es_host=es_host, index_name=index_name, keyword_index=keyword_index)
    ingestor = Ingestor(
        client=manager.client,
        document_index=index_name,
        keyword_index=keyword_index,
        state_tracker=state_tracker,
    )
    searcher = Searcher(client=manager.client, index_name=index_name)
    return {
        "tracker": state_tracker,
        "manager": manager,
        "ingestor": ingestor,
        "searcher": searcher,
    }


def _render_search(console: Console, results: List[Dict[str, Any]]) -> None:
    table = Table(title="Search Results")
    table.add_column("doc_id")
    table.add_column("title")
    table.add_column("keywords")
    table.add_column("score")
    table.add_column("snippet")
    for item in results:
        table.add_row(
            str(item["doc_id"]),
            str(item["title"]),
            ", ".join(item["keywords"]),
            f"{float(item['score']):.3f}",
            str(item["snippet"]),
        )
    console.print(table)


def command_init(console: Console, manager: IndexManager) -> int:
    manager.create_indices()
    console.print("[green]Indices initialized.[/green]")
    return 0


def _load_airtable_source(console: Console) -> Optional[AirtableSource]:
    try:
        return AirtableSource.from_env()
    except AirtableConfigError as exc:
        console.print(f"[dim]Airtable source disabled: {exc}[/dim]")
        return None


def _list_airtable_attachments(
    source: Optional[AirtableSource], console: Console
) -> List[Dict[str, Any]]:
    if source is None:
        return []
    try:
        return source.list_attachments()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Airtable list failed:[/red] {exc}")
        return []


def _load_gforms_source(console: Console) -> Optional[GoogleFormsSource]:
    try:
        return GoogleFormsSource.from_env()
    except GoogleFormsConfigError as exc:
        console.print(f"[dim]Google Forms source disabled: {exc}[/dim]")
        return None


def _list_gforms_files(
    source: Optional[GoogleFormsSource], console: Console
) -> List[Dict[str, Any]]:
    if source is None:
        return []
    try:
        return source.list_files()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Google Forms list failed:[/red] {exc}")
        return []


def command_sync(console: Console, ingestor: Ingestor, tracker: StateTracker) -> int:
    keywords = _read_keywords(Path("registries/keywords.json"))
    json_documents = _read_documents(Path("registries/documents.json"))

    airtable_source = _load_airtable_source(console)
    airtable_metas = _list_airtable_attachments(airtable_source, console)
    gforms_source = _load_gforms_source(console)
    gforms_metas = _list_gforms_files(gforms_source, console)

    new_keywords = tracker.get_new_keywords(keywords)
    indexed_kw = len(keywords) - len(new_keywords)
    console.print(
        f"Keywords  -> {len(keywords)} total | {indexed_kw} already indexed | {len(new_keywords)} new",
        end="",
    )
    if new_keywords:
        count = ingestor.index_new_keywords(new_keywords)
        console.print(f" -> indexing... [green]✓[/green] ({count} indexed)")
    else:
        console.print(" -> no-op [green]✓[/green]")

    airtable_stubs = [
        {"doc_id": meta["doc_id"], "_airtable_meta": meta} for meta in airtable_metas
    ]
    gforms_stubs = [
        {"doc_id": meta["doc_id"], "_gforms_meta": meta} for meta in gforms_metas
    ]
    combined_stubs: List[Dict[str, Any]] = (
        list(json_documents) + airtable_stubs + gforms_stubs
    )
    total_docs = len(combined_stubs)
    new_stubs = tracker.get_new_documents(combined_stubs)
    indexed_docs = total_docs - len(new_stubs)

    console.print(
        f"Documents -> {total_docs} total ({len(json_documents)} json + "
        f"{len(airtable_metas)} airtable + {len(gforms_metas)} gforms) | "
        f"{indexed_docs} already indexed | {len(new_stubs)} new"
    )

    if not new_stubs:
        console.print("           -> no-op [green]✓[/green]")
        return 0

    needs_ocr = any(
        stub.get("_airtable_meta") or stub.get("_gforms_meta") for stub in new_stubs
    )
    azure_endpoint = ""
    azure_key = ""
    if needs_ocr:
        try:
            azure_endpoint, azure_key = get_azure_settings()
        except RuntimeError as exc:
            console.print(
                f"[red]{exc}[/red] Remote attachments will be skipped this run."
            )

    docs_to_index: List[Dict[str, Any]] = []
    for stub in new_stubs:
        airtable_meta = stub.get("_airtable_meta")
        gforms_meta = stub.get("_gforms_meta")
        if airtable_meta is None and gforms_meta is None:
            docs_to_index.append(stub)
            continue
        if not azure_endpoint:
            continue
        if airtable_meta is not None and airtable_source is not None:
            filename = airtable_meta.get("filename") or airtable_meta["attachment_id"]
            try:
                console.print(f"  [cyan]OCR airtable[/cyan] {filename}")
                doc = airtable_source.fetch_content(
                    airtable_meta, azure_endpoint, azure_key
                )
                docs_to_index.append(doc)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]FAIL[/red] {filename}: {exc}")
        elif gforms_meta is not None and gforms_source is not None:
            filename = gforms_meta.get("filename") or gforms_meta["file_id"]
            try:
                console.print(f"  [cyan]OCR gforms[/cyan]  {filename}")
                doc = gforms_source.fetch_content(
                    gforms_meta, azure_endpoint, azure_key
                )
                docs_to_index.append(doc)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]FAIL[/red] {filename}: {exc}")

    if docs_to_index:
        result = ingestor.index_new_documents(docs_to_index)
        console.print(
            f"           -> indexed [green]✓[/green] "
            f"({result['success']} success, {result['failed']} failed)"
        )
    else:
        console.print("           -> nothing indexed [yellow]![/yellow]")
    return 0


def command_status(console: Console, manager: IndexManager, tracker: StateTracker) -> int:
    keywords = _read_keywords(Path("registries/keywords.json"))
    json_documents = _read_documents(Path("registries/documents.json"))
    airtable_source = _load_airtable_source(console)
    airtable_metas = _list_airtable_attachments(airtable_source, console)
    gforms_source = _load_gforms_source(console)
    gforms_metas = _list_gforms_files(gforms_source, console)

    total_documents = len(json_documents) + len(airtable_metas) + len(gforms_metas)
    stats = tracker.get_stats(
        total_keywords=len(keywords), total_documents=total_documents
    )

    table = Table(title="Indexer Status")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in stats.items():
        table.add_row(key, str(value))
    table.add_row("json_documents", str(len(json_documents)))
    table.add_row("airtable_attachments", str(len(airtable_metas)))
    table.add_row("gforms_files", str(len(gforms_metas)))
    table.add_row("es_healthy", str(manager.health_check()))
    console.print(table)
    return 0


def command_reindex(
    console: Console,
    manager: IndexManager,
    ingestor: Ingestor,
    tracker: StateTracker,
    doc_id: str,
    all_flag: bool,
) -> int:
    if all_flag:
        tracker.clear()
        manager.delete_indices()
        manager.create_indices()
        console.print("[yellow]State cleared and indices recreated.[/yellow]")
        return command_sync(console, ingestor, tracker)

    if doc_id.startswith("airtable_"):
        airtable_source = _load_airtable_source(console)
        if airtable_source is None:
            console.print("[red]Airtable source not configured[/red]")
            return 1
        target_meta = next(
            (m for m in airtable_source.list_attachments() if m["doc_id"] == doc_id),
            None,
        )
        if not target_meta:
            console.print(f"[red]Airtable attachment not found for doc_id={doc_id}[/red]")
            return 1
        try:
            azure_endpoint, azure_key = get_azure_settings()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        doc = airtable_source.fetch_content(target_meta, azure_endpoint, azure_key)
        tracker.remove_document(doc_id)
        result = ingestor.index_new_documents([doc])
        console.print(
            f"[green]Reindexed doc_id={doc_id}[/green] "
            f"({result['success']} success, {result['failed']} failed)"
        )
        return 0

    if doc_id.startswith("gform_"):
        gforms_source = _load_gforms_source(console)
        if gforms_source is None:
            console.print("[red]Google Forms source not configured[/red]")
            return 1
        target_meta = next(
            (m for m in gforms_source.list_files() if m["doc_id"] == doc_id),
            None,
        )
        if not target_meta:
            console.print(f"[red]Google Forms file not found for doc_id={doc_id}[/red]")
            return 1
        try:
            azure_endpoint, azure_key = get_azure_settings()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        doc = gforms_source.fetch_content(target_meta, azure_endpoint, azure_key)
        tracker.remove_document(doc_id)
        result = ingestor.index_new_documents([doc])
        console.print(
            f"[green]Reindexed doc_id={doc_id}[/green] "
            f"({result['success']} success, {result['failed']} failed)"
        )
        return 0

    documents = _read_documents(Path("registries/documents.json"))
    target_docs = [doc for doc in documents if str(doc.get("doc_id")) == doc_id]
    if not target_docs:
        console.print(f"[red]Document not found for doc_id={doc_id}[/red]")
        return 1
    tracker.remove_document(doc_id)
    result = ingestor.index_new_documents(target_docs)
    console.print(
        f"[green]Reindexed doc_id={doc_id}[/green] ({result['success']} success, {result['failed']} failed)"
    )
    return 0


def command_search(
    console: Console, searcher: Searcher, keyword: str, text: str, size: int
) -> int:
    if keyword and text:
        results = searcher.search_combined(keyword=keyword, text_query=text, size=size)
    elif keyword:
        results = searcher.search_by_keyword(keyword=keyword, size=size)
    elif text:
        results = searcher.search_by_text(query=text, size=size)
    else:
        console.print("[red]Provide --keyword and/or --text[/red]")
        return 1
    _render_search(console, results)
    return 0


def main() -> int:
    console = Console()
    parser = _build_parser()
    args = parser.parse_args()

    components = _build_components()
    tracker = components["tracker"]
    manager = components["manager"]
    ingestor = components["ingestor"]
    searcher = components["searcher"]

    try:
        if args.command == "init":
            return command_init(console, manager)
        if args.command == "sync":
            return command_sync(console, ingestor, tracker)
        if args.command == "status":
            return command_status(console, manager, tracker)
        if args.command == "reindex":
            return command_reindex(
                console=console,
                manager=manager,
                ingestor=ingestor,
                tracker=tracker,
                doc_id=args.doc_id,
                all_flag=bool(args.all),
            )
        if args.command == "search":
            return command_search(
                console=console,
                searcher=searcher,
                keyword=args.keyword,
                text=args.text,
                size=args.size,
            )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
