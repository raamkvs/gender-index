# LLM Prompt Fix Summary

## Problem Identified

The LLM was producing summarized output with conversational elements instead of verbatim extraction:
- Added introductory text like "This WWF brief explains why gender matters..."
- Created bullet-point summaries instead of extracting full paragraphs
- Added service offers like "If you want, I can also provide..."
- Paraphrased content instead of copying exact text from source

## Root Cause

The original prompt lacked:
1. Clear role definition establishing this as data extraction, not conversation
2. Comprehensive list of prohibited output patterns
3. Strong enforcement mechanism (e.g., Ctrl+F test)
4. Sufficient wrong examples showing what NOT to do
5. Validation checklist for self-checking
6. Explicit rules against conversational output

## Solution Implemented

Restructured the entire `DEFAULT_OUTPUT_SCHEMA` in `llm_client.py` (lines 17-365) with the following improvements:

### 1. Role Definition (NEW - Top of Prompt)
- Establishes the AI as a "DATA EXTRACTION TOOL, not a conversational assistant"
- Explicitly states what the AI does NOT do: write introductions, summarize, offer services
- Defines singular task: Copy text word-for-word into JSON

### 2. STRICTLY FORBIDDEN Section (NEW)
Created comprehensive banned patterns list:
- Prohibited introductory phrases: "This document explains...", "Key points:", etc.
- Prohibited summary formatting: bullet lists, numbered sections
- Prohibited service offers: "If you want, I can also provide..."
- Prohibited paraphrasing: ANY text not copied from source

### 3. Strengthened Step 3 Extraction Rules
Added critical enforcement mechanisms:
- **Ctrl+F test**: "Every sentence you write must be findable in the source using Ctrl+F"
- **Bold formatting is the ONLY modification allowed**
- If you cannot quote the exact sentence, do not include it
- Emphasized character-for-character copying

### 4. Validation Checklist (NEW)
Added internal checklist before output:
1. Ctrl+F test for every sentence
2. No introductory text
3. No bullet summaries
4. No service offers
5. No paraphrasing
6. JSON only

### 5. Enhanced Rules Section
- **Rule 10**: NEVER add introductory text, explanations, or offers
- **Rule 11**: Output only JSON object, no conversational text
- Strengthened Rule 6 with explicit definition: "VERBATIM means every word from the document, in the same order, with the same phrasing"

### 6. Multiple Wrong vs. Right Examples (NEW)
Added 7 examples (5 wrong, 2 correct):
- **Example 1**: CORRECT - Verbatim CBD paragraph
- **Example 2**: WRONG - Introductory text pattern
- **Example 3**: WRONG - Bullet-point summary
- **Example 4**: WRONG - Service offer
- **Example 5**: WRONG - Paraphrasing
- **Example 6**: CORRECT - Verbatim from actual CITES document
- **Example 7**: CORRECT - Case study (exception)

Each wrong example includes explanation of why it's wrong.

## New Prompt Structure

1. **Role Definition** - Establishes extraction-only mode
2. **STRICTLY FORBIDDEN** - Comprehensive banned patterns
3. **Step 1** - Document type classification
4. **Step 2** - Keyword application
5. **Step 3** - VERBATIM extraction (with Ctrl+F test)
6. **Step 3-alt** - Case study (exception noted)
7. **Step 4** - Page numbers
8. **Validation Checklist** - Self-checking before output
9. **Output Format** - Enhanced rules (10-11 added)
10. **Examples** - Multiple wrong/right patterns

## Expected Impact

The restructured prompt should eliminate:
- ❌ Introductory/explanatory text
- ❌ Bullet-point summaries
- ❌ Service offers
- ❌ Paraphrasing

And produce:
- ✅ Pure JSON output
- ✅ Verbatim text extraction
- ✅ Bold keywords only
- ✅ No conversational elements

## Testing

All 28 tests in `test_pipeline.py` pass successfully with the new prompt.

## Files Modified

- `doc-indexer/llm_client.py` - Lines 17-365 (entire `DEFAULT_OUTPUT_SCHEMA`)
  - Previous prompt: 193 lines
  - New prompt: 349 lines (80% increase in specificity)

## Comparison: Original Document vs. Previous Output

**Original Text (lines 27-35 from CITES PDF):**
```
Men and women don't necessarily have the same access to
resources including land, control over resources, and economic
opportunities to shift away from wildlife use.
Men and women also play different roles in the trade as actors and
drivers, as consumers, bystanders and observers.
```

**Previous LLM Output (WRONG):**
```
This WWF brief explains why gender matters to CITES and wildlife trade policy.
Key points:
- Wildlife trade is gender-differentiated. - Men and women often have different access to land,
resources, and alternative livelihoods...
```

**Expected New Output (CORRECT):**
```json
{
  "relevant_paragraphs": [
    {
      "text": "Men and **women** don't necessarily have the same access to resources including land, control over resources, and economic opportunities to shift away from wildlife use.",
      "page_number": 1
    },
    {
      "text": "Men and **women** also play different roles in the trade as actors and drivers, as consumers, bystanders and observers.",
      "page_number": 1
    }
  ]
}
```

## Key Improvements

1. **Role clarity**: AI now knows it's a tool, not an assistant
2. **Explicit prohibitions**: Clear list of what NOT to do
3. **Verification mechanism**: Ctrl+F test for every sentence
4. **Self-checking**: Validation checklist before output
5. **Strong examples**: Multiple wrong patterns demonstrated
6. **Enforcement**: Rules 10-11 explicitly forbid conversational output
