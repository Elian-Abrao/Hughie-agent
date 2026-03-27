import { useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { fetchNotes, searchNotes } from "../api/client";
import type { BrainNote } from "../api/client";

// ── Config ────────────────────────────────────────────────────────────────────

const NOTE_TYPES = ["", "preference", "pattern", "project", "person", "fact"] as const;

const TYPE_META: Record<string, { label: string; className: string }> = {
  "":           { label: "Todas",       className: "" },
  preference:   { label: "Preferência", className: "bg-blue-950/60 text-blue-300 border-blue-800/60" },
  pattern:      { label: "Padrão",      className: "bg-purple-950/60 text-purple-300 border-purple-800/60" },
  project:      { label: "Projeto",     className: "bg-green-950/60 text-green-300 border-green-800/60" },
  person:       { label: "Pessoa",      className: "bg-orange-950/60 text-orange-300 border-orange-800/60" },
  fact:         { label: "Fato",        className: "bg-zinc-800/80 text-zinc-400 border-zinc-700" },
};

function typeLabel(type: string) {
  return TYPE_META[type]?.label ?? type;
}

function typeCls(type: string) {
  return TYPE_META[type]?.className ?? "bg-zinc-800/80 text-zinc-400 border-zinc-700";
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function MemoryPage() {
  const [notes, setNotes] = useState<BrainNote[]>([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<BrainNote | null>(null);

  const loadAll = useCallback(async (type: string) => {
    setLoading(true);
    try {
      setNotes(await fetchNotes(type, 200));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!query) loadAll(typeFilter);
  }, [typeFilter, query, loadAll]);

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) { loadAll(typeFilter); return; }
    setLoading(true);
    try {
      setNotes(await searchNotes(q, 30));
    } finally {
      setLoading(false);
    }
  }, [query, typeFilter, loadAll]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
    if (e.key === "Escape") { setQuery(""); loadAll(typeFilter); }
  };

  const handleTypeFilter = (type: string) => {
    setTypeFilter(type);
    setQuery("");
  };

  const handleCardClick = (note: BrainNote) => {
    setSelected((prev) => (prev?.id === note.id ? null : note));
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Notes list ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div className="px-6 py-4 border-b border-border flex-shrink-0 space-y-3">
          {/* Search */}
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Busca semântica nas notas…"
              className="flex-1 bg-surface2 border border-border rounded-lg px-4 py-2 text-sm text-[#e8e8e8] placeholder-muted outline-none focus:border-accent transition-colors"
            />
            <button
              onClick={handleSearch}
              className="px-4 py-2 bg-accent text-white rounded-lg text-sm font-medium hover:opacity-85 transition-opacity"
            >
              Buscar
            </button>
            {query && (
              <button
                onClick={() => { setQuery(""); loadAll(typeFilter); }}
                className="px-3 py-2 border border-border text-muted hover:text-[#e8e8e8] rounded-lg text-sm transition-colors"
              >
                ✕
              </button>
            )}
          </div>

          {/* Type filters */}
          <div className="flex flex-wrap gap-1.5">
            {NOTE_TYPES.map((type) => (
              <button
                key={type}
                onClick={() => handleTypeFilter(type)}
                className={clsx(
                  "px-3 py-1 rounded-full text-xs border transition-colors",
                  typeFilter === type && !query
                    ? "bg-accent text-white border-accent"
                    : "border-border text-muted hover:text-[#e8e8e8] hover:border-[#555]"
                )}
              >
                {typeLabel(type)}
              </button>
            ))}
          </div>

          {/* Count */}
          <p className="text-xs text-muted">
            {loading ? "Carregando…" : `${notes.length} nota${notes.length !== 1 ? "s" : ""}${query ? " encontradas" : ""}`}
          </p>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && (
            <div className="flex items-center justify-center h-32">
              <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {!loading && notes.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="text-5xl mb-3">🧠</div>
              <p className="text-muted text-sm">
                {query ? "Nenhuma nota encontrada para essa busca" : "Nenhuma nota ainda"}
              </p>
            </div>
          )}

          {!loading && notes.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {notes.map((note) => (
                <NoteCard
                  key={note.id}
                  note={note}
                  selected={selected?.id === note.id}
                  onClick={() => handleCardClick(note)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Detail panel ── */}
      {selected && (
        <div className="w-80 flex-shrink-0 border-l border-border bg-surface flex flex-col">
          {/* Panel header */}
          <div className="flex items-center justify-between p-4 border-b border-border">
            <TypeBadge type={selected.type} />
            <button
              onClick={() => setSelected(null)}
              className="text-muted hover:text-[#e8e8e8] transition-colors text-lg leading-none"
              aria-label="Fechar"
            >
              ✕
            </button>
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <h2 className="text-[#e8e8e8] font-semibold text-base leading-snug">
              {selected.title}
            </h2>
            <p className="text-sm text-[#b8b8b8] leading-relaxed whitespace-pre-wrap">
              {selected.content}
            </p>

            <div className="pt-3 border-t border-border space-y-1.5 text-xs text-muted">
              <div className="flex justify-between">
                <span>Importância</span>
                <span className="text-[#e8e8e8]">{selected.importance.toFixed(1)}</span>
              </div>
              <div className="flex justify-between">
                <span>Status</span>
                <span className="text-[#e8e8e8] capitalize">{selected.status}</span>
              </div>
              <div className="flex justify-between">
                <span>Atualizado</span>
                <span className="text-[#e8e8e8]">
                  {new Date(selected.updated_at).toLocaleDateString("pt-BR")}
                </span>
              </div>
              <p className="font-mono text-[10px] break-all text-muted/60 pt-1">{selected.id}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── NoteCard ──────────────────────────────────────────────────────────────────

function NoteCard({
  note,
  selected,
  onClick,
}: {
  note: BrainNote;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "text-left p-4 rounded-xl border transition-all space-y-2 hover:shadow-lg",
        selected
          ? "border-accent bg-accent-dim shadow-[0_0_0_1px_#7c6af7]"
          : "border-border bg-surface hover:border-[#4a4a4a] hover:bg-surface2"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-[#e8e8e8] leading-snug">{note.title}</p>
        <TypeBadge type={note.type} />
      </div>
      <p className="text-xs text-muted leading-relaxed line-clamp-3">{note.content}</p>
      {note.importance > 1.2 && (
        <div className="flex items-center gap-1">
          <span className="text-yellow-400 text-xs">★</span>
          <span className="text-xs text-muted">{note.importance.toFixed(1)}</span>
        </div>
      )}
    </button>
  );
}

// ── TypeBadge ─────────────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  return (
    <span
      className={clsx(
        "text-xs px-2 py-0.5 rounded-full border flex-shrink-0",
        typeCls(type)
      )}
    >
      {typeLabel(type)}
    </span>
  );
}
