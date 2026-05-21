# Railway Deployment Guide for Doc Indexer API

This guide explains how to deploy the Doc Indexer API to Railway.

## Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **Azure Document Intelligence**: You need an Azure subscription with Document Intelligence (Form Recognizer) service

## Setup Steps

### 1. Create Azure Document Intelligence Resource

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a new "Document Intelligence" or "Form Recognizer" resource
3. Note down:
   - **Endpoint**: `https://<your-resource>.cognitiveservices.azure.com/`
   - **Key**: Found under "Keys and Endpoint" section

### 2. Deploy to Railway

#### Option A: Via Railway CLI

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login to Railway
railway login

# Initialize project (from doc-indexer directory)
cd doc-indexer
railway init

# Add environment variables
railway variables set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="https://your-resource.cognitiveservices.azure.com"
railway variables set AZURE_DOCUMENT_INTELLIGENCE_KEY="your-key-here"

# Deploy
railway up
```

#### Option B: Via Railway Dashboard

1. Go to [railway.app/new](https://railway.app/new)
2. Select "Deploy from GitHub repo"
3. Connect your GitHub repository
4. Railway will auto-detect the Dockerfile
5. Add environment variables in the **Variables** tab:
   - `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`
   - `AZURE_DOCUMENT_INTELLIGENCE_KEY`
6. Deploy

### 3. Configure Environment Variables

In Railway dashboard, add these variables:

| Variable | Value | Required |
|----------|-------|----------|
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | Your Azure endpoint URL | Yes |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | Your Azure API key | Yes |
| `PORT` | (Auto-set by Railway) | No |
| `ES_HOST` | Elasticsearch URL (if using) | Optional |
| `ES_INDEX` | documents | Optional |
| `ES_KEYWORD_INDEX` | keyword_registry | Optional |

### 4. Test Your Deployment

Once deployed, Railway will provide a public URL (e.g., `https://your-app.railway.app`).

#### Test with URLs (POST /api/ocr/keyword-report)

```bash
curl -X POST "https://your-app.railway.app/api/ocr/keyword-report" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_urls": [
      "https://example.com/document.pdf"
    ],
    "keywords": ["woman", "gender"]
  }'
```

#### Test with File Upload (POST /api/ocr/keyword-report-upload)

```bash
curl -X POST "https://your-app.railway.app/api/ocr/keyword-report-upload" \
  -F "keywords=woman,gender" \
  -F "files=@/path/to/document.pdf"
```

#### Download Report (GET /api/ocr/download-report/{filename})

```bash
curl -O "https://your-app.railway.app/api/ocr/download-report/keyword_paragraph_report.docx"
```

## API Documentation

Once deployed, visit:
- **Interactive API Docs**: `https://your-app.railway.app/docs`
- **Alternative Docs**: `https://your-app.railway.app/redoc`

## API Endpoints

### 1. Process PDFs from URLs
**POST** `/api/ocr/keyword-report`

Request body:
```json
{
  "pdf_urls": ["https://example.com/doc1.pdf", "https://example.com/doc2.pdf"],
  "keywords": ["woman", "gender", "equality"]
}
```

Response:
```json
{
  "download_summary": {
    "downloaded": 2,
    "skipped": 0,
    "failed": 0
  },
  "ocr_summary": {
    "processed": 2,
    "failed": 0,
    "errors": []
  },
  "keyword_index": {
    "woman": [
      {
        "file": "doc1.pdf",
        "paragraph": "Text containing woman..."
      }
    ],
    "gender": [...]
  },
  "report_available": true,
  "report_filename": "keyword_paragraph_report.docx"
}
```

### 2. Process Uploaded PDF Files
**POST** `/api/ocr/keyword-report-upload`

Form data:
- `keywords`: Comma-separated string (e.g., "woman,gender,equality")
- `files`: One or more PDF files

### 3. Download Word Report
**GET** `/api/ocr/download-report/{filename}`

Downloads the generated Word document.

## Important Notes

### Request Timeouts
- Azure OCR can take **several minutes** for large PDFs
- Set client timeout to **5+ minutes** or use async polling pattern
- Railway free tier has a **100-second HTTP timeout**; consider upgrading for long OCR jobs

### Storage
- Downloaded PDFs and reports are stored in `/tmp` (ephemeral)
- Files are automatically cleaned up on container restart
- For persistent storage, integrate Railway volumes or external storage (S3)

### Costs
- **Railway**: Free tier includes 500 execution hours/month; $5/month Hobby plan for more
- **Azure Document Intelligence**: Pay-per-page OCR (~$1.50 per 1000 pages for Read API)

## Troubleshooting

### Azure Connection Errors
- Verify endpoint URL ends with `/` or remove trailing slash based on error
- Check API key is valid and not expired
- Ensure Azure resource region is accessible

### Long Request Timeouts
- For large PDFs, consider implementing a job queue (Celery, Redis)
- Use Railway's background workers for long-running tasks
- Implement webhook callbacks instead of synchronous responses

### File Upload Issues
- Railway has body size limits; for large files use URL download method
- Ensure `multipart/form-data` content type is set

## Next Steps

1. **Add Authentication**: Implement API keys or JWT tokens
2. **Rate Limiting**: Add rate limiting to prevent abuse
3. **Job Queue**: For production, use background workers (Celery + Redis)
4. **Monitoring**: Add logging and error tracking (Sentry, LogTail)
5. **Database**: Connect to Railway PostgreSQL for job history

## Support

For issues with:
- **Railway Deployment**: [Railway Docs](https://docs.railway.app)
- **Azure Document Intelligence**: [Azure Docs](https://learn.microsoft.com/azure/ai-services/document-intelligence/)
- **This API**: Check logs in Railway dashboard
