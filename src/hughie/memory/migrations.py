DDL = """
CREATE TABLE IF NOT EXISTS brain_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'fact',
    embedding vector(768),
    importance FLOAT DEFAULT 1.0,
    status VARCHAR(20) DEFAULT 'active',
    source_kind VARCHAR(30) DEFAULT 'auto_worker',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS source_kind VARCHAR(30) DEFAULT 'auto_worker';
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS brain_notes_title_lower_idx ON brain_notes ((lower(title)));

CREATE TABLE IF NOT EXISTS brain_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_note_id UUID NOT NULL REFERENCES brain_notes(id) ON DELETE CASCADE,
    target_kind VARCHAR(20) NOT NULL,
    target_note_id UUID REFERENCES brain_notes(id) ON DELETE CASCADE,
    target_path TEXT,
    relation_type VARCHAR(50) DEFAULT 'related_to',
    weight FLOAT DEFAULT 1.0,
    evidence JSONB DEFAULT '{}'::jsonb,
    created_by VARCHAR(20) DEFAULT 'worker',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT brain_links_target_check CHECK (
        (target_kind = 'note' AND target_note_id IS NOT NULL AND target_path IS NULL)
        OR
        (target_kind IN ('file', 'directory') AND target_note_id IS NULL AND target_path IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS brain_links_source_note_idx ON brain_links (source_note_id);
CREATE INDEX IF NOT EXISTS brain_links_target_note_idx ON brain_links (target_note_id);
CREATE INDEX IF NOT EXISTS brain_links_target_path_idx ON brain_links (target_path);

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
