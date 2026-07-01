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

## Role
You are a DATA EXTRACTION TOOL, not a conversational assistant. Copy relevant text word-for-word from the source document into structured JSON. Output ONLY the JSON object — no preamble, commentary, summaries, bullet reformatting, or offers of further help ("Would you like me to...", "I can also provide..."). If your output isn't valid, that's why.

Every sentence in `text` must be findable verbatim in the source. If you can't quote the exact sentence, don't include it. Bold formatting (`**keyword**`) is the only permitted modification — everything else is character-for-character.

## Document Classification
This extraction tool is configured to process ONLY Category C documents:
- **Category C: National environmental law/policy** — NDCs, environment acts, climate strategies, national environmental policies, etc.

## Keyword Focus
Extract gender commitments/considerations from the national environmental law/policy. 
Keywords to identify: women, woman, girl, girls, gender, rural/indigenous women, women environmental defenders.

## Extraction Instructions
Return complete, verbatim body paragraphs (typically 2+ sentences, ~80+ characters) that explain commitments, objectives, measures, rights, obligations, or analysis related to gender.

**Do NOT extract**: section headings, chapter/TOC titles, agenda items, standalone all-caps labels, quoted phrase lists, or any single-line label under ~80 characters without a full sentence. If a heading introduces relevant content, extract the paragraph(s) beneath it — never the heading alone.

Bold every keyword occurrence with `**keyword**`; change nothing else. If no relevant content exists, return `[]`.

## Page Numbers
Identify the page marker (e.g. `[PAGE N]`, `--- Page N ---`, header/footer numbering) immediately preceding each excerpt and record as `page_number`. If an excerpt spans pages, use the starting page. If no marker exists anywhere in the document, use `null` — never guess.

