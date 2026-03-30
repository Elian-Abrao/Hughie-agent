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
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS fonte VARCHAR(30) DEFAULT 'input_manual';
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS confianca FLOAT DEFAULT 0.3;
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS peso_temporal FLOAT DEFAULT 1.0;
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS criado_por TEXT DEFAULT 'system';
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS ultima_atualizacao TIMESTAMPTZ DEFAULT now();
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS historico JSONB DEFAULT '[]'::jsonb;
ALTER TABLE brain_notes ADD COLUMN IF NOT EXISTS metadados JSONB DEFAULT '{}'::jsonb;

UPDATE brain_notes
SET
    fonte = COALESCE(fonte, 'input_manual'),
    confianca = COALESCE(confianca, 0.3),
    peso_temporal = COALESCE(peso_temporal, 1.0),
    criado_por = COALESCE(criado_por, source_kind, 'system'),
    ultima_atualizacao = COALESCE(ultima_atualizacao, updated_at, now()),
    historico = COALESCE(historico, '[]'::jsonb),
    metadados = COALESCE(metadados, metadata, '{}'::jsonb);

CREATE UNIQUE INDEX IF NOT EXISTS brain_notes_title_lower_idx ON brain_notes ((lower(title)));
CREATE INDEX IF NOT EXISTS brain_notes_type_confidence_idx ON brain_notes (type, confianca DESC);
CREATE INDEX IF NOT EXISTS brain_notes_source_idx ON brain_notes (fonte);
CREATE INDEX IF NOT EXISTS brain_notes_temporal_weight_idx ON brain_notes (peso_temporal DESC);
CREATE INDEX IF NOT EXISTS brain_notes_last_updated_idx ON brain_notes (ultima_atualizacao DESC);

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
ALTER TABLE brain_links ADD COLUMN IF NOT EXISTS tipo_relacao VARCHAR(50) DEFAULT 'referencia';
ALTER TABLE brain_links ADD COLUMN IF NOT EXISTS confianca FLOAT DEFAULT 0.3;
ALTER TABLE brain_links ADD COLUMN IF NOT EXISTS fonte VARCHAR(30) DEFAULT 'input_manual';
ALTER TABLE brain_links ADD COLUMN IF NOT EXISTS criado_em TIMESTAMPTZ DEFAULT now();

UPDATE brain_links
SET
    tipo_relacao = COALESCE(tipo_relacao, relation_type, 'referencia'),
    confianca = COALESCE(confianca, 0.3),
    fonte = COALESCE(fonte, 'input_manual'),
    criado_em = COALESCE(criado_em, created_at, now());

CREATE INDEX IF NOT EXISTS brain_links_relation_type_idx ON brain_links (tipo_relacao);
CREATE INDEX IF NOT EXISTS brain_links_source_idx ON brain_links (fonte);
CREATE INDEX IF NOT EXISTS brain_links_confidence_idx ON brain_links (confianca DESC);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS conversations_session_id_idx ON conversations (session_id);
CREATE INDEX IF NOT EXISTS conversations_created_at_idx ON conversations (created_at);

CREATE TABLE IF NOT EXISTS consolidation_state (
    session_id TEXT PRIMARY KEY,
    last_processed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    tarefa TEXT NOT NULL,
    resultado TEXT NOT NULL,
    tempo_total_segundos INT,
    arquivos_modificados JSONB DEFAULT '[]'::jsonb,
    decisoes_tomadas JSONB DEFAULT '[]'::jsonb,
    erros_encontrados JSONB DEFAULT '[]'::jsonb,
    aprendizados JSONB DEFAULT '[]'::jsonb,
    node_ids_afetados JSONB DEFAULT '[]'::jsonb,
    embedding vector(768)
);

CREATE INDEX IF NOT EXISTS episodes_session_id_idx ON episodes (session_id);
CREATE INDEX IF NOT EXISTS episodes_created_at_idx ON episodes (created_at DESC);

CREATE TABLE IF NOT EXISTS maintenance_runs (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ DEFAULT now(),
    decayed INT DEFAULT 0,
    garbage_collected INT DEFAULT 0,
    conflicts_resolved INT DEFAULT 0
);

ALTER TABLE maintenance_runs ADD COLUMN IF NOT EXISTS stubs_deleted INT DEFAULT 0;
ALTER TABLE maintenance_runs ADD COLUMN IF NOT EXISTS stubs_promoted INT DEFAULT 0;

-- Partial index to speed up stub cleanup queries
CREATE INDEX IF NOT EXISTS brain_notes_stub_created_at_idx
    ON brain_notes (created_at)
    WHERE status = 'stub';

CREATE TABLE IF NOT EXISTS chat_stream_events (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_stream_events_session_idx
    ON chat_stream_events (session_id, id);
"""
