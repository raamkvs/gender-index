# PDF Report Feature Deployment Checklist

## 1. Supabase Setup

### Create the `generated_documents` table:
Run the SQL in `create_generated_documents_table.sql` in your Supabase SQL Editor

```sql
CREATE TABLE generated_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id_topic TEXT NOT NULL,
  blob_url TEXT NOT NULL,
  filename TEXT NOT NULL,
  document_count INT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_generated_documents_chat_id ON generated_documents(chat_id_topic);
```

## 2. Vercel Blob Setup

You mentioned you already have:
- ✅ BLOB_STORE_ID_DOC_GENERATED
- ✅ BLOB_READ_WRITE_TOKEN__DOC_GENERATED

## 3. Railway Environment Variables

Add these environment variables in Railway Dashboard → Your Service → Variables:

```bash
BLOB_STORE_ID_DOC_GENERATED=<your-store-id>
BLOB_READ_WRITE_TOKEN__DOC_GENERATED=<your-token>
```

## 4. Deploy to Railway

### Option A: Git Push (if connected to GitHub)
```bash
git add .
git commit -m "Add PDF report generation feature"
git push origin main
```

Railway will automatically:
- Detect changes
- Install `reportlab>=4.0.0` from requirements.txt
- Deploy the new code

### Option B: Railway CLI
```bash
railway up
```

## 5. Verify Deployment

After deployment:

1. **Check logs** in Railway Dashboard for any errors
2. **Test the pipeline**:
   - Run a pipeline with `POST /api/pipeline/analyze`
   - Poll with `GET /health?chat_id={chat_id_topic}`
   - Verify the response includes `generated_pdf_url`

3. **Check Supabase**:
   - Verify row was created in `generated_documents` table
   - Confirm `blob_url` is populated

4. **Test PDF download**:
   - Open the `generated_pdf_url` in a browser
   - Verify PDF contains expected content

## 6. Rollback Plan (if needed)

If something goes wrong:
```bash
git revert HEAD
git push origin main
```

Or use Railway Dashboard → Deployments → Rollback to previous version
