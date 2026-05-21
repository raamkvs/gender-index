# Doc Indexer

Incremental indexer for Elasticsearch. Pulls documents from multiple sources and indexes only what's new.

## Sources

| Source        | Location                              | Notes                                                       |
| ------------- | ------------------------------------- | ----------------------------------------------------------- |
| JSON registry | `registries/documents.json`           | Hand-edited list of docs (`doc_id`, `title`, ...).          |
| Airtable      | Airtable API (configured via env)     | Pulls attachments, downloads + OCRs each PDF.               |
| Google Forms  | Forms + Drive APIs (service account)  | Reads file-upload answers, downloads from Drive, OCRs them. |

`StateTracker` (`state/indexed_state.json`) dedupes by `doc_id` across all sources, so repeat syncs only OCR newly added Airtable attachments.

## Run

```bash
# Start Elasticsearch
docker-compose up -d

# CLI sync (reads registries/ + Airtable)
python main.py sync
python main.py status
python main.py reindex --doc-id airtable_recXXX_attYYY
python main.py reindex --all

# Web UI
cd backend && pip install fastapi uvicorn && uvicorn main:app --reload
cd frontend && npm install && npm run dev
# Open http://localhost:5173
```

## Configuration

`.env` (committed defaults):

```
ES_HOST=http://localhost:9200
ES_INDEX=documents
ES_KEYWORD_INDEX=keyword_registry
```

`.env.local` (secrets, gitignored):

```
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=...
AZURE_DOCUMENT_INTELLIGENCE_KEY=...

AIRTABLE_PAT=pat...
AIRTABLE_BASE_ID=app...
AIRTABLE_TABLE_NAME=docs1
AIRTABLE_ATTACHMENT_FIELD=Attachments   # default
AIRTABLE_TITLE_FIELD=                   # optional, defaults to "Name" then record id
AIRTABLE_KEYWORDS_FIELD=                # optional, multi-select / comma list

GOOGLE_APPLICATION_CREDENTIALS=.gcp-credentials.json   # path to service account JSON
GOOGLE_FORM_ID=1no-yFEhXhKyT0Fkvjn3Shv6ruCDjMnPNRht82R4NTSQ
```

Sources are independently optional — if env vars are missing, that source is silently disabled and `sync` proceeds with the remaining sources.

### Google Forms one-time setup

1. In Google Cloud Console, enable **Google Forms API** and **Google Drive API** on the project that owns the service account.
2. Open the form, click **Add collaborators**, and add the service account email (e.g. `ram-kvs@gender-undp.iam.gserviceaccount.com`) with **Editor** access. Without this, the API returns `PERMISSION_DENIED`.
3. Save the service account JSON key to `doc-indexer/.gcp-credentials.json` (gitignored). Do not paste the contents anywhere else.
4. Add `GOOGLE_APPLICATION_CREDENTIALS=.gcp-credentials.json` and `GOOGLE_FORM_ID=<id>` to `.env.local`.

## doc_id schemes

Each external file becomes one ES document with a stable id so repeat syncs dedup correctly:

| Source        | doc_id format                                  | Local cache path                                    |
| ------------- | ---------------------------------------------- | --------------------------------------------------- |
| Airtable      | `airtable_{record_id}_{attachment_id}`         | `downloads/airtable/{record_id}/{filename}`         |
| Google Forms  | `gform_{response_id}_{file_id}`                | `downloads/google_forms/{response_id}/{filename}`   |

Common doc shape after ingestion:

```
title    = file name (or record/question title)
content  = OCR'd paragraphs joined with blank lines
source   = file URL (Airtable CDN or Drive view link)
origin   = "airtable" | "google_forms"
```

Downloaded files are cached locally so re-runs don't re-download.
