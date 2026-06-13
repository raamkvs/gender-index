"""Azure AI Foundry GPT54 Responses API client."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from doc_catalog import catalog_entry_to_prompt_text

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_SCHEMA = """\
Output format (strict — one document only):

Format your output using this markdown-style structure:

1. Start with a subsection header: ### {Organization/Treaty Name}
2. Follow with the full citation in bold: **{Document symbol, title, article/section numbers, year}**
3. Then provide the extracted provisions in clear paragraphs
4. Use *italics* (with asterisks) to emphasize key gender-related terms like: women, girls, \
gender equality, empowerment, indigenous peoples, local communities, rural women, young women, etc.
5. For articles with sub-sections, use **(a)**, **(b)**, **(c)** formatting
6. Separate distinct provisions with blank lines
7. If grouping by theme is needed, use ## {Theme Name} before subsections
8. If nothing relevant is found, output: ### {Organization Name}\n\n**{Document citation}**\n\nNo relevant gender-related provisions found.

Example:

### Convention on the Elimination of All Forms of Discrimination against Women (CEDAW)

**CEDAW 1979. Article 14.2.**

States Parties shall take all appropriate measures to eliminate discrimination against *women in rural areas* in order to ensure, on a basis of equality of men and women, that they participate in and benefit from rural development and, in particular, shall ensure to such women the right:

**(a)** To participate in the elaboration and implementation of development planning at all levels.

**(b)** To have access to adequate health care facilities, including information, counselling and services in family planning.
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
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            chunks.append(content.strip())
            continue
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
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
        "temperature": 0.7,  # Balanced creativity
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
    output_schema_hint: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """Run one LLM call for a single catalog document entry."""
    schema = _resolve_output_schema(output_schema_hint)
    system_prompt = (
        "You extract gender-related and closely associated provisions from a single "
        "OCR'd document. Follow the output format exactly.\n\n"
        f"Output format instructions:\n{schema}"
    )
    user_prompt = catalog_entry_to_prompt_text(catalog_entry)
    return _call_llm(system_prompt, user_prompt, timeout_seconds=timeout_seconds)


def combine_document_extractions(extractions: List[str]) -> str:
    """Join per-document LLM outputs into the final pipeline response text."""
    cleaned = [text.strip() for text in extractions if text and text.strip()]
    return "\n\n".join(cleaned)


def analyze_all_documents(
    catalog: Dict[str, Any],
    output_schema_hint: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """Run one LLM call per catalog document and combine the extracts."""
    extractions: List[str] = []
    for entry in catalog.get("documents", []):
        extraction = analyze_document_with_llm(
            entry,
            output_schema_hint=output_schema_hint,
            timeout_seconds=timeout_seconds,
        )
        extractions.append(extraction)
    return combine_document_extractions(extractions)
