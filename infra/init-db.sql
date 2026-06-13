-- Enable pgvector extension for vector storage.
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify pgvector is available during initialization.
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- Optional sample vector table for local smoke testing.
-- CREATE TABLE IF NOT EXISTS sample_vectors (
--     id bigserial PRIMARY KEY,
--     embedding vector(1536),
--     metadata jsonb
-- );
