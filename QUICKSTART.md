# Doc Indexer API - Quick Start Guide

This guide will help you get the keyword OCR API running locally and deployed to Railway.

## What This API Does

The Doc Indexer API extracts text from PDF documents using Azure Document Intelligence (OCR) and finds paragraphs containing specific keywords. It can:

1. **Download PDFs from URLs** and process them
2. **Accept uploaded PDF files** via multipart form data
3. **Extract paragraphs** using Azure OCR
4. **Index keywords** in the extracted text
5. **Generate Word reports** with keyword matches

## Prerequisites

- Python 3.11+
- Azure Document Intelligence resource (see setup below)
- Railway account (for deployment)

## Local Development Setup

### 1. Install Dependencies

```bash
cd doc-indexer
pip install -r requirements.txt
```

### 2. Configure Azure Document Intelligence

Create `.env.local` file:

```bash
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key-here
```

**Get Azure credentials:**
1. Go to [Azure Portal](https://portal.azure.com)
2. Create "Document Intelligence" resource
3. Copy endpoint and key from "Keys and Endpoint" section

### 3. Run the API Locally

```bash
# From doc-indexer directory
uvicorn backend.main:app --reload --port 8000
```

The API will be available at:
- API: `http://localhost:8000`
- Interactive docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### 4. Test the API

#### Option A: Using the Interactive Docs

1. Open `http://localhost:8000/docs` in your browser
2. Navigate to `/api/ocr/keyword-report` endpoint
3. Click "Try it out"
4. Enter your request:
```json
{
  "pdf_urls": [
    "https://ulii.org/akn/ug/act/2015/3/eng%402015-03-06.pdf"
  ],
  "keywords": ["woman", "gender"]
}
```
5. Click "Execute"

#### Option B: Using cURL

```bash
# Process PDFs from URLs
curl -X POST "http://localhost:8000/api/ocr/keyword-report" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_urls": ["https://example.com/document.pdf"],
    "keywords": ["woman", "gender"]
  }'

# Upload PDF files
curl -X POST "http://localhost:8000/api/ocr/keyword-report-upload" \
  -F "keywords=woman,gender" \
  -F "files=@document.pdf"

# Download generated report
curl -O "http://localhost:8000/api/ocr/download-report/keyword_paragraph_report.docx"
```

#### Option C: Using the Example Client

```bash
# Edit example_api_client.py to set your API URL
python example_api_client.py
```

## Deploy to Railway

### Quick Deploy (5 minutes)

1. **Push to GitHub**
```bash
git add .
git commit -m "Add OCR API endpoints"
git push
```

2. **Deploy on Railway**
   - Go to [railway.app/new](https://railway.app/new)
   - Click "Deploy from GitHub repo"
   - Select your repository
   - Railway auto-detects the Dockerfile

3. **Add Environment Variables**
   
   In Railway dashboard → Variables tab:
   ```
   AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com
   AZURE_DOCUMENT_INTELLIGENCE_KEY=your-azure-key
   ```

4. **Deploy**
   - Railway automatically builds and deploys
   - You'll get a URL like `https://your-app.railway.app`

5. **Test**
```bash
curl https://your-app.railway.app/health
```

See [RAILWAY_DEPLOY.md](./RAILWAY_DEPLOY.md) for detailed deployment instructions.

## API Endpoints

### 1. Health Check
```
GET /health
```

Returns API status.

### 2. Process PDFs from URLs
```
POST /api/ocr/keyword-report
```

**Request:**
```json
{
  "pdf_urls": ["https://example.com/doc.pdf"],
  "keywords": ["woman", "gender", "equality"]
}
```

**Response:**
```json
{
  "download_summary": {
    "downloaded": 1,
    "skipped": 0,
    "failed": 0
  },
  "ocr_summary": {
    "processed": 1,
    "failed": 0,
    "errors": []
  },
  "keyword_index": {
    "woman": [
      {
        "file": "doc.pdf",
        "paragraph": "Full paragraph text..."
      }
    ]
  },
  "report_available": true,
  "report_filename": "keyword_paragraph_report.docx"
}
```

### 3. Upload and Process PDFs
```
POST /api/ocr/keyword-report-upload
```

**Form Data:**
- `keywords`: Comma-separated string (e.g., "woman,gender")
- `files`: One or more PDF files

### 4. Download Report
```
GET /api/ocr/download-report/{filename}
```

Downloads the generated Word document with keyword matches.

## How It Works

```
┌─────────────────┐
│  Client/Tool    │
│  (Your App)     │
└────────┬────────┘
         │
         │ HTTP POST /api/ocr/keyword-report
         │ { pdf_urls: [...], keywords: [...] }
         │
         ▼
┌─────────────────────────────────────────┐
│         Doc Indexer API                 │
│  (Railway - your-app.railway.app)       │
│                                         │
│  1. Download PDFs from URLs             │
│     OR receive uploaded files           │
│                                         │
│  2. Send PDFs to Azure ────────────►    │
│                                         │
│  3. ◄──────── OCR Results               │
│     (paragraphs extracted)              │
│                                         │
│  4. Index keywords in paragraphs        │
│                                         │
│  5. Generate Word report                │
│                                         │
│  6. Return JSON response                │
└─────────┬───────────────────────────────┘
          │
          ▼
     JSON Response
     + Optional Report Download
```

## Using from Another Tool

### Python Example

```python
import requests

API_URL = "https://your-app.railway.app"

# Process PDFs
response = requests.post(
    f"{API_URL}/api/ocr/keyword-report",
    json={
        "pdf_urls": ["https://example.com/doc.pdf"],
        "keywords": ["climate", "sustainability"]
    },
    timeout=300  # 5 minutes for OCR
)

result = response.json()
print(f"Found {len(result['keyword_index']['climate'])} matches for 'climate'")

# Download report
if result['report_available']:
    report = requests.get(
        f"{API_URL}/api/ocr/download-report/{result['report_filename']}"
    )
    with open("report.docx", "wb") as f:
        f.write(report.content)
```

### JavaScript Example

```javascript
const API_URL = "https://your-app.railway.app";

async function processDocuments() {
  const response = await fetch(`${API_URL}/api/ocr/keyword-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      pdf_urls: ["https://example.com/doc.pdf"],
      keywords: ["climate", "sustainability"]
    })
  });
  
  const result = await response.json();
  console.log("Keyword matches:", result.keyword_index);
  
  // Download report
  if (result.report_available) {
    const reportUrl = `${API_URL}/api/ocr/download-report/${result.report_filename}`;
    window.open(reportUrl);
  }
}
```

## Important Considerations

### Timeouts
- Azure OCR can take **1-5 minutes per PDF**
- Set HTTP client timeout to **5+ minutes**
- Consider async pattern for multiple large PDFs

### Rate Limits
- Azure Document Intelligence has rate limits (15 requests/minute on free tier)
- Implement retry logic with exponential backoff
- Consider queuing for batch processing

### Costs
- **Railway**: $5/month for Hobby plan (free tier: 500 hours)
- **Azure OCR**: ~$1.50 per 1,000 pages (Read API)

### Security
- Add API authentication (API keys, JWT) before production
- Railway URL is public by default
- Don't expose Azure credentials to clients

## Troubleshooting

### "Azure configuration error"
- Check environment variables are set in Railway
- Verify Azure endpoint URL format
- Test Azure key in Azure Portal

### "Request timed out"
- Increase client timeout (300+ seconds)
- Check PDF file size (large files take longer)
- Verify Azure OCR service is responding

### "No compatible analyze endpoint found"
- Azure endpoint URL may be wrong
- Check Azure resource region
- Verify API version compatibility

## Next Steps

- [ ] Add API authentication
- [ ] Implement rate limiting
- [ ] Add webhook support for async processing
- [ ] Set up monitoring and logging
- [ ] Create admin dashboard

## Support

- **Railway Issues**: [Railway Docs](https://docs.railway.app)
- **Azure Issues**: [Azure Support](https://learn.microsoft.com/azure/ai-services/document-intelligence/)
- **API Docs**: Visit `/docs` on your deployed URL
