DDL = """
CREATE TABLE IF NOT EXISTS brain_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'fact',
    embedding vector(768),
    importance FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS conversations_session_id_idx ON conversations (session_id);
CREATE INDEX IF NOT EXISTS conversations_created_at_idx ON conversations (created_at);

CREATE TABLE IF NOT EXISTS consolidation_state (
    session_id TEXT PRIMARY KEY,
    last_processed_at TIMESTAMPTZ DEFAULT now()
);
"""
