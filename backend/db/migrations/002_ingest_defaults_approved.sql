-- Drop the human-approval gate for retrieval. New sources and chunks are
-- searchable as soon as ingest writes them. Reject and soft-delete still
-- hide a row. Already-applied 001 keeps DEFAULT 'pending' until this runs.

ALTER TABLE sources ALTER COLUMN status SET DEFAULT 'approved';
ALTER TABLE chunks ALTER COLUMN status SET DEFAULT 'approved';
