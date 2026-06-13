# Gender Reviewer Pipeline API Documentation Summary

## Overview

The Gender Reviewer Pipeline uses a two-step async pattern:
1. **Start Job API** (`POST /api/pipeline/analyze`) - Unchanged
2. **Poll Status API** (`GET /health`) - **Updated with `report_pdf_url`**

---

## API 1: Start Job (Unchanged)

**Endpoint:** `POST /api/pipeline/analyze`  
**Server:** `https://gender-index-production.up.railway.app`

### Request Body

```json
{
  "chat_id_topic": "session-id-here",
  "run": "first",
  "links": ["https://example.org/policy.pdf"],
  "output_schema_hint": null,
  "download_timeout": 180
}
```

### Response (202 Accepted)

```json
{
  "status": "accepted",
  "chat_id_topic": "session-id-here",
  "message": "Pipeline request accepted. Poll /health?chat_id=session-id-here for status.",
  "poll_interval_seconds": 10
}
```

**No changes to this API.**

---

## API 2: Poll Status (Updated)

**Endpoint:** `GET /health?chat_id={chat_id_topic}`  
**Server:** `https://gender-index-production.up.railway.app`

### Response Structure

#### While Processing
```json
{
  "status": "in_progress",
  "chat_id_topic": "session-id-here",
  "comments": "wait"
}
```

#### When Completed (New Structure)

```json
{
  "status": "completed",
  "chat_id_topic": "session-id-here",
  "comments": "Pipeline completed successfully",
  "result": {
    "chat_id_topic": "session-id-here",
    "run": "first",
    "report_pdf_url": "https://blob.vercel-storage.com/report.pdf",
    "ai_extractions": [
      "Gender Reviewer Report — Download PDF: https://blob.vercel-storage.com/report.pdf",
      "Document 1 extraction text...",
      "Document 2 extraction text..."
    ],
    "documents_processed": 2,
    "total_documents": 2,
    "undownloadable_links": [],
    "blob_links": [
      {"url": "https://blob.vercel-storage.com/doc1.pdf", "filename": "doc1.pdf"}
    ],
    "ocr_errors": []
  }
}
```

### What's New

**Added field:** `result.report_pdf_url`
- Type: `string` (URI) or `null`
- Description: Direct URL to the generated PDF report
- This is the primary field for accessing the report download link

**Updated field:** `result.ai_extractions`
- First entry (`ai_extractions[0]`) now contains the PDF download link in format: `"Gender Reviewer Report — Download PDF: {url}"`
- Remaining entries (`ai_extractions[1:]`) contain per-document extractions
- This dual approach supports both direct API access (`report_pdf_url`) and chatbot compatibility (`ai_extractions[0]`)

---

## Field Reference

### `result` object properties

| Field | Type | Description | New/Changed |
|-------|------|-------------|-------------|
| `chat_id_topic` | string | Session identifier | Unchanged |
| `run` | string | "first" or "rerun" | Unchanged |
| **`report_pdf_url`** | **string \| null** | **Direct PDF download URL** | **✨ NEW** |
| `ai_extractions` | string[] | PDF link + document extractions | **📝 Modified** |
| `documents_processed` | integer | Docs processed this run | Unchanged |
| `total_documents` | integer | Total extractions stored | Unchanged |
| `undownloadable_links` | array | Failed downloads | Unchanged |
| `blob_links` | array | Uploaded PDF URLs | Unchanged |
| `ocr_errors` | array | OCR failures | Unchanged |

---

## Usage Patterns

### For Direct API Consumers
Use `result.report_pdf_url` to get the PDF download link:

```javascript
if (response.result.report_pdf_url) {
  window.open(response.result.report_pdf_url);
}
```

### For Chatbots (Copilot, etc.)
Read from `result.ai_extractions[0]`:

```javascript
const pdfEntry = response.result.ai_extractions[0];
if (pdfEntry.includes("Download PDF:")) {
  const url = pdfEntry.split("Download PDF: ")[1];
  // Use url...
}
```

### For Summaries
Use `result.ai_extractions.slice(1)` for document content:

```javascript
const documentExtractions = response.result.ai_extractions.slice(1);
documentExtractions.forEach(extraction => {
  // Process each document's content...
});
```

---

## Complete OpenAPI Specs

- **Start Job API:** [`gender-reviewer-api.openapi.yaml`](./gender-reviewer-api.openapi.yaml)
- **Poll Status API:** [`gender-reviewer-status-api.openapi.yaml`](./gender-reviewer-status-api.openapi.yaml)

---

## Migration Notes

**Backward Compatibility:** ✅ Full backward compatibility maintained
- Existing clients that read `ai_extractions` will continue to work
- The PDF link is still present in `ai_extractions[0]`
- New clients can use `report_pdf_url` for cleaner access

**No Breaking Changes:** All existing fields remain unchanged
