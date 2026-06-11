# Railway Deployment — Gender Reviewer Pipeline

## Prerequisites

1. A [Railway](https://railway.app) account connected to this GitHub repo
2. A Supabase project with the three tables created (see below)
3. A Vercel Blob store with a `BLOB_READ_WRITE_TOKEN`
4. Azure Document Intelligence resource (OCR)
5. Azure AI Foundry resource (GPT54)

## Step 1: Create Supabase Tables

In your Supabase project → SQL editor, run:

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

## Step 2: Set Environment Variables in Railway

In your Railway project → Variables tab, add:

| Variable | Description | Required |
|----------|-------------|----------|
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Azure OCR endpoint URL | Yes |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | Azure OCR API key | Yes |
| `GPT54_API_KEY` | Azure AI Foundry key | Yes |
| `GPT54_ENDPOINT` | Azure AI Foundry responses URL | Yes |
| `AZURE_GPT54_DEPLOYMENT` | Model deployment name | Yes |
| `AZURE_GPT54_API_VERSION` | API version | Yes |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob `vercel_blob_rw_...` token | Yes |
| `SUPABASE_URL` | `https://xxx.supabase.co` | Yes |
| `SUPABASE_KEY` | Supabase service role key | Yes |
| `CORS_ORIGINS` | Comma-separated allowed origins (default: `*`) | No |
| `PORT` | Auto-set by Railway | No |

**Note:** Elasticsearch (`ES_HOST` etc.) is **not required** for the Gender Reviewer pipeline.
In-memory keyword search is used instead. Elasticsearch is only needed for the legacy sync/admin UI.

## Step 3: Deploy

```bash
# Via Railway CLI
npm i -g @railway/cli
railway login
cd doc-indexer
railway up
```

Or push to your connected GitHub branch — Railway deploys automatically.

## Step 4: Verify

```bash
# Health check
curl https://your-app.railway.app/health

# First run (returns ai_extractions + blob_links + undownloadable_links)
curl -X POST https://your-app.railway.app/api/pipeline/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id_topic": "climate-gender-2024",
    "links": ["https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"],
    "run": "first"
  }'

# Rerun (processes unprocessed uploads for this chat_id_topic)
curl -X POST https://your-app.railway.app/api/pipeline/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id_topic": "climate-gender-2024",
    "run": "rerun"
  }'
```

## Interactive Docs

- `https://your-app.railway.app/docs` — Swagger UI
- `https://your-app.railway.app/redoc` — ReDoc

## Architecture Notes

- **File storage**: Vercel Blob (not Google Drive, not Railway local storage)
- **State / AI results**: Supabase (`document_extractions`, `pipeline_results`, `uploads` tables)
- **Search**: In-memory keyword search over OCR paragraphs (no Elasticsearch needed)
- **Pipeline endpoint**: `POST /api/pipeline/analyze` — called by the chatbot
- **Upload page**: Separate Vercel app (`upload-page/`) — stores user files in Blob + Supabase, then chatbot triggers `run=rerun`

## Troubleshooting

**OCR timeouts**: Azure OCR can take several minutes for large PDFs. Railway Hobby plan is
recommended to avoid the 100-second free-tier timeout.

**Blob upload failures**: Check `BLOB_READ_WRITE_TOKEN` is set correctly in Railway.

**Supabase errors**: Confirm `SUPABASE_URL` starts with `https://` and `SUPABASE_KEY` is
the **service role** key (not the anon/public key) so it bypasses Row Level Security.
