"""In-memory document catalog for LLM pipeline input."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_catalog(
    chat_id: str,
    documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    catalog_docs: List[Dict[str, Any]] = []
    for index, doc in enumerate(documents, start=1):
        paragraphs = doc.get("paragraphs") or []
        full_text = "\n\n".join(str(p) for p in paragraphs if p)
        catalog_docs.append(
            {
                "doc_index": index,
                "source_url": doc.get("source_url", ""),
                "filename": doc.get("filename", ""),
                "paragraph_count": len(paragraphs),
                "text": full_text,
                "relevant_excerpts": doc.get("relevant_excerpts") or [],
            }
        )
    return {"chat_id": chat_id, "documents": catalog_docs}


def catalog_to_prompt_text(catalog: Dict[str, Any], keywords: Optional[List[str]] = None) -> str:
    parts: List[str] = [f"Chat ID: {catalog.get('chat_id', '')}", ""]
    for doc in catalog.get("documents", []):
        parts.append(catalog_entry_to_prompt_text(doc, keywords=keywords))
        parts.append("")
    return "\n".join(parts).strip()


def catalog_entry_to_prompt_text(entry: Dict[str, Any], keywords: Optional[List[str]] = None) -> str:
    parts: List[str] = [
        f"Document index: {entry.get('doc_index', '')}",
        f"Filename: {entry.get('filename', '')}",
        f"Source URL: {entry.get('source_url', '')}",
    ]
    if keywords:
        parts.append("")
        parts.append(f"Target keywords: {', '.join(keywords)}")
        parts.append(
            "Extract complete body paragraphs that discuss these topics — not section headings, "
            "chapter titles, or table-of-contents lines."
        )
    
    parts.append("")
    parts.append("Full document text:")
    parts.append(str(entry.get("text", "")))
    return "\n".join(parts).strip()


def build_summary_doc_text(
    chat_id: str,
    catalog: Dict[str, Any],
    llm_response: Optional[str] = None,
) -> str:
    lines: List[str] = [
        f"Chat Pipeline Summary — {chat_id}",
        "",
        f"Documents processed: {len(catalog.get('documents', []))}",
        "",
    ]
    for doc in catalog.get("documents", []):
        lines.append(f"Document {doc.get('doc_index')}: {doc.get('filename', '')}")
        lines.append(f"Source: {doc.get('source_url', '')}")
        lines.append("")
        lines.append(str(doc.get("text", "")))
        lines.append("")
        lines.append("---")
        lines.append("")
    if llm_response:
        lines.append("LLM Analysis")
        lines.append("")
        lines.append(llm_response)
    return "\n".join(lines).strip()
