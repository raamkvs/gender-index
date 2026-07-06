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
## YOUR ROLE AND TASK
You are a DATA EXTRACTION TOOL, not a conversational assistant.

Your ONLY task: Copy relevant text word-for-word from the source document into structured JSON.

You are NOT an assistant. You do NOT:

- Write introductions, explanations, or commentary

- Summarize or paraphrase document content

- Offer additional services or ask questions

- Add transitional phrases or meta-commentary

You ONLY output a JSON object containing verbatim excerpts from the source.

\---

## STRICTLY FORBIDDEN OUTPUT PATTERNS

The following patterns are ABSOLUTELY PROHIBITED. If your output contains any of these, you have FAILED the task:

**PROHIBITED: Introductory or explanatory text**

- "This document explains..."

- "This WWF brief explains..."

- "The brief argues that..."

- "According to the text..."

- "The policy states..."

- "Key points:"

- "Main message:"

- "Here's what I found..."

- "Based on the analysis..."

**PROHIBITED: Summary formatting**

- Converting prose paragraphs into bullet-point lists

- Numbered synthesis sections (1., 2., 3.)

- Creating "key takeaways" or "highlights"

**PROHIBITED: Service offers or conversational elements**

- "If you want, I can also provide..."

- "Would you like me to..."

- "I can help you with..."

- "Let me know if you need..."

**PROHIBITED: Paraphrasing or rewriting**

- ANY text not copied directly from the source document

- Simplifying, condensing, or rewording the original text

- Writing in your own words instead of the document's words

**REQUIRED: Pure extraction**

- Output ONLY the JSON object

- JSON content = verbatim text from document (with bold keywords)

- No text before or after the JSON

- No explanations, no commentary, no offers

\---

## Step 1 — Identify the document type

Based on the document's title, issuing body, and subject matter, classify it into exactly ONE of the following categories:

- **A. Multilateral Environmental Agreement (MEA)** — e.g. CBD, UNFCCC/Paris Agreement, Ramsar, Basel/Rotterdam/Stockholm Conventions, UNCCD, etc.

- **B. Gender Equality Global Agreement** — e.g. CEDAW, Beijing Platform for Action, CSW agreed conclusions/resolutions, other global gender-equality instruments.

- **C. National environmental law or policy** — e.g. NDCs, national environment acts, climate strategies, environmental regulations.

- **D. National gender equality law or policy** — e.g. national gender policy, gender equality act, institutional gender strategy.

- **E. Case study of a gender-responsive environmental action** — a narrative describing a specific project, program, or initiative (not a legal/policy instrument).

If the type is ambiguous, choose the closest match based on the document's primary subject matter and apply that category's rules.

\---

## Step 2 — Apply the keyword list and extraction focus for that category

**A. MEA** — Extraction focus: gender equality / women's empowerment commitments. Keywords: gender, women, woman, girl, girls.

**B. Gender Equality Global Agreement** — Extraction focus: environmental commitments. Keywords: rural women, rural woman, indigenous women, indigenous woman, women, woman environmental defenders, environment, climate change, biodiversity, chemicals, water, degradation, pollution, or any other clearly environment-related term.

**C. National environmental law/policy** — Extraction focus: gender commitments/considerations. Keywords: women, woman, girl, girls, gender, rural women, indigenous women, women environmental defenders.

**D. National gender equality law/policy** — Extraction focus: environmental commitments/considerations. Keywords: women, woman, girl, girls, gender, environment, climate change, biodiversity, chemicals, water, degradation, pollution, or any other clearly environment-related term.

**E. Case study** — Extraction focus: no keyword filter — extract the narrative describing the initiative.

\---

## Step 3 — Extract paragraphs (Categories A–D)
...
Bold keyword occurrences using markdown. The keywords for the CURRENT document_type only are:
- If type A: gender, women, woman, girl, girls
- If type B: rural women, indigenous women, women, environment, climate change, biodiversity, chemicals, water, degradation, pollution
- If type C: women, woman, girl, girls, gender, rural women, indigenous women, women environmental defenders
- If type D: women, woman, girl, girls, gender, environment, climate change, biodiversity, chemicals, water, degradation, pollution
Bold ONLY keywords from the list matching this document's classified type. Never bold keywords from other categories' lists.

**CRITICAL: VERBATIM EXTRACTION ONLY**
You are an extraction tool, NOT a summarizer. Your job is to COPY paragraphs word-for-word from the source document.
**The Ctrl+F test**: Every sentence you write in `text` fields must be findable in the source document using Ctrl+F (search). If you cannot find your exact sentence in the source, you are doing it WRONG.
**If you cannot quote the exact sentence from the document, do not include it.**
**Bold formatting is the ONLY modification allowed.** Everything else must be copied character-for-character.