## Output Format
\```json
{
  "document_name": "Full official citation (instrument name, symbol, year, article/decision numbers)",
  "document_type": "C",
  "relevant_paragraphs": [
    { "text": "Verbatim paragraph with **bold** keywords...", "page_number": 4 }
  ],
  "case_studies": []
}
\```

Rules:
1. Valid JSON only — nothing before or after.
2. Always set `document_type: "C"` (National environmental law/policy).
3. Populate `relevant_paragraphs` with gender-related provisions. Leave `case_studies: []` empty.
4. Every entry needs a `page_number` (or `null`).
5. If nothing relevant is found, return `relevant_paragraphs: []` — never omit the key.

## Example

**Correct extraction**:
\```json
{
  "document_name": "Rwanda National Environment and Climate Change Policy (2019)",
  "document_type": "C",
  "relevant_paragraphs": [
    { "text": "The policy recognizes that **women** and **girls** are disproportionately affected by climate change impacts due to their socio-economic roles in natural resource management.", "page_number": 12 },
    { "text": "Ensure **gender**-responsive climate action by integrating **women**'s participation in decision-making processes for environmental management at all levels.", "page_number": 15 }
  ],
  "case_studies": []
}
\```
Every sentence is copied exactly from the source; only bold was added to keywords.

**Wrong example (combines every failure mode to avoid)**:
\```json
{
  "document_name": "National Policy",
  "document_type": "C",
  "relevant_paragraphs": [
    { "text": "This policy explains gender considerations. Key points: women are affected by climate change. I can also provide more details if needed.", "page_number": 1 }
  ],
  "case_studies": []
}
\```
Wrong because: it opens with introductory framing ("This policy explains..."), reformats prose into a bulleted "Key points" list, paraphrases instead of quoting, and appends a service offer. None of that text is a verbatim sentence from the source — every one of these is independently disqualifying."""


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


# Some upstream callers (e.g. Copilot Studio connectors) cannot send a true
# null for an optional string field and instead send a literal placeholder
# word. Treat these as "no hint provided" rather than using them verbatim
# as the system prompt.
_NULL_HINT_PLACEHOLDERS = {
    "blank",
    "none",
    "null",
    "n/a",
    "na",
    "undefined",
    "string",
    "-",
}


def _resolve_output_schema(output_schema_hint: Optional[str]) -> str:
    if output_schema_hint:
        cleaned = output_schema_hint.strip()
        if cleaned and cleaned.lower() not in _NULL_HINT_PLACEHOLDERS:
            return cleaned
        if cleaned:
            logger.warning(
                f"[AI API] Ignoring placeholder output_schema_hint value {cleaned!r}; using DEFAULT_OUTPUT_SCHEMA instead."
            )
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
                "document_type": "A",
                "relevant_paragraphs": [],
                "case_studies": [],
                "error": "Empty LLM response",
            }
        else:
            # Fallback for non-JSON prose responses
            data = {
                "document_name": _infer_document_name(prose, filename),
                "document_type": "A",
                "relevant_paragraphs": [
                    {"text": p, "page_number": None} for p in _split_prose_paragraphs(prose)
                ],
                "case_studies": [],
            }

    document_name = str(data.get("document_name") or filename).strip() or filename
    document_type = str(data.get("document_type", "A")).strip() or "A"
    
    # Handle relevant_paragraphs - support both new format (objects) and old format (strings)
    paragraphs = data.get("relevant_paragraphs", [])
    if not isinstance(paragraphs, list):
        paragraphs = []
    
    normalized_paragraphs = []
    for p in paragraphs:
        if isinstance(p, dict):
            # New format: {"text": "...", "page_number": N}
            text = str(p.get("text", "")).strip()
            page_number = p.get("page_number")
            if text and not _looks_like_heading_only(text):
                normalized_paragraphs.append({
                    "text": text,
                    "page_number": page_number if page_number is not None else None
                })
        elif isinstance(p, str) and p.strip():
            # Old format: plain string - convert to new format
            text = p.strip()
            if not _looks_like_heading_only(text):
                normalized_paragraphs.append({
                    "text": text,
                    "page_number": None
                })
    
    # Handle case_studies
    case_studies = data.get("case_studies", [])
    if not isinstance(case_studies, list):
        case_studies = []
    
    normalized_case_studies = []
    for cs in case_studies:
        if isinstance(cs, dict):
            # Validate required fields
            name = str(cs.get("name", "")).strip()
            if name:
                normalized_case_studies.append({
                    "name": name,
                    "year": str(cs.get("year", "")).strip() or "",
                    "environmental_topic": str(cs.get("environmental_topic", "")).strip() or "",
                    "summary": str(cs.get("summary", "")).strip() or "",
                    "source": str(cs.get("source", "")).strip() or "",
                    "page_number": cs.get("page_number") if cs.get("page_number") is not None else None
                })

    normalized: Dict[str, Any] = {
        "document_name": document_name,
        "document_type": document_type,
        "relevant_paragraphs": normalized_paragraphs,
        "case_studies": normalized_case_studies,
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
    case_studies = data.get("case_studies") or []
    error = data.get("error")

    if error and not paragraphs and not case_studies:
        return f"{doc_name}. Extraction unavailable ({error})."
    
    def strip_bold(value: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"\1", str(value))
    
    # Handle new format (objects) and old format (strings)
    texts = []
    for p in paragraphs:
        if isinstance(p, dict):
            text = str(p.get("text", "")).strip()
            if text:
                texts.append(strip_bold(text))
        elif isinstance(p, str) and p.strip():
            texts.append(strip_bold(p))
    
    if not texts and not case_studies:
        return f"{doc_name}. No relevant gender-related provisions found."

    body = " ".join(texts)
    
    # Add case studies if present
    if case_studies:
        cs_summaries = []
        for cs in case_studies:
            if isinstance(cs, dict):
                name = cs.get("name", "")
                summary = cs.get("summary", "")
                if name or summary:
                    cs_summaries.append(f"{name}: {summary}".strip(": "))
        if cs_summaries:
            body = f"{body} Case studies: {' '.join(cs_summaries)}".strip()
    
    return f"{doc_name}. {body}".strip()


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int = 300,
) -> str:
    settings = get_gpt54_settings()
    
    # Log first 100 characters of system prompt
    system_prompt_preview = system_prompt[:100] + "..." if len(system_prompt) > 100 else system_prompt
    logger.info(f"[AI API] Starting LLM call")
    logger.info(f"[AI API] System prompt (first 100 chars): {system_prompt_preview}")
    logger.info(f"[AI API] User prompt length: {len(user_prompt)} characters")
    
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
                "content": system_prompt,
            },
            {
                "type": "message",
                "role": "user",
                "content": user_prompt,
            },
        ],
        "store": False,
        "temperature": 0.2,
    }
    
    logger.info(f"[AI API] Posting request to: {settings.endpoint}")
    logger.info(f"[AI API] Model deployment: {settings.deployment}")

    response = requests.post(
        settings.endpoint,
        headers=headers,
        json=body,
        timeout=timeout_seconds,
    )
    
    logger.info(f"[AI API] Response status code: {response.status_code}")
    
    if not response.ok:
        error_preview = response.text[:500] if response.text else "No error message"
        logger.error(f"[AI API] Request failed with status {response.status_code}: {error_preview}")
        raise RuntimeError(
            f"GPT54 request failed ({response.status_code}): {response.text[:2000]}"
        )

    payload = response.json()
    
    # Log API response details for debugging
    status = payload.get("status", "unknown")
    usage = payload.get("usage", {})
    logger.info(
        f"[AI API] Response - Status: {status}, "
        f"Input tokens: {usage.get('input_tokens', 0)}, "
        f"Output tokens: {usage.get('output_tokens', 0)}"
    )
    
    text = _extract_response_text(payload)
    if not text:
        logger.error("[AI API] Extracted text is empty")
        raise RuntimeError("GPT54 response contained no text output.")
    
    text_preview = text[:200] + "..." if len(text) > 200 else text
    logger.info(f"[AI API] Output text length: {len(text)} characters")
    logger.info(f"[AI API] Output text preview (first 200 chars): {text_preview}")
    
    return text


def analyze_document_with_llm(
    catalog_entry: Dict[str, Any],
    output_schema_hint: Optional[str] = None,
    timeout_seconds: int = 300,
) -> str:
    """Run one LLM call for a single catalog document entry."""
    system_prompt = _resolve_output_schema(output_schema_hint)
    
    # User prompt includes document metadata and full text
    user_prompt = catalog_entry_to_prompt_text(catalog_entry, keywords=None)
    raw_response = _call_llm(system_prompt, user_prompt, timeout_seconds=timeout_seconds)
    filename = str(catalog_entry.get("filename") or "document.pdf")
    return normalize_llm_extraction(raw_response, filename)


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
