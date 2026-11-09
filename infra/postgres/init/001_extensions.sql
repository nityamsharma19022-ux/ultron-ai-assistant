-- Runs once, the first time the local ULTRON Postgres volume is created.
-- Only enables extensions; ULTRON's tables will come from versioned
-- migrations so the same schema can be applied to a Supabase project later.
-- Both extensions are available on Supabase too.

CREATE EXTENSION IF NOT EXISTS vector;   -- embeddings for assistant memory
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fuzzy text search