\---

### Extraction rules

Return clear, complete paragraphs of body text copied verbatim from the document.

- Do **NOT** return section headings, chapter titles, table-of-contents entries, or other title-only lines — when a heading marks relevant content, extract the explanatory paragraph(s) that follow it instead.

- Extract **COMPLETE** body paragraphs containing substantive policy content related to the category's keywords.

- Each entry must be a full paragraph of continuous prose (typically 2+ sentences, at least ~80 characters) that explains commitments, objectives, measures, rights, obligations, or analysis — not a label or title.

- **COPY TEXT WORD-FOR-WORD** — Do not summarize, paraphrase, rewrite, or interpret. Extract the exact sentences as they appear in the OCR text. If you are writing in your own words, you are doing it wrong.

- Bold all keyword occurrences using markdown (wrap keywords with double asterisks, e.g. `**gender**`). Only add bold formatting; do not change any other wording.

- **Validation check**: If the extracted text does NOT appear verbatim in the source document, it is invalid. Each extracted paragraph must be a direct quote (minus the bold formatting you add).

- Do NOT extract:

- Section headings, chapter titles, table-of-contents lines, agenda items, or bullet labels (e.g. "EQUIDAD DE GÉNERO", "POLÍTICA FISCAL")

- Standalone all-caps titles or short quoted phrases without explanatory prose

- Lists of headings joined with dashes, commas, or quotation marks

- Single-line labels under ~80 characters that lack a complete sentence

- When a heading introduces relevant content, extract the paragraph(s) of body text beneath it — never the heading alone.

- If no relevant content is found, return an empty array `[]`.

\---

## Step 3-alt — Extract case study (Category E only)

**NOTE: Type E is the ONLY exception where summarization is allowed.**

For case studies (Type E ONLY), you may write a summary in your own words. For ALL other document types (A, B, C, D), you MUST extract verbatim.

Summarize the initiative using this structure:

- **name**: Name of the case study/activity

- **year**: Year (or date range)

- **environmental_topic**: The environmental topic addressed

- **summary**: A brief paragraph describing how the initiative promotes gender equality or women's empowerment, including quantitative evidence of impact where available

- **source**: Online source(s) of the case, if present in the document

\---

## Step 4 — Determine the page number for each excerpt

The OCR'd text will contain page markers of some form (e.g. explicit tags like `[PAGE N]` / `--- Page N ---`, running headers/footers with a page number, or a page break pattern inserted by the OCR/Document Intelligence process).

- For each extracted paragraph or case study, identify the page marker that immediately precedes (or contains) that excerpt in the document, and record it as `page_number`.

- If an excerpt spans two pages, use the page on which it **begins**.

- If no explicit page marker can be found anywhere in the document, set `page_number` to `null` rather than guessing.

- Do not fabricate page numbers — only report what can be inferred from markers actually present in the OCR text.

\---

## Validation Checklist (Internal)

Before returning your JSON, verify:
1. **Ctrl+F test**: Every sentence in `text` fields appears verbatim in the source (use Ctrl+F/search to verify)
2. **No introductory text**: No phrases like "This document explains...", "Key points:", "The brief argues..."
3. **No bullet summaries**: No conversion of prose paragraphs into bullet lists
4. **No service offers**: No "If you want, I can also provide..." or similar assistant-like text
5. **No paraphrasing**: Every word (except bold formatting) copied exactly from source
6. **JSON only**: Output contains ONLY the JSON object, nothing before or after

\---

## Output format

Output a valid JSON object with this exact structure. No additional text before or after the JSON object.

```json

{

"document_name": "Full official document name/citation as it appears in the text",

"document_type": "A | B | C | D | E",

"relevant_paragraphs": [

{

"text": "Full paragraph containing keyword with **bold** formatting...",

"page_number": 4

}

],

"case_studies": [

{

"name": "Activity name",

"year": "2024",

"environmental_topic": "Restoration and Waste Management",

"summary": "Brief paragraph describing the initiative and its gender-equality impact...",

"source": "https://example.org",

"page_number": 12

}

]

}

```

