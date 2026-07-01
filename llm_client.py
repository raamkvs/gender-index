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

Every sentence in `text` must be findable verbatim in the source. If you can't quote the exact sentence, don't include it. Bold formatting (`**keyword**`) is the only permitted modification — everything else is character-for-character. This applies to all fields except `summary` in Category E (the sole exception where you write in your own words).

## Step 1 — Classify the document (exactly one)
| Type | Category | Examples |
|---|---|---|
| A | Multilateral Environmental Agreement | CBD, UNFCCC/Paris, Ramsar, Basel/Rotterdam/Stockholm, UNCCD |
| B | Gender Equality Global Agreement | CEDAW, Beijing Platform for Action, CSW conclusions |
| C | National environmental law/policy | NDCs, environment acts, climate strategies |
| D | National gender equality law/policy | National gender policy/act, institutional gender strategy |
| E | Case study of gender-responsive environmental action | Narrative of a specific project/program (not a legal instrument) |

If ambiguous, pick the closest match by primary subject matter.

## Step 2 — Keyword focus by type
- **A**: extract gender/women's-empowerment commitments. Keywords: gender, women, woman, girl, girls.
- **B**: extract environmental commitments. Keywords: rural/indigenous women, women environmental defenders, environment, climate change, biodiversity, chemicals, water, degradation, pollution, or any clearly environment-related term.
- **C**: extract gender commitments/considerations. Keywords: women, woman, girl, girls, gender, rural/indigenous women, women environmental defenders.
- **D**: extract environmental commitments/considerations. Keywords: women, woman, girl, girls, gender, environment, climate change, biodiversity, chemicals, water, degradation, pollution, or any clearly environment-related term.
- **E**: no keyword filter — extract the initiative's narrative.

## Step 3 — Extract paragraphs (Types A–D only)
Return complete, verbatim body paragraphs (typically 2+ sentences, ~80+ characters) that explain commitments, objectives, measures, rights, obligations, or analysis.

**Do NOT extract**: section headings, chapter/TOC titles, agenda items, standalone all-caps labels, quoted phrase lists, or any single-line label under ~80 characters without a full sentence. If a heading introduces relevant content, extract the paragraph(s) beneath it — never the heading alone.

Bold every keyword occurrence with `**keyword**`; change nothing else. If no relevant content exists, return `[]`.

## Step 3-alt — Case study (Type E only)
Summarize in your own words:
- `name` — activity/case study name
- `year` — year or range
- `environmental_topic` — topic addressed
- `summary` — brief paragraph on how the initiative advances gender equality/women's empowerment, with quantitative impact if available
- `source` — online source(s), if present in the document

## Step 4 — Page numbers
Identify the page marker (e.g. `[PAGE N]`, `--- Page N ---`, header/footer numbering) immediately preceding each excerpt and record as `page_number`. If an excerpt spans pages, use the starting page. If no marker exists anywhere in the document, use `null` — never guess.

## Output format
\```json
{
  "document_name": "Full official citation (instrument name, symbol, year, article/decision numbers)",
  "document_type": "A | B | C | D | E",
  "relevant_paragraphs": [
    { "text": "Verbatim paragraph with **bold** keywords...", "page_number": 4 }
  ],
  "case_studies": [
    {
      "name": "Activity name",
      "year": "2024",
      "environmental_topic": "Restoration and Waste Management",
      "summary": "Brief paragraph on the initiative and its gender-equality impact...",
      "source": "https://example.org",
      "page_number": 12
    }
  ]
}
\```
Rules:
1. Valid JSON only — nothing before or after.
2. Types A–D → populate `relevant_paragraphs`, leave `case_studies: []`. Type E → populate `case_studies`, leave `relevant_paragraphs: []`.
3. Every entry needs a `page_number` (or `null`).
4. If nothing relevant is found, return both arrays empty — never omit a key.

## Examples

**Correct (Type A)**:
\```json
{
  "document_name": "CITES and Gender Brief (November 2022)",
  "document_type": "A",
  "relevant_paragraphs": [
    { "text": "Men and **women** don't necessarily have the same access to resources including land, control over resources, and economic opportunities to shift away from wildlife use.", "page_number": 1 },
    { "text": "Being curious about these **gender** dynamics, understanding them and taking them into account amplifies the effectiveness of conservation and wildlife protection.", "page_number": 1 }
  ],
  "case_studies": []
}
\```
Every sentence is copied exactly from the source; only bold was added.

**Wrong (combines every failure mode to avoid)**:
\```json
{
  "document_name": "CITES and Gender Brief",
  "document_type": "A",
  "relevant_paragraphs": [
    { "text": "This brief explains why gender matters to CITES. Key points: wildlife trade is gender-differentiated. If you want, I can also provide a summary.", "page_number": 1 }
  ],
  "case_studies": []
}
\```
Wrong because: it opens with introductory framing ("This brief explains..."), reformats prose into a bulleted "Key points" list, paraphrases instead of quoting, and appends a service offer. None of that text is a verbatim sentence from the source — every one of these is independently disqualifying.

**Correct (Type E — the one case where summarizing is allowed)**:
\```json
{
  "document_name": "Adopt a Coastline",
  "document_type": "E",
  "relevant_paragraphs": [],
  "case_studies": [
    {
      "name": "Adopt a Coastline",
      "year": "2024",
      "environmental_topic": "Restoration and Waste Management",
      "summary": "More than 60 girls and young women trained as coastal stewards plant indigenous trees to slow coastal erosion, protect nesting sites of critically endangered turtles, and manage beach bins. The project, created by local NGO Adopt-a-Coastline, was selected for a $100,000 grant from the UN's Global Environment Facility (GEF).",
      "source": "https://www.bbc.com/news/world-latin-america-68683693 ; https://www.adoptacoastline.org/",
      "page_number": null
    }
  ]
}
\```"""


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
