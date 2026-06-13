-- Create generated_documents table for PDF report tracking
-- Run this in Supabase SQL Editor or via psql

CREATE TABLE IF NOT EXISTS generated_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id_topic TEXT NOT NULL,
  blob_url TEXT NOT NULL,
  filename TEXT NOT NULL,
  document_count INT NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index for faster lookups by chat_id_topic
CREATE INDEX IF NOT EXISTS idx_generated_documents_chat_id 
ON generated_documents(chat_id_topic);

-- Optional: Add comment to describe the table
COMMENT ON TABLE generated_documents IS 'Stores metadata for generated PDF reports from the Gender Reviewer pipeline';
