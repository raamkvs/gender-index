"""Azure AI Foundry GPT54 Responses API client."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from doc_catalog import catalog_entry_to_prompt_text

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_SCHEMA = """\
Output a valid JSON object with this exact structure:

{
  "document_name": "Full official document name/citation as it appears in the text",
  "relevant_paragraphs": [
    "Full paragraph 1 containing **keyword** with bold formatting...",
    "Full paragraph 2 containing **keyword** with bold formatting...",
    ...
  ]
}

Rules:
1. Output must be valid JSON (no additional text before or after the JSON object)
2. Extract COMPLETE body paragraphs from the document that contain substantive policy content related to any of the provided keywords
3. Each entry must be a full paragraph of continuous prose (typically 2+ sentences, at least ~80 characters) that explains commitments, objectives, measures, rights, obligations, or analysis — not a label or title
4. Bold all keyword occurrences using **keyword** markdown format (wrap keywords with double asterisks)
5. If no relevant content found, return empty array [] for relevant_paragraphs
6. Document name should include full citation (treaty name, instrument title, document symbol, year, decision/article numbers, etc.)
7. Each paragraph should be a separate array element
8. Preserve original paragraph wording (no summarization or paraphrasing); copy the full paragraph as it appears in the OCR text, including surrounding sentences for context
9. Do NOT extract any of the following as relevant_paragraphs:
   - Section headings, chapter titles, table-of-contents lines, agenda items, or bullet labels (e.g. "EQUIDAD DE GÉNERO", "POLÍTICA FISCAL")
   - Standalone all-caps titles or short quoted phrases without explanatory prose
   - Lists of headings joined with dashes, commas, or quotation marks
   - Single-line labels under ~80 characters that lack a complete sentence
10. When a heading introduces relevant content, extract the paragraph(s) of body text beneath it — never the heading alone

Example output:
{
  "document_name": "Convention on Biological Diversity (CBD) UNEP/CBD/COP/5/23 (2000). V/16. Article 8(j) and related provisions",
  "relevant_paragraphs": [
    "Preamble Recognizing the vital role that **women** play in the conservation and sustainable use of biodiversity, and emphasizing that greater attention should be given to strengthening this role and the participation of **women** of indigenous and local communities in the programme of work."
  ]
}
"""


class LLMConfigError(RuntimeError):
    pass


@dataclass
class GPT54Settings:
    api_key: str
    endpoint: str
    deployment: str
    api_version: str


def get_gpt54_settings() -> GPT54Settings:
    api_key = os.getenv("GPT54_API_KEY", "").strip()
    endpoint = os.getenv("GPT54_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_GPT54_DEPLOYMENT", "").strip()
    api_version = os.getenv("AZURE_GPT54_API_VERSION", "").strip()

    missing: List[str] = []
    if not api_key:
        missing.append("GPT54_API_KEY")
    if not endpoint:
        missing.append("GPT54_ENDPOINT")
    if not deployment:
        missing.append("AZURE_GPT54_DEPLOYMENT")
    if not api_version:
        missing.append("AZURE_GPT54_API_VERSION")
    if missing:
        raise LLMConfigError(f"GPT54 env vars missing: {', '.join(missing)}")

    return GPT54Settings(
        api_key=api_key,
        endpoint=endpoint.rstrip("/"),
        deployment=deployment,
        api_version=api_version,
    )


def _extract_response_text(payload: Dict[str, Any]) -> str:
    # Check for explicit output_text field
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    # Parse output array (Azure AI Foundry format)
    chunks: List[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            chunks.append(content.strip())
            continue
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                for key in ("text", "output_text"):
                    text = part.get(key)
                    if isinstance(text, str) and text.strip():
                        chunks.append(text.strip())

    if chunks:
        return "\n".join(chunks)

    # Try direct text/content/message keys
    for key in ("text", "content", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Try OpenAI-style choices format
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

    # Check if there's an error message
    error_msg = payload.get("error")
    if error_msg:
        logger.error(f"LLM API returned error: {error_msg}")
        raise RuntimeError(f"LLM API error: {error_msg}")
    
    # Log the problematic response structure for debugging
    status = payload.get("status", "unknown")
    output_tokens = payload.get("usage", {}).get("output_tokens", 0)
    logger.error(
        f"Failed to extract text from LLM response. "
        f"Status: {status}, Output tokens: {output_tokens}, "
        f"Response keys: {list(payload.keys())}"
    )
    
    # Return a more helpful error message instead of dumping JSON
    raise RuntimeError(
        f"LLM returned empty response. Status: {status}, "
        f"Output tokens: {output_tokens}. Check API configuration and model deployment."
    )


def _resolve_output_schema(output_schema_hint: Optional[str]) -> str:
    if output_schema_hint and output_schema_hint.strip():
        return output_schema_hint.strip()
    return DEFAULT_OUTPUT_SCHEMA


def parse_llm_json_response(text: str) -> Dict[str, Any]:
    """Parse JSON from an LLM response, tolerating code fences and leading prose."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Empty LLM response")

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        data = json.loads(cleaned[start : end + 1])
        if isinstance(data, dict):
            return data

    raise ValueError(f"Could not parse JSON from LLM response: {cleaned[:200]}")


