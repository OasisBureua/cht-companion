-- SCRUM-196 / CHAT-3 — KB schema rev 2 (pgvector on cht-companion-db)
-- Apply once per database. Idempotent where possible (IF NOT EXISTS).

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    source_type      TEXT NOT NULL,
    title            TEXT NOT NULL,
    url              TEXT NOT NULL,
    playlist_url     TEXT,
    external_id      TEXT,
    doctors          TEXT[] NOT NULL DEFAULT '{}',
    topics           TEXT[] NOT NULL DEFAULT '{}',
    content_date     DATE,
    status           TEXT NOT NULL DEFAULT 'pending',
    approved_by      TEXT,
    approved_at      TIMESTAMPTZ,
    rejected_by      TEXT,
    rejected_at      TIMESTAMPTZ,
    rejected_reason  TEXT,
    uploaded_by      TEXT,
    chunk_count      INTEGER NOT NULL DEFAULT 0,
    embedding_model  TEXT NOT NULL,
    source_hash      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version          INTEGER NOT NULL DEFAULT 1,
    last_ingested_at TIMESTAMPTZ,
    CONSTRAINT sources_source_type_chk
      CHECK (source_type IN ('youtube_caption', 'catalog_clip', 'curated_doc')),
    CONSTRAINT sources_status_chk
      CHECK (status IN ('pending', 'approved', 'rejected', 'soft_deleted'))
);

CREATE INDEX IF NOT EXISTS sources_status_idx       ON sources(status);
CREATE INDEX IF NOT EXISTS sources_source_type_idx  ON sources(source_type);
CREATE INDEX IF NOT EXISTS sources_content_date_idx ON sources(content_date);
CREATE INDEX IF NOT EXISTS sources_doctors_gin      ON sources USING GIN(doctors);
CREATE INDEX IF NOT EXISTS sources_topics_gin       ON sources USING GIN(topics);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id           TEXT PRIMARY KEY,
    source_id          TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    source_type        TEXT NOT NULL,
    chunk_index        INTEGER NOT NULL,
    text               TEXT NOT NULL,
    text_length        INTEGER NOT NULL,
    embedding          vector(1024) NOT NULL,
    speaker            TEXT,
    speakers_in_chunk  TEXT[] NOT NULL DEFAULT '{}',
    timestamp_start    INTEGER,
    timestamp_end      INTEGER,
    duration_seconds   INTEGER,
    title              TEXT NOT NULL,
    url                TEXT NOT NULL,
    playlist_url       TEXT,
    doctors            TEXT[] NOT NULL DEFAULT '{}',
    topics             TEXT[] NOT NULL DEFAULT '{}',
    content_date       DATE,
    status             TEXT NOT NULL DEFAULT 'pending',
    approved_by        TEXT,
    approved_at        TIMESTAMPTZ,
    rejected_by        TEXT,
    rejected_at        TIMESTAMPTZ,
    rejected_reason    TEXT,
    embedding_model    TEXT NOT NULL,
    chunk_hash         TEXT NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chunks_source_type_chk
      CHECK (source_type IN ('youtube_caption', 'catalog_clip', 'curated_doc')),
    CONSTRAINT chunks_status_chk
      CHECK (status IN ('pending', 'approved', 'rejected', 'soft_deleted')),
    CONSTRAINT chunks_source_chunk_uq
      UNIQUE (source_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_source_id_idx ON chunks(source_id);
CREATE INDEX IF NOT EXISTS chunks_status_idx    ON chunks(status);
CREATE INDEX IF NOT EXISTS chunks_doctors_gin   ON chunks USING GIN(doctors);
CREATE INDEX IF NOT EXISTS chunks_topics_gin    ON chunks USING GIN(topics);

-- HNSW cosine index (SCRUM-196 §5.3). IF NOT EXISTS requires PG 9.5+; index create is safe to re-run once.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx ON chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 128);

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    triggered_by    TEXT,
    chunks_before   INTEGER,
    chunks_after    INTEGER,
    chunks_skipped  INTEGER,
    error_message   TEXT,
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    CONSTRAINT ingest_jobs_kind_chk
      CHECK (kind IN ('initial', 'reindex', 'refresh')),
    CONSTRAINT ingest_jobs_status_chk
      CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);

CREATE INDEX IF NOT EXISTS ingest_jobs_source_id_idx ON ingest_jobs(source_id);
CREATE INDEX IF NOT EXISTS ingest_jobs_status_idx    ON ingest_jobs(status);
CREATE INDEX IF NOT EXISTS ingest_jobs_queued_at_idx ON ingest_jobs(queued_at DESC);