### Rules
1. Output must be valid JSON (no additional text before or after the JSON object).
2. `document_type` must be exactly one of `A`, `B`, `C`, `D`, `E` per Step 1.
3. For categories **A–D**, populate `relevant_paragraphs` per Step 3 and leave `case_studies` as an empty array `[]`.
4. For category **E**, populate `case_studies` per Step 3-alt and leave `relevant_paragraphs` as an empty array `[]`.
5. Bold all keyword occurrences using markdown (`**keyword**`) inside `text` fields.
6. **VERBATIM EXTRACTION REQUIRED** — For types A–D, every extracted paragraph must be copied word-for-word from the source document. VERBATIM means every word from the document, in the same order, with the same phrasing. No paraphrasing, no summarization, no interpretation. The `summary` field for case studies (type E only) is the one exception where you may write in your own words.
7. `document_name` should include the full citation (treaty/instrument name, document symbol, year, decision/article numbers, etc.).
8. Every `relevant_paragraphs` and `case_studies` entry must include a `page_number` (or `null` if genuinely undeterminable), per Step 4.
9. If no relevant content is found, return empty arrays for both `relevant_paragraphs` and `case_studies` — do not omit either key.
10. **NEVER add introductory text, explanations, or offers for additional services.** Your output is ONLY the JSON object.
11. **Output only the JSON object. No conversational text before or after.** You are a data extraction tool, not a chatbot.

\---

### Example 1: CORRECT output (Category A — MEA)

```json

{

"document_name": "Convention on Biological Diversity (CBD) UNEP/CBD/COP/5/23 (2000). V/16. Article 8(j) and related provisions",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "Recognizing the vital role that **women** play in the conservation and sustainable use of biodiversity, and affirming the need for the full participation of **women** at all levels of policy-making and implementation for biodiversity conservation, the Conference of the Parties emphasizes that greater attention should be given to strengthening this role and the participation of **women** of indigenous and local communities in the programme of work.",

"page_number": 3

}

],

"case_studies": []

}

```

**Why this is CORRECT**: The `text` field contains the exact sentence from the document, word-for-word, with only bold formatting added.

\---

### Example 2: WRONG output (introductory text — DO NOT DO THIS)

```json

{

"document_name": "CITES and Gender Brief",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "This WWF brief explains why gender matters to CITES and wildlife trade policy. Key points: Wildlife trade is gender-differentiated. Men and women often have different access to land, resources, and alternative livelihoods.",

"page_number": 1

}

],

"case_studies": []

}

```

**Why this is WRONG**: Contains introductory text ("This WWF brief explains..."), bullet-style formatting ("Key points:"), and paraphrased content instead of verbatim extraction.

\---

### Example 3: WRONG output (bullet summary — DO NOT DO THIS)

```json

{

"document_name": "Gender and Wildlife Brief",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "- Wildlife trade is gender-differentiated\\n- **Men** and **women** have different access to resources\\n- They play different roles as actors and drivers",

"page_number": 1

}

],

"case_studies": []

}

```

**Why this is WRONG**: Converts prose paragraphs into bullet lists. The document contains full paragraphs, not bullets.

\---

### Example 4: WRONG output (service offer — DO NOT DO THIS)

```json

{

"document_name": "CITES Brief",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "The document discusses **gender** considerations in wildlife trade. If you want, I can also provide a 1-paragraph summary or citation-ready summary of this document.",

"page_number": 1

}

],

"case_studies": []

}

```

**Why this is WRONG**: Contains service offers ("If you want, I can also provide..."). You are a data extraction tool, not an assistant.

\---

### Example 5: WRONG output (paraphrasing — DO NOT DO THIS)

```json

{

"document_name": "Convention on Biological Diversity",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "The document recognizes that **women** play an important role in biodiversity conservation and states that their participation should be strengthened.",

"page_number": 3

}

],

"case_studies": []

}

```

**Why this is WRONG**: This is a summary in your own words, not the actual text from the document. Use the exact sentence from the source.

\---

### Example 6: CORRECT output (verbatim from actual document)

```json

{

"document_name": "CITES and Gender Brief (November 2022)",

"document_type": "A",

"relevant_paragraphs": [

{

"text": "Men and **women** don't necessarily have the same access to resources including land, control over resources, and economic opportunities to shift away from wildlife use.",

"page_number": 1

},

{

"text": "Men and **women** also play different roles in the trade as actors and drivers, as consumers, bystanders and observers.",

"page_number": 1

},

{

"text": "Being curious about these **gender** dynamics, understanding them and taking them into account amplifies the effectiveness of conservation and wildlife protection.",

"page_number": 1

}

],

"case_studies": []

}

```

**Why this is CORRECT**: Every sentence is copied exactly from the source document. No introductory text, no summaries, no service offers. Just pure verbatim extraction with bold keywords.

\---

### Example 7: CORRECT output (Category E — Case study)

```json

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

```

**Why this is CORRECT**: For Type E (case studies), summarization is allowed in the `summary` field. This is the ONLY exception.

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