def _infer_document_name(prose: str, filename: str) -> str:
    first_line = prose.splitlines()[0].strip() if prose else ""
    if first_line.startswith("###"):
        return first_line.lstrip("#").strip()
    if first_line.startswith("**") and first_line.endswith("**"):
        return first_line.strip("*").strip()
    if len(first_line) > 20 and len(first_line) < 300:
        return first_line
    return filename


def _split_prose_paragraphs(prose: str) -> List[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", prose) if block.strip()]
    if blocks:
        return blocks
    line = prose.strip()
    return [line] if line else []


_HEADING_DASH_LIST_RE = re.compile(
    r'^(\s*"[^"]+"\s*-\s*)+"[^"]+"\s*$',
    re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r"[.!?;:]")


def _looks_like_heading_only(text: str) -> bool:
    """Heuristic filter for section titles and TOC fragments mistaken as paragraphs."""
    cleaned = text.strip().strip('"').strip()
    if not cleaned:
        return True
    if _HEADING_DASH_LIST_RE.match(text.strip()):
        return True

    letters = [char for char in cleaned if char.isalpha()]
    if letters:
        upper_ratio = sum(1 for char in letters if char.isupper()) / len(letters)
        if upper_ratio >= 0.85 and len(cleaned) < 120:
            return True

    word_count = len(re.findall(r"\b\w+\b", cleaned, flags=re.UNICODE))
    has_sentence_end = bool(_SENTENCE_END_RE.search(cleaned))
    if len(cleaned) < 80 and not has_sentence_end:
        return True
    if word_count < 12 and not has_sentence_end:
        return True
    return False


def _filter_substantive_paragraphs(paragraphs: List[str]) -> List[str]:
    return [paragraph for paragraph in paragraphs if not _looks_like_heading_only(paragraph)]


def normalize_llm_extraction(raw: str, filename: str) -> str:
    """Normalize LLM output to canonical JSON string for storage and PDF generation."""
    try:
        data = parse_llm_json_response(raw)
    except ValueError:
        prose = raw.strip()
        if not prose:
            data = {
                "document_name": filename,
                "relevant_paragraphs": [],
                "error": "Empty LLM response",
            }
        else:
            data = {
                "document_name": _infer_document_name(prose, filename),
                "relevant_paragraphs": _split_prose_paragraphs(prose),
            }

    document_name = str(data.get("document_name") or filename).strip() or filename
    paragraphs = data.get("relevant_paragraphs", [])
    if not isinstance(paragraphs, list):
        paragraphs = [str(paragraphs)] if paragraphs else []
    paragraphs = [str(p).strip() for p in paragraphs if str(p).strip()]
    paragraphs = _filter_substantive_paragraphs(paragraphs)

    normalized: Dict[str, Any] = {
        "document_name": document_name,
        "relevant_paragraphs": paragraphs,
    }
    if data.get("error"):
        normalized["error"] = str(data["error"])
    return json.dumps(normalized)


def format_extraction_for_api(ai_extraction: str) -> str:
    """Convert stored JSON extraction into readable prose for API/chat consumers."""
    try:
        data = json.loads(ai_extraction)
    except json.JSONDecodeError:
        return ai_extraction.strip()

    if not isinstance(data, dict):
        return ai_extraction.strip()

    doc_name = str(data.get("document_name", "Unknown Document")).strip()
    paragraphs = data.get("relevant_paragraphs") or []
    error = data.get("error")

    if error and not paragraphs:
        return f"{doc_name}. Extraction unavailable ({error})."
    if not paragraphs:
        return f"{doc_name}. No relevant gender-related provisions found."

    def strip_bold(value: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"\1", str(value))

    body = " ".join(strip_bold(p) for p in paragraphs if str(p).strip())
    return f"{doc_name}. {body}"


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int = 300,
) -> str:
    settings = get_gpt54_settings()
    headers = {
        "api-key": settings.api_key,
        "Content-Type": "application/json",
    }
    if settings.api_version:
        headers["x-ms-api-version"] = settings.api_version

    body: Dict[str, Any] = {
        "model": settings.deployment,
        "input": [
            {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
        "store": False,
        "temperature": 0.2,
    }

    response = requests.post(
        settings.endpoint,
        headers=headers,
        json=body,
        timeout=timeout_seconds,
    )
    if not response.ok:
        raise RuntimeError(
            f"GPT54 request failed ({response.status_code}): {response.text[:2000]}"
        )

    payload = response.json()
    
    # Log API response details for debugging
    status = payload.get("status", "unknown")
    usage = payload.get("usage", {})
    logger.info(
        f"LLM API response - Status: {status}, "
        f"Input tokens: {usage.get('input_tokens', 0)}, "
        f"Output tokens: {usage.get('output_tokens', 0)}"
    )
    
    text = _extract_response_text(payload)
    if not text:
        raise RuntimeError("GPT54 response contained no text output.")
    return text


def analyze_document_with_llm(
    catalog_entry: Dict[str, Any],
    keywords: Optional[List[str]] = None,
    output_schema_hint: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """Run one LLM call for a single catalog document entry."""
    schema = _resolve_output_schema(output_schema_hint)
    
    # Build system prompt with keywords
    keywords_list = keywords or []
    if keywords_list:
        keywords_str = ", ".join(keywords_list)
        system_prompt = (
            f"You extract substantive policy provisions from a single OCR'd document that relate to ANY of these keywords:\n"
            f"{keywords_str}\n\n"
            "Return clear, complete paragraphs of body text that convey relevant points, commitments, or insights from the document. "
            "Do NOT return section headings, chapter titles, table-of-contents entries, or other title-only lines — "
            "when a heading marks relevant content, extract the explanatory paragraph(s) that follow it instead.\n\n"
            "For each extracted paragraph, if any of these keywords appear, highlight them using **bold** markdown formatting.\n\n"
            f"Output format instructions:\n{schema}"
        )
    else:
        # Fallback if no keywords provided
        system_prompt = (
            "You extract gender-related and closely associated provisions from a single "
            "OCR'd document. Return full substantive paragraphs with relevant insights — "
            "never section headings or title-only lines. Follow the output format exactly.\n\n"
            f"Output format instructions:\n{schema}"
        )
    
    user_prompt = catalog_entry_to_prompt_text(catalog_entry, keywords=keywords_list)
    raw_response = _call_llm(system_prompt, user_prompt, timeout_seconds=timeout_seconds)
    filename = str(catalog_entry.get("filename") or "document.pdf")
    return normalize_llm_extraction(raw_response, filename)


def combine_document_extractions(extractions: List[str]) -> str:
    """Join per-document LLM outputs into the final pipeline response text."""
    cleaned = [text.strip() for text in extractions if text and text.strip()]
    return "\n\n".join(cleaned)


def analyze_all_documents(
    catalog: Dict[str, Any],
    keywords: Optional[List[str]] = None,
    output_schema_hint: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """Run one LLM call per catalog document and combine the extracts."""
    extractions: List[str] = []
    for entry in catalog.get("documents", []):
        extraction = analyze_document_with_llm(
            entry,
            keywords=keywords,
            output_schema_hint=output_schema_hint,
            timeout_seconds=timeout_seconds,
        )
        extractions.append(extraction)
    return combine_document_extractions(extractions)
