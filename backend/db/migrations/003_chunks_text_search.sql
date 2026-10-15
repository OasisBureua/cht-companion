-- Keyword half of hybrid retrieval. Exact names such as "DB-12" or a drug
-- name match here even when vector search ranks those chunks low.
-- Generated, so ingest never writes it and existing rows fill on ALTER.

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS text_search tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(title, '') || ' ' || text)) STORED;

CREATE INDEX IF NOT EXISTS chunks_text_search_gin ON chunks USING GIN (text_search);
