# Gender Reviewer Pipeline

A Railway-hosted FastAPI pipeline that downloads PDFs, OCRs them with Azure Document Intelligence,
extracts gender-related provisions per document using an LLM, and stores results in Supabase.
Supports two run modes:

- **`run=first`**: Download from URLs → upload to Vercel Blob → OCR → AI extract per doc → store in Supabase → return all extractions
- **`run=rerun`**: Pull unprocessed uploads from Supabase → download from Blob → OCR → AI extract → combine with previous results → return all extractions

## API

### POST `/api/pipeline/analyze`

```json
{
  "chat_id_topic": "climate-gender-2024",
  "links": ["https://example.com/doc1.pdf", "https://example.com/doc2.pdf"],
  "run": "first"
}
```

**Response:**

```json
{
  "chat_id_topic": "climate-gender-2024",
  "run": "first",
  "ai_extractions": [
    "Convention on Biological Diversity (CBD)...",
    "Paris Agreement (2015)..."
  ],
  "documents_processed": 2,
  "total_documents": 2,
  "undownloadable_links": [{"url": "...", "reason": "HTTP 403"}],
  "blob_links": [{"url": "https://blob.vercel-storage.com/...", "filename": "doc1.pdf"}],
  "ocr_errors": []
}
```

For `run=rerun`, omit `links`. The pipeline queries `uploads` WHERE `chat_id_topic = X AND processed = false`.

### GET `/health`

Returns `{"status": "healthy"}`.

## Supabase Schema

Run these SQL statements once in your Supabase project:

```sql
CREATE TABLE document_extractions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id_topic TEXT NOT NULL,
  filename TEXT NOT NULL,
  source_url TEXT,
  blob_url TEXT,
  ai_extraction TEXT NOT NULL,
  keywords TEXT[],
  processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_document_extractions_chat ON document_extractions(chat_id_topic);
CREATE INDEX idx_document_extractions_chat_processed ON document_extractions(chat_id_topic, processed_at DESC);

CREATE TABLE pipeline_results (
  chat_id_topic TEXT PRIMARY KEY,
  undownloadable_links JSONB DEFAULT '[]'::jsonb,
  blob_links JSONB DEFAULT '[]'::jsonb,
  last_run_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE uploads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id_topic TEXT NOT NULL,
  blob_url TEXT NOT NULL,
  filename TEXT NOT NULL,
  processed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_uploads_chat_unprocessed ON uploads(chat_id_topic, processed) WHERE processed = FALSE;
```

## Configuration

Copy `.env.local.example` to `.env.local` and fill in values:

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Yes | Azure OCR endpoint |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | Yes | Azure OCR key |
| `GPT54_API_KEY` | Yes | Azure AI Foundry key |
| `GPT54_ENDPOINT` | Yes | Azure AI Foundry responses URL |
| `AZURE_GPT54_DEPLOYMENT` | Yes | Deployment/model name |
| `AZURE_GPT54_API_VERSION` | Yes | API version header |
| `BLOB_READ_WRITE_TOKEN` | Yes | Vercel Blob token |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Supabase service role key |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: `*`) |
| `ES_HOST`, `ES_INDEX`, `ES_KEYWORD_INDEX` | No | Only for legacy sync/admin UI |

## Local Development

```bash
pip install -r requirements.txt
cp .env.local.example .env.local   # fill in values
uvicorn backend.main:app --reload  # API at http://localhost:8000
```

Run tests:

```bash
pytest tests/test_pipeline.py -v                  # unit tests (no credentials needed)
pytest tests/ -m integration -v                   # live tests (requires credentials)
```

## Deploy to Railway

See [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md).

## Upload Page (Separate Vercel App)

The `upload-page/` folder contains a Next.js app for users to upload PDFs for a given
`chat_id_topic`. See [upload-page/README.md](../upload-page/README.md).

## Legacy Features

The legacy Elasticsearch sync/admin UI and Airtable/Google Forms sources are still present
for backward compatibility. They require `ES_HOST` and respective source credentials.
See `registries/`, `sources/`, `main.py`, and the frontend in `frontend/`.
